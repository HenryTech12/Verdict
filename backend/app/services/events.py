from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class Event:
    id: int
    name: str
    data: dict[str, Any]


class EventBus:
    """In-process ring buffer behind the /stream server-sent-events endpoint."""

    def __init__(self) -> None:
        self._events: deque[Event] = deque(maxlen=500)
        self._next_id = 1
        self._lock = Lock()

    def publish(self, name: str, data: dict[str, Any]) -> Event:
        with self._lock:
            event = Event(self._next_id, name, data)
            self._next_id += 1
            self._events.append(event)
            return event

    def after(self, event_id: int) -> list[Event]:
        with self._lock:
            return [event for event in self._events if event.id > event_id]

    def latest_id(self) -> int:
        with self._lock:
            return self._next_id - 1


event_bus = EventBus()
