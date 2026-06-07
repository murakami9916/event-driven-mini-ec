from __future__ import annotations

from datetime import datetime, timezone

from app.application.dto.models import StoredEvent
from app.application.exceptions import NotFound
from app.application.ports.publisher import EventPublisher
from app.application.ports.uow import UnitOfWorkFactory


class ReplayEventUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory, publisher: EventPublisher) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher

    def execute(self, event_id: str) -> dict[str, str]:
        with self._uow_factory() as uow:
            event = uow.events.get(event_id)
            if event is None:
                raise NotFound(f"event not found: {event_id}")
        message_id = self._publisher.publish(event)
        return {"event_id": event.event_id, "redis_message_id": message_id}


class RedriveDeadLetterUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory, publisher: EventPublisher) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher

    def execute(self, dead_letter_id: int) -> dict[str, str | int]:
        with self._uow_factory() as uow:
            dead_letter = uow.dead_letters.get(dead_letter_id)
            if dead_letter is None:
                raise NotFound(f"dead letter not found: {dead_letter_id}")

            event = StoredEvent(
                id=0,
                event_id=dead_letter.event_id,
                event_type=dead_letter.event_type,
                aggregate_type="dead-letter",
                aggregate_id=dead_letter.event_id,
                payload=dead_letter.payload,
                occurred_at=dead_letter.redriven_at or datetime.now(timezone.utc),
            )
            message_id = self._publisher.publish(event)
            uow.dead_letters.mark_redriven(dead_letter_id)
            uow.commit()
            return {
                "dead_letter_id": dead_letter_id,
                "event_id": dead_letter.event_id,
                "redis_message_id": message_id,
            }
