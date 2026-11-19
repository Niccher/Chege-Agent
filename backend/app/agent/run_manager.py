import asyncio
from datetime import datetime, timezone
import json
import re
import time
from typing import Any, Dict
from sqlmodel import Session, select

from backend.app.agent.approval_engine import ApprovalEngine
from backend.app.agent.context import ContextBuilder
from backend.app.agent.loop_guard import LoopGuard, StalledExecutionError
from backend.app.core.logging import get_logger
from backend.app.db.database import get_db_engine
from backend.app.db.models import Message, Project, Run, Session as DBSession, ToolCall, utc_now
from backend.app.events.manager import get_event_manager
from backend.app.providers.base import ModelOptions, Provider
from backend.app.tools import governance
from backend.app.tools.base import ToolContext
from backend.app.tools.registry import get_tool_registry

logger = get_logger("agent.run_manager")


def _elapsed_ms_since(started_at: datetime | None) -> int:
    """Return elapsed wall-clock milliseconds for timezone-aware/naive runs."""
    if started_at is None:
        return 0
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return max(0, int((utc_now() - started_at).total_seconds() * 1000))


class RunManager:
    """
    Supervises asynchronous execution of agent runs (AGT-05), supporting real-time SSE,
    loop protection (AGT-03), context budgeting (CTX-01), and approval pauses (AGT-07).
    """

    def __init__(self, provider: Provider, sandbox_factory: Any):
        self.provider = provider
        self.sandbox_factory = sandbox_factory
        self.registry = get_tool_registry()
        self.event_mgr = get_event_manager()
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, asyncio.Event] = {}
        # Provider instance actually used per run, so an approval resume reuses
        # the same instance instead of constructing a new (possibly real) one.
        self._providers: Dict[str, Any] = {}

    def is_running(self, run_id: str) -> bool:
        return run_id in self._active_tasks and not self._active_tasks[run_id].done()

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel an active run (AGT-05)."""
        if run_id in self._cancel_events:
            self._cancel_events[run_id].set()

        engine = get_db_engine()
        with Session(engine, expire_on_commit=False) as db:
            run = db.get(Run, run_id)
            if run and run.status in ("running", "awaiting_approval"):
                run.status = "cancelled"
                run.completed_at = utc_now()
                run.duration_ms = _elapsed_ms_since(run.created_at)
                db.add(run)
                db.commit()
                self._providers.pop(run_id, None)
                await self.event_mgr.emit(db, run_id, "run.cancelled", {"run_id": run_id})
                logger.info(f"Run {run_id} cancelled.")
                return True
        return False

    async def start_run(
        self,
        run_id: str,
        session_id: str,
        user_prompt: str,
        model_name: str,
        max_steps: int = 50,
        policy_mode: str = "auto_edit",
        provider_name: str | None = None,
    ) -> None:
        """Launch background run task with optional provider override (MDL-01)."""
        cancel_evt = asyncio.Event()
        self._cancel_events[run_id] = cancel_evt

        task = asyncio.create_task(
            self._execute_loop(
                run_id=run_id,
                session_id=session_id,
                user_prompt=user_prompt,
                model_name=model_name,
                max_steps=max_steps,
                policy_mode=policy_mode,
                cancel_evt=cancel_evt,
                provider_name=provider_name,
            )
        )
        self._active_tasks[run_id] = task

    def _parse_text_tool_calls(self, content: str) -> list[dict]:
        """Strict text protocol parsing for models in text mode (AGT-06, SEC-05)."""
        calls = []
        pattern = r"<tool_call>\s*(.*?)\s*</tool_call>"
        for match in re.finditer(pattern, content, re.DOTALL):
            raw_json = match.group(1).strip()
            try:
                data, _ = json.JSONDecoder().raw_decode(raw_json)
                if isinstance(data, dict) and "name" in data and "arguments" in data:
                    calls.append({
                        "id": f"tc_{len(calls) + 1}",
                        "function": {"name": data["name"], "arguments": data["arguments"]}
                    })
            except Exception:
                continue
        return calls

    async def _execute_loop(
        self,
        run_id: str,
        session_id: str,
        user_prompt: str | None,
        model_name: str,
        max_steps: int,
        policy_mode: str,
        cancel_evt: asyncio.Event,
        provider_name: str | None = None,
    ) -> None:
        from backend.app.providers.factory import get_provider
        # Reuse the provider chosen at run start (important for approval
        # resumes and for injected test providers). Only resolve a new one on
        # the first pass for this run.
        active_provider = self._providers.get(run_id)
        if active_provider is None:
            active_provider = get_provider(provider_name) if provider_name else self.provider
            self._providers[run_id] = active_provider
        engine = get_db_engine()
        loop_guard = LoopGuard()
        run_started = time.monotonic()
        prompt_tokens = 0
        completion_tokens = 0
        thinking_started = None
        thinking_ended = None

        try:
            with Session(engine, expire_on_commit=False) as db:
                session_rec = db.get(DBSession, session_id)
                if not session_rec:
                    logger.error(f"Session {session_id} not found.")
                    return

                project_rec = db.get(Project, session_rec.project_id)
                if not project_rec:
                    logger.error(f"Project for session {session_id} not found.")
                    return

                run = db.get(Run, run_id)
                if not run:
                    run = Run(id=run_id, session_id=session_id, model=model_name, provider="default")
                    db.add(run)
                    db.commit()

                # Record user prompt if supplied
                if user_prompt:
                    user_msg = Message(session_id=session_id, role="user", content=user_prompt)
                    db.add(user_msg)
                    db.commit()

                await self.event_mgr.emit(db, run_id, "run.started", {"run_id": run_id, "model": model_name})
                await self.event_mgr.emit(
                    db, run_id, "run.phase", {"phase": "preparing", "label": "Preparing workspace", "step": 0, "max_steps": max_steps}
                )

                from backend.app.core.config import get_settings
                settings = get_settings()
                workspace_root = settings.project_root(project_rec.slug)
                workspace_root.mkdir(parents=True, exist_ok=True)
                deadline = time.monotonic() + settings.run_timeout_seconds

                # Automatic pre-run checkpoint: every mutating tool that follows
                # can be undone with POST /api/v1/runs/{id}/revert.
                from backend.app.agent.checkpoints import CheckpointManager
                CheckpointManager.create_checkpoint(workspace_root, run_id, project_rec.id, db)

                sandbox = self.sandbox_factory(workspace_root, project_rec.slug)
                approval_engine = ApprovalEngine(db, project_rec.id, policy_mode, run_id=run_id)
                tool_ctx = ToolContext(
                    project_slug=project_rec.slug,
                    workspace_root=workspace_root,
                    session_id=session_id,
                    run_id=run_id,
                    sandbox=sandbox,
                    db=db,
                )

            for step in range(max_steps):
                if cancel_evt.is_set():
                    with Session(engine, expire_on_commit=False) as db:
                        run = db.get(Run, run_id)
                        if run and run.status == "running":
                            run.status = "cancelled"
                            run.completed_at = utc_now()
                            run.duration_ms = _elapsed_ms_since(run.created_at)
                            db.add(run)
                            db.commit()
                            await self.event_mgr.emit(db, run_id, "run.cancelled", {"status": "cancelled"})
                    return


                with Session(engine, expire_on_commit=False) as db:
                    # Refresh session and project records
                    session_rec = db.get(DBSession, session_id)
                    project_rec = db.get(Project, session_rec.project_id)
                    history = list(
                        db.exec(
                            select(Message)
                            .where(Message.session_id == session_id)
                            .order_by(Message.created_at.asc())
                        ).all()
                    )

                    await self.event_mgr.emit(
                        db, run_id, "run.phase",
                        {"phase": "planning", "label": f"Planning step {step + 1} of {max_steps}", "step": step + 1, "max_steps": max_steps},
                    )

                    # Only enabled tools are advertised to the model. Tool
                    # schemas are measured and subtracted before history is
                    # built, preventing the 12k-prompt / 4k-server mismatch.
                    enabled = governance.enabled_tool_names(db)
                    tool_schemas = self.registry.get_schemas(enabled)
                    tool_tokens = len(json.dumps(tool_schemas)) // 4 + 8 * len(tool_schemas)

                    target_provider = (provider_name or settings.default_provider or "").lower()
                    num_ctx = settings.ollama_num_ctx if target_provider == "ollama" else settings.default_context_window
                    reserve = max(512, min(2048, settings.default_context_window // 8))
                    options = ModelOptions(
                        num_ctx=num_ctx,
                        temperature=settings.default_temperature,
                        top_p=settings.default_top_p,
                        keep_alive=settings.ollama_keep_alive,
                    )

                    ctx_builder = ContextBuilder(
                        workspace_root, project_rec, session_rec,
                        max_budget=settings.default_context_window,
                    )
                    system_prompt = ctx_builder.build_system_prompt()
                    assembled = ctx_builder.assemble_messages(
                        history, system_prompt, reserve_for_completion=reserve, tool_tokens=tool_tokens
                    )

                    # Stream model response with a cumulative run deadline.
                    accumulated_content = []
                    accumulated_thinking = []
                    streamed_tool_calls = []
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"Run exceeded its {settings.run_timeout_seconds}s time limit. "
                            "Increase 'Run timeout' in Settings or reduce the task."
                        )

                    await self.event_mgr.emit(
                        db, run_id, "run.phase",
                        {"phase": "model", "label": "Waiting for the model", "step": step + 1, "max_steps": max_steps},
                    )

                    try:
                        async with asyncio.timeout(remaining):
                            async for chunk in active_provider.stream_chat(
                                model=model_name,
                                messages=assembled,
                                tools=tool_schemas,
                                options=options,
                            ):
                                if cancel_evt.is_set():
                                    break

                                if chunk.delta_content:
                                    accumulated_content.append(chunk.delta_content)
                                    await self.event_mgr.emit(
                                        db, run_id, "message.delta", {"content": chunk.delta_content}
                                    )

                                if chunk.delta_thinking:
                                    now = time.monotonic()
                                    if thinking_started is None:
                                        thinking_started = now
                                    thinking_ended = now
                                    accumulated_thinking.append(chunk.delta_thinking)
                                    await self.event_mgr.emit(
                                        db, run_id, "thinking.delta", {"thinking": chunk.delta_thinking}
                                    )

                                if chunk.prompt_tokens:
                                    prompt_tokens = max(prompt_tokens, int(chunk.prompt_tokens))
                                if chunk.completion_tokens:
                                    completion_tokens = max(completion_tokens, int(chunk.completion_tokens))

                                if chunk.tool_calls:
                                    streamed_tool_calls.extend(chunk.tool_calls)
                    except TimeoutError as e:
                        logger.warning(f"Run {run_id} timed out: {e}")
                        run = db.get(Run, run_id)
                        run.status = "failed"
                        run.completed_at = utc_now()
                        run.duration_ms = _elapsed_ms_since(run.created_at)
                        db.add(run)
                        db.commit()
                        await self.event_mgr.emit(
                            db, run_id, "run.failed",
                            {"error": str(e) or "Run exceeded its time limit"},
                        )
                        return
                    except Exception as e:
                        logger.error(f"Provider inference failed: {e}")
                        run = db.get(Run, run_id)
                        run.status = "failed"
                        run.completed_at = utc_now()
                        run.duration_ms = _elapsed_ms_since(run.created_at)
                        db.add(run)
                        db.commit()
                        detail = str(e).strip() or f"{type(e).__name__}: provider request failed or timed out"
                        await self.event_mgr.emit(db, run_id, "run.failed", {"error": detail})
                        return

                    await self.event_mgr.emit(
                        db, run_id, "run.phase",
                        {"phase": "working", "label": "Reviewing the response", "step": step + 1, "max_steps": max_steps},
                    )

                    full_content = "".join(accumulated_content)
                    full_thinking = "".join(accumulated_thinking)

                    # Check for tool calls (native or text protocol fallback)
                    effective_tool_calls = streamed_tool_calls or self._parse_text_tool_calls(full_content)

                    if not effective_tool_calls:
                        # Model finished reasoning and returned final text response
                        run = db.get(Run, run_id)
                        elapsed_ms = (
                            _elapsed_ms_since(run.created_at)
                            if run is not None
                            else int((time.monotonic() - run_started) * 1000)
                        )
                        thinking_ms = (
                            int((thinking_ended - thinking_started) * 1000)
                            if thinking_started is not None and thinking_ended is not None
                            else 0
                        )
                        metrics = {
                            "run_id": run_id,
                            "model": model_name,
                            "duration_ms": elapsed_ms,
                            "thinking_ms": thinking_ms,
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens,
                        }
                        assistant_msg = Message(
                            session_id=session_id,
                            role="assistant",
                            content=full_content,
                            thinking=full_thinking if full_thinking else None,
                            metrics_json=json.dumps(metrics),
                        )
                        db.add(assistant_msg)
                        run = db.get(Run, run_id)
                        run.status = "completed"
                        run.prompt_tokens = prompt_tokens
                        run.completion_tokens = completion_tokens
                        run.total_tokens = prompt_tokens + completion_tokens
                        run.duration_ms = elapsed_ms
                        run.completed_at = utc_now()
                        db.add(run)
                        db.commit()
                        await self.event_mgr.emit(
                            db, run_id, "run.completed",
                            {"status": "completed", "metrics": metrics},
                        )
                        return

                    # Record assistant message with proposed tool calls
                    assistant_msg = Message(
                        session_id=session_id,
                        role="assistant",
                        content=full_content,
                        thinking=full_thinking if full_thinking else None,
                        tool_calls_json=json.dumps(effective_tool_calls),
                    )
                    db.add(assistant_msg)
                    db.commit()

                    await self.event_mgr.emit(
                        db, run_id, "run.phase",
                        {"phase": "evaluating", "label": "Planning tool calls", "step": step + 1, "max_steps": max_steps},
                    )

                    # Evaluate approvals and loop guards for each proposed call
                    pending_proposals = []
                    for tc in effective_tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args = fn.get("arguments", {})
                        tc_id = tc.get("id") or str(fn_name)

                        if isinstance(fn_args, str):
                            try:
                                fn_args = json.loads(fn_args)
                            except Exception:
                                fn_args = {}

                        tool_instance = self.registry.get(fn_name)
                        if not tool_instance:
                            err_msg = Message(
                                session_id=session_id,
                                role="tool",
                                tool_name=fn_name,
                                tool_call_id=tc_id,
                                content=f"ERROR: Unknown tool '{fn_name}'",
                            )
                            db.add(err_msg)
                            db.commit()
                            continue

                        # LoopGuard check (AGT-03)
                        try:
                            warning = loop_guard.record_call(fn_name, fn_args)
                            if warning:
                                warn_msg = Message(session_id=session_id, role="system", content=warning)
                                db.add(warn_msg)
                                db.commit()
                        except StalledExecutionError as se:
                            run = db.get(Run, run_id)
                            run.status = "stalled"
                            db.add(run)
                            db.commit()
                            await self.event_mgr.emit(db, run_id, "run.failed", {"error": str(se)})
                            return

                        # Evaluate approval
                        decision = approval_engine.evaluate(tool_instance, fn_args)
                        if decision.requires_approval:
                            pending_record = approval_engine.create_pending_tool_call(run_id, tool_instance, fn_args)
                            pending_proposals.append({
                                "id": pending_record.id,
                                "tool": fn_name,
                                "arguments": fn_args,
                                "risk": tool_instance.risk.value,
                                "reason": decision.reason,
                            })

                    if pending_proposals:
                        # Halt loop and wait for user approval (AGT-07)
                        run = db.get(Run, run_id)
                        run.status = "awaiting_approval"
                        db.add(run)
                        db.commit()
                        await self.event_mgr.emit(
                            db, run_id, "run.phase",
                            {"phase": "awaiting_approval", "label": "Waiting for your approval", "step": step + 1, "max_steps": max_steps},
                        )
                        await self.event_mgr.emit(
                            db, run_id, "tool.approval_required", {"pending": pending_proposals}
                        )
                        return

                    # All tool calls safe to execute automatically!
                    for tc in effective_tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args = fn.get("arguments", {})
                        tc_id = tc.get("id") or str(fn_name)

                        if isinstance(fn_args, str):
                            try:
                                fn_args = json.loads(fn_args)
                            except Exception:
                                fn_args = {}

                        tool_instance = self.registry.get(fn_name)
                        if not tool_instance:
                            continue

                        # Execution-time guard: text-protocol tool calls that
                        # were never in the advertised schema must still be
                        # refused when the tool is disabled.
                        if not governance.is_enabled(db, fn_name):
                            db.add(Message(
                                session_id=session_id,
                                role="tool",
                                tool_name=fn_name,
                                tool_call_id=tc_id,
                                content=f"ERROR: Tool '{fn_name}' is disabled in the Tools console.",
                            ))
                            db.commit()
                            continue

                        # Persist every executed call, including auto-approved
                        # calls, so GET /runs/{id} is a complete audit trail.
                        tool_record = ToolCall(
                            run_id=run_id,
                            tool_name=fn_name,
                            arguments_json=json.dumps(fn_args),
                            status="executing",
                            risk=tool_instance.risk.value,
                        )
                        db.add(tool_record)
                        db.commit()
                        db.refresh(tool_record)

                        await self.event_mgr.emit(
                            db, run_id, "run.phase",
                            {"phase": "tool", "label": f"Running {fn_name}", "step": step + 1, "max_steps": max_steps},
                        )
                        await self.event_mgr.emit(
                            db, run_id, "tool.started", {"tool": fn_name, "arguments": fn_args}
                        )

                        try:
                            args_obj = tool_instance.args_model(**fn_args)
                            result = await tool_instance.run(tool_ctx, args_obj)
                        except Exception as ex:
                            result_str = f"ERROR executing {fn_name}: {str(ex)}"
                            loop_guard.record_result(is_error=True)
                            tool_record.status = "failed"
                            tool_record.error = result_str
                        else:
                            result_str = result.content
                            loop_guard.record_result(is_error=result.is_error)
                            tool_record.status = "failed" if result.is_error else "completed"
                        tool_record.result = result_str
                        db.add(tool_record)
                        db.commit()

                        tool_msg = Message(
                            session_id=session_id,
                            role="tool",
                            tool_name=fn_name,
                            tool_call_id=tc_id,  # AGT-02: associate tool call ID
                            content=result_str,
                        )
                        db.add(tool_msg)
                        db.commit()

                        await self.event_mgr.emit(
                            db, run_id, "tool.completed", {"tool": fn_name, "result": result_str[:400]}
                        )

            # Reached max steps limit
            with Session(engine, expire_on_commit=False) as db:
                run = db.get(Run, run_id)
                if run and run.status == "running":
                    elapsed_ms = _elapsed_ms_since(run.created_at)
                    run.status = "completed"
                    run.prompt_tokens = prompt_tokens
                    run.completion_tokens = completion_tokens
                    run.total_tokens = prompt_tokens + completion_tokens
                    run.duration_ms = elapsed_ms
                    run.completed_at = utc_now()
                    limit_msg = Message(
                        session_id=session_id,
                        role="assistant",
                        content="Operational budget limit reached (maximum steps). Let me know how you would like to proceed.",
                        metrics_json=json.dumps({
                            "run_id": run_id,
                            "model": model_name,
                            "duration_ms": elapsed_ms,
                            "thinking_ms": (
                                int((thinking_ended - thinking_started) * 1000)
                                if thinking_started is not None and thinking_ended is not None
                                else 0
                            ),
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens,
                        }),
                    )
                    db.add(limit_msg)
                    db.add(run)
                    db.commit()
                    await self.event_mgr.emit(
                        db, run_id, "run.phase",
                        {"phase": "done", "label": "Step limit reached", "step": max_steps, "max_steps": max_steps},
                    )
                    await self.event_mgr.emit(db, run_id, "run.completed", {"status": "budget_limit"})

        except Exception as e:
            logger.error(f"Fatal error in run loop {run_id}: {e}", exc_info=True)
            with Session(engine, expire_on_commit=False) as db:
                run = db.get(Run, run_id)
                if run and run.status not in ("completed", "cancelled"):
                    run.status = "failed"
                    run.completed_at = utc_now()
                    run.duration_ms = _elapsed_ms_since(run.created_at)
                    db.add(run)
                    db.commit()
                    await self.event_mgr.emit(
                        db, run_id, "run.failed",
                        {"error": str(e).strip() or f"{type(e).__name__}: run failed"},
                    )
        finally:
            self._active_tasks.pop(run_id, None)
            self._cancel_events.pop(run_id, None)
            # Keep the provider only while a run may resume after approval.
            # Completed/failed/cancelled runs were leaking provider instances
            # for the lifetime of the process.
            try:
                with Session(engine) as db:
                    run = db.get(Run, run_id)
                    if not run or run.status != "awaiting_approval":
                        self._providers.pop(run_id, None)
            except Exception:
                self._providers.pop(run_id, None)

    async def continue_run(
        self,
        run_id: str,
        approvals: list[dict],
        model_name: str,
        policy_mode: str = "auto_edit",
    ) -> None:
        """Resume execution of an awaiting_approval run after user feedback (AGT-07)."""
        engine = get_db_engine()
        with Session(engine, expire_on_commit=False) as db:
            run = db.get(Run, run_id)
            if not run or run.status != "awaiting_approval":
                raise ValueError(f"Run {run_id} is not awaiting approval.")

            session_rec = db.get(DBSession, run.session_id)
            project_rec = db.get(Project, session_rec.project_id)
            from backend.app.core.config import get_settings
            settings = get_settings()
            workspace_root = settings.project_root(project_rec.slug)
            sandbox = self.sandbox_factory(workspace_root, project_rec.slug)
            await self.event_mgr.emit(
                db, run_id, "run.phase", {"phase": "resuming", "label": "Resuming after approval", "step": 0, "max_steps": settings.max_steps}
            )
            tool_ctx = ToolContext(
                project_slug=project_rec.slug,
                workspace_root=workspace_root,
                session_id=session_rec.id,
                run_id=run_id,
                sandbox=sandbox,
                db=db,
            )

            # Process user approvals
            for item in approvals:
                call_id = item.get("id")
                action = item.get("action")  # "approve" or "reject"
                edited_args = item.get("arguments")

                tc = db.get(ToolCall, call_id)
                if not tc:
                    continue

                tool_instance = self.registry.get(tc.tool_name)
                if action == "approve" and tool_instance:
                    args_to_use = edited_args if edited_args is not None else json.loads(tc.arguments_json)
                    tc.status = "approved"
                    if edited_args is not None:
                        tc.edited_by_user = True
                        tc.arguments_json = json.dumps(edited_args)
                    db.add(tc)
                    db.commit()

                    # Approving a grant prompt records a run-scoped grant.
                    if governance.grant_required(db, tc.tool_name):
                        governance.grant_tool(db, run_id, tc.tool_name)

                    if not governance.is_enabled(db, tc.tool_name):
                        res_content = f"ERROR: Tool '{tc.tool_name}' was disabled before approval; not executed."
                        tc.status = "failed"
                        tc.error = res_content
                    else:
                        await self.event_mgr.emit(
                            db, run_id, "run.phase",
                            {"phase": "tool", "label": f"Running {tc.tool_name}", "step": 0, "max_steps": settings.max_steps},
                        )
                        await self.event_mgr.emit(
                            db, run_id, "tool.started",
                            {"tool": tc.tool_name, "arguments": args_to_use},
                        )
                        try:
                            args_obj = tool_instance.args_model(**args_to_use)
                            result = await tool_instance.run(tool_ctx, args_obj)
                            res_content = result.content
                            tc.status = "completed"
                        except Exception as ex:
                            res_content = f"ERROR: {str(ex)}"
                            tc.status = "failed"
                            tc.error = res_content
                        tc.result = res_content
                        await self.event_mgr.emit(
                            db, run_id, "tool.completed",
                            {"tool": tc.tool_name, "result": res_content[:400]},
                        )

                    db.add(tc)
                    tool_msg = Message(
                        session_id=session_rec.id,
                        role="tool",
                        tool_name=tc.tool_name,
                        tool_call_id=tc.id,
                        content=res_content,
                    )
                    db.add(tool_msg)
                    db.commit()
                else:
                    tc.status = "rejected"
                    db.add(tc)
                    db.commit()
                    tool_msg = Message(
                        session_id=session_rec.id,
                        role="tool",
                        tool_name=tc.tool_name,
                        tool_call_id=tc.id,
                        content="ERROR: User denied execution of this tool call.",
                    )
                    db.add(tool_msg)
                    db.commit()

            # Set run back to running and resume loop
            run.status = "running"
            db.add(run)
            db.commit()

        cancel_evt = asyncio.Event()
        self._cancel_events[run_id] = cancel_evt
        task = asyncio.create_task(
            self._execute_loop(
                run_id=run_id,
                session_id=session_rec.id,
                user_prompt=None,  # continuing existing conversation
                model_name=model_name,
                max_steps=settings.max_steps,
                policy_mode=policy_mode,
                cancel_evt=cancel_evt,
                # No provider_name: _execute_loop reuses self._providers[run_id]
                provider_name=None,
            )
        )
        self._active_tasks[run_id] = task
