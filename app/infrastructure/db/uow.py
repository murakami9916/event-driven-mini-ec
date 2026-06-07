from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.infrastructure.repositories.sqlalchemy_repositories import (
    SqlAlchemyDeadLetterRepository,
    SqlAlchemyEventLogRepository,
    SqlAlchemyIdempotencyRepository,
    SqlAlchemyInventoryRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOrderSummaryRepository,
    SqlAlchemyProcessedEventRepository,
    SqlAlchemyShipmentRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory
        self.session: Session | None = None
        self._committed = False

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.session = self._session_factory()
        self.orders = SqlAlchemyOrderRepository(self.session)
        self.inventory = SqlAlchemyInventoryRepository(self.session)
        self.shipments = SqlAlchemyShipmentRepository(self.session)
        self.events = SqlAlchemyEventLogRepository(self.session)
        self.idempotency = SqlAlchemyIdempotencyRepository(self.session)
        self.processed_events = SqlAlchemyProcessedEventRepository(self.session)
        self.order_summary = SqlAlchemyOrderSummaryRepository(self.session)
        self.dead_letters = SqlAlchemyDeadLetterRepository(self.session)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.session is None:
            return
        if exc_type is not None or not self._committed:
            self.rollback()
        self.session.close()

    def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("unit of work is not active")
        self.session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self.session is not None:
            self.session.rollback()

