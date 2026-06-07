from __future__ import annotations

import logging
import time

from app.config import get_settings
from app.infrastructure.db.session import create_session_factory, init_database
from app.infrastructure.db.uow import SqlAlchemyUnitOfWork
from app.infrastructure.redis.publisher import RedisStreamPublisher


LOGGER = logging.getLogger(__name__)


class OutboxRelay:
    def __init__(
        self,
        uow_factory,
        publisher: RedisStreamPublisher,
        batch_size: int = 100,
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._batch_size = batch_size

    def run_once(self) -> int:
        published = 0
        with self._uow_factory() as uow:
            events = uow.events.list_unpublished(self._batch_size)
            for event in events:
                self._publisher.publish(event)
                uow.events.mark_published(event.event_id)
                published += 1
            uow.commit()
        return published


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    init_database(settings.database_url)
    session_factory = create_session_factory(settings.database_url)
    relay = OutboxRelay(
        uow_factory=lambda: SqlAlchemyUnitOfWork(session_factory),
        publisher=RedisStreamPublisher(settings.redis_url, settings.event_stream),
    )
    while True:
        try:
            count = relay.run_once()
            if count:
                LOGGER.info("published %s outbox events", count)
        except Exception:
            LOGGER.exception("outbox relay failed")
        time.sleep(settings.outbox_poll_seconds)


if __name__ == "__main__":
    main()

