from __future__ import annotations

import logging
import sys

from app.application.dto.models import StoredEvent
from app.application.use_cases.create_shipment import CreateShipmentUseCase
from app.application.use_cases.projections import ApplyOrderSummaryProjectionUseCase
from app.application.use_cases.reserve_inventory import ReserveInventoryUseCase
from app.config import get_settings
from app.infrastructure.db.session import create_session_factory, init_database
from app.infrastructure.db.uow import SqlAlchemyUnitOfWork
from app.infrastructure.redis.consumer import RedisStreamConsumer


def _add_dead_letter(uow_factory, consumer_name: str):
    def add(event: StoredEvent, error: str, failures: int) -> None:
        with uow_factory() as uow:
            uow.dead_letters.add(consumer_name, event, error, failures)
            uow.commit()

    return add


def build_consumer(role: str) -> RedisStreamConsumer:
    settings = get_settings()
    init_database(settings.database_url)
    session_factory = create_session_factory(settings.database_url)
    uow_factory = lambda: SqlAlchemyUnitOfWork(session_factory)

    if role == "inventory":
        use_case = ReserveInventoryUseCase(uow_factory)
        consumer_name = use_case.consumer_name
        handler = use_case.execute
    elif role == "shipping":
        use_case = CreateShipmentUseCase(uow_factory)
        consumer_name = use_case.consumer_name
        handler = use_case.execute
    elif role == "projection":
        use_case = ApplyOrderSummaryProjectionUseCase(uow_factory)
        consumer_name = use_case.consumer_name
        handler = use_case.execute
    else:
        raise ValueError("role must be one of: inventory, shipping, projection")

    return RedisStreamConsumer(
        redis_url=settings.redis_url,
        stream_name=settings.event_stream,
        group_name=consumer_name,
        consumer_name=f"{consumer_name}-1",
        handler=handler,
        dead_letter_handler=_add_dead_letter(uow_factory, consumer_name),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    role = sys.argv[1] if len(sys.argv) > 1 else ""
    build_consumer(role).run_forever()


if __name__ == "__main__":
    main()

