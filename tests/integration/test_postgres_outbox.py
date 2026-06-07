import os

import pytest
from sqlalchemy import create_engine

from app.application.dto.models import CreateOrderCommand, OrderLineInput
from app.application.use_cases.create_order import CreateOrderUseCase
from app.infrastructure.db.models import Base
from app.infrastructure.db.session import create_session_factory
from app.infrastructure.db.uow import SqlAlchemyUnitOfWork


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for PostgreSQL integration tests",
)


def test_create_order_and_mark_outbox_event_published() -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    engine = create_engine(database_url, future=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session_factory = create_session_factory(database_url)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    CreateOrderUseCase(uow_factory).execute(
        CreateOrderCommand("key-1", [OrderLineInput("SKU-001", 1)])
    )

    with uow_factory() as uow:
        events = uow.events.list_unpublished(10)
        assert len(events) == 1
        uow.events.mark_published(events[0].event_id)
        uow.commit()

    with uow_factory() as uow:
        assert uow.events.list_unpublished(10) == []
