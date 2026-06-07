from __future__ import annotations

from typing import Protocol

from app.application.dto.models import StoredEvent


class EventPublisher(Protocol):
    def publish(self, event: StoredEvent) -> str: ...

