import asyncio
import json
from typing import Dict, List
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select
from backend.app.db.models import Event


class EventManager:
    """
    Publish/Subscribe event broadcaster for Server-Sent Events (RT-01).
    Ensures monotonic sequence ordering and supports ?after=seq replay.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        if run_id not in self._subscribers:
            self._subscribers[run_id] = []
        self._subscribers[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        if run_id in self._subscribers and q in self._subscribers[run_id]:
            self._subscribers[run_id].remove(q)
            if not self._subscribers[run_id]:
                del self._subscribers[run_id]

    async def emit(self, db: Session, run_id: str, event_type: str, payload: dict) -> Event:
        """Persist an event with a DB-derived, gap-free per-run sequence.

        The sequence is computed inside the transaction with SELECT MAX(seq)+1
        and protected by a unique index. On a concurrent-insert collision we
        roll back and recompute, so a process restart can never desync SSE
        sequence numbers (unlike the old in-memory counter).
        """
        payload_str = json.dumps(payload)
        evt: Event | None = None
        for attempt in range(5):
            try:
                seq = db.exec(
                    select(func.coalesce(func.max(Event.seq), 0)).where(Event.run_id == run_id)
                ).one() + 1
                evt = Event(
                    run_id=run_id,
                    seq=seq,
                    event_type=event_type,
                    payload_json=payload_str,
                )
                db.add(evt)
                db.commit()
                db.refresh(evt)
                break
            except IntegrityError:
                db.rollback()
                if attempt == 4:
                    raise
        assert evt is not None

        # Notify active subscriber queues
        if run_id in self._subscribers:
            for q in list(self._subscribers[run_id]):
                await q.put(evt)

        return evt

    def get_events_after(self, db: Session, run_id: str, after_seq: int = 0) -> List[Event]:
        """Fetch historical events for client catchup."""
        statement = (
            select(Event)
            .where(Event.run_id == run_id)
            .where(Event.seq > after_seq)
            .order_by(Event.seq.asc())
        )
        return list(db.exec(statement).all())


_global_event_manager = None


def get_event_manager() -> EventManager:
    global _global_event_manager
    if _global_event_manager is None:
        _global_event_manager = EventManager()
    return _global_event_manager
