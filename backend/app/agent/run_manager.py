import asyncio
import json
from pathlib import Path
import re
from typing import Any, Dict
from sqlmodel import Session, select

from backend.app.agent.approval_engine import ApprovalEngine
from backend.app.agent.context import ContextBuilder
from backend.app.agent.loop_guard import LoopGuard, StalledExecutionError
from backend.app.core.logging import get_logger
from backend.app.db.database import get_db_engine
from backend.app.db.models import Message, Project, Run, Session as DBSession, ToolCall
from backend.app.events.manager import get_event_manager
from backend.app.providers.base import InternalMessage, ModelOptions, Provider
from backend.app.tools.base import ToolContext
from backend.app.tools.registry import get_tool_registry

logger = get_logger("agent.run_manager")


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

    def is_running(self, run_id: str) -> bool:
        return run_id in self._active_tasks and not self._active_tasks[run_id].done()

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel an active run (AGT-05)."""
        if run_id in self._cancel_events:
            self._cancel_events[run_id].set()

        engine = get_db_engine()
        with Session(engine, expire_on_commit=False) as db:
            run = db.get(Run, run_id)
            if run and run.status == "running":
                run.status = "cancelled"
                db.add(run)
                db.commit()
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
    ) -> None:
        """Launch background run task."""
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
    ) -> None:
        engine = get_db_engine()
        loop_guard = LoopGuard()

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

                from backend.app.core.config import get_settings
                settings = get_settings()
                workspace_root = (settings.workdir / project_rec.slug).resolve()
                workspace_root.mkdir(parents=True, exist_ok=True)
                sandbox = self.sandbox_factory(workspace_root, project_rec.slug)
                approval_engine = ApprovalEngine(db, project_rec.id, policy_mode)
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

                    ctx_builder = ContextBuilder(workspace_root, project_rec, session_rec)
                    system_prompt = ctx_builder.build_system_prompt()
                    assembled = ctx_builder.assemble_messages(history, system_prompt)

                    tool_schemas = self.registry.get_schemas()
                    options = ModelOptions(num_ctx=16384, temperature=0.2)

                    # Stream model response
                    accumulated_content = []
                    accumulated_thinking = []
                    streamed_tool_calls = []

                    try:
                        async for chunk in self.provider.stream_chat(
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
                                accumulated_thinking.append(chunk.delta_thinking)
                                await self.event_mgr.emit(
                                    db, run_id, "thinking.delta", {"thinking": chunk.delta_thinking}
                                )

                            if chunk.tool_calls:
                                streamed_tool_calls.extend(chunk.tool_calls)
                    except Exception as e:
                        logger.error(f"Provider inference failed: {e}")
                        run = db.get(Run, run_id)
                        run.status = "failed"
                        db.add(run)
                        db.commit()
                        await self.event_mgr.emit(db, run_id, "run.failed", {"error": str(e)})
                        return

                    full_content = "".join(accumulated_content)
                    full_thinking = "".join(accumulated_thinking)

                    # Check for tool calls (native or text protocol fallback)
                    effective_tool_calls = streamed_tool_calls or self._parse_text_tool_calls(full_content)

                    if not effective_tool_calls:
                        # Model finished reasoning and returned final text response
                        assistant_msg = Message(
                            session_id=session_id,
                            role="assistant",
                            content=full_content,
                            thinking=full_thinking if full_thinking else None,
                        )
                        db.add(assistant_msg)
                        run = db.get(Run, run_id)
                        run.status = "completed"
                        db.add(run)
                        db.commit()
                        await self.event_mgr.emit(db, run_id, "run.completed", {"status": "completed"})
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

                        await self.event_mgr.emit(
                            db, run_id, "tool.started", {"tool": fn_name, "arguments": fn_args}
                        )

                        try:
                            args_obj = tool_instance.args_model(**fn_args)
                            result = await tool_instance.run(tool_ctx, args_obj)
                        except Exception as ex:
                            result_str = f"ERROR executing {fn_name}: {str(ex)}"
                            loop_guard.record_result(is_error=True)
                        else:
                            result_str = result.content
                            loop_guard.record_result(is_error=result.is_error)

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
                    run.status = "completed"
                    limit_msg = Message(
                        session_id=session_id,
                        role="assistant",
                        content="Operational budget limit reached (maximum steps). Let me know how you would like to proceed.",
                    )
                    db.add(limit_msg)
                    db.add(run)
                    db.commit()
                    await self.event_mgr.emit(db, run_id, "run.completed", {"status": "budget_limit"})

        except Exception as e:
            logger.error(f"Fatal error in run loop {run_id}: {e}", exc_info=True)
            with Session(engine, expire_on_commit=False) as db:
                run = db.get(Run, run_id)
                if run and run.status not in ("completed", "cancelled"):
                    run.status = "failed"
                    db.add(run)
                    db.commit()
                    await self.event_mgr.emit(db, run_id, "run.failed", {"error": str(e)})
        finally:
            self._active_tasks.pop(run_id, None)
            self._cancel_events.pop(run_id, None)

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
            workspace_root = (settings.workdir / project_rec.slug).resolve()
            sandbox = self.sandbox_factory(workspace_root, project_rec.slug)
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

                    try:
                        args_obj = tool_instance.args_model(**args_to_use)
                        result = await tool_instance.run(tool_ctx, args_obj)
                        res_content = result.content
                    except Exception as ex:
                        res_content = f"ERROR: {str(ex)}"

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
                max_steps=50,
                policy_mode=policy_mode,
                cancel_evt=cancel_evt,
            )
        )
        self._active_tasks[run_id] = task
