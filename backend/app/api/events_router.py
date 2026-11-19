import asyncio
import json
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from backend.app.db.database import create_session
from backend.app.events.manager import EventManager, get_event_manager

router = APIRouter(prefix="/runs", tags=["events"])


@router.get("/{run_id}/events")
async def stream_run_events(
    request: Request,
    run_id: str,
    after: int = Query(default=0, description="Replay events strictly after this sequence number (RT-01)"),
    event_mgr: EventManager = Depends(get_event_manager),
):
    """
    Server-Sent Events endpoint streaming real-time tokens, tool outputs, and status (RT-01).
    Supports client reconnection and message catchup via ?after=seq.
    """
    async def event_generator():
        # 1. Catchup: replay historical events if requested
        has_terminal = False
        with create_session() as db:
            past_events = event_mgr.get_events_after(db, run_id, after_seq=after)
            for evt in past_events:
                yield f"id: {evt.seq}\nevent: {evt.event_type}\ndata: {evt.payload_json}\n\n"
                if evt.event_type in ("run.completed", "run.failed", "run.cancelled"):
                    has_terminal = True

        if has_terminal:
            return

        # 2. Subscribe to live events
        queue = event_mgr.subscribe(run_id)
        try:
            while True:
                if await request.is_disconnected():
                    break

                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield f"id: {evt.seq}\nevent: {evt.event_type}\ndata: {evt.payload_json}\n\n"
                    if evt.event_type in ("run.completed", "run.failed", "run.cancelled"):
                        break
                except asyncio.TimeoutError:
                    # Send keep-alive comment
                    yield ": ping\n\n"
        finally:
            event_mgr.unsubscribe(run_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
