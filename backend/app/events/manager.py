import asyncio
import json
from typing import AsyncIterator, Dict, List
from sqlmodel import Session, select
from backend.app.db.models import Event


class EventManager:
    """
    Publish/Subscribe event broadcaster for Server-Sent Events (RT-01).
    Ensures monotonic sequence ordering and supports ?after=seq replay.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._seq_counters: Dict[str, int] = {}

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
        # Monotonic sequence per run
        self._seq_counters[run_id] = self._seq_counters.get(run_id, 0) + 1
        seq = self._seq_counters[run_id]

        payload_str = json.dumps(payload)
        evt = Event(
            run_id=run_id,
            seq=seq,
            event_type=event_type,
            payload_json=payload_str,
        )
        db.add(evt)
        db.commit()
        db.refresh(evt)

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
