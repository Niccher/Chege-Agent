import asyncio
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from backend.app.db.database import create_session
from backend.app.events.manager import EventManager, get_event_manager

router = APIRouter(prefix="/runs", tags=["events"])

_TERMINAL = ("run.completed", "run.failed", "run.cancelled")


@router.get("/{run_id}/events")
async def stream_run_events(
    request: Request,
    run_id: str,
    after: int = Query(default=0, description="Replay events strictly after this sequence number (RT-01)"),
    event_mgr: EventManager = Depends(get_event_manager),
):
    """Stream run events (SSE) with catchup and reconnection support.

    The browser sends ``Last-Event-ID`` on reconnect (or ``?after=`` on a
    manual resume). We subscribe *before* replaying history and drop any live
    event with a sequence we already replayed, so no event is lost or doubled
    in the gap between the two operations.
    """
    # Last-Event-ID is set automatically by EventSource on reconnect; prefer
    # the larger of it and the explicit query parameter.
    header_value = request.headers.get("last-event-id")
    try:
        after = max(after, int(header_value)) if header_value and header_value.isdigit() else after
    except (TypeError, ValueError):
        pass

    async def event_generator():
        # 1. Subscribe before reading history to close the replay race.
        queue = event_mgr.subscribe(run_id)
        has_terminal = False
        last_seq = after
        try:
            with create_session() as db:
                for evt in event_mgr.get_events_after(db, run_id, after_seq=after):
                    yield f"id: {evt.seq}\nevent: {evt.event_type}\ndata: {evt.payload_json}\n\n"
                    last_seq = max(last_seq, evt.seq)
                    if evt.event_type in _TERMINAL:
                        has_terminal = True

            if has_terminal:
                return

            # 2. Stream live events, skipping anything already replayed.
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keep-alive comment
                    continue
                if evt.seq <= last_seq:
                    continue
                last_seq = max(last_seq, evt.seq)
                yield f"id: {evt.seq}\nevent: {evt.event_type}\ndata: {evt.payload_json}\n\n"
                if evt.event_type in _TERMINAL:
                    break
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
