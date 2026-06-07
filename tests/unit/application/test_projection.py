from app.application.dto.models import CreateOrderCommand, InventoryAdjustmentCommand, OrderLineInput
from app.application.use_cases.adjust_inventory import AdjustInventoryUseCase
from app.application.use_cases.create_order import CreateOrderUseCase
from app.application.use_cases.create_shipment import CreateShipmentUseCase
from app.application.use_cases.projections import (
    ApplyOrderSummaryProjectionUseCase,
    RebuildOrderSummaryUseCase,
)
from app.application.use_cases.reserve_inventory import ReserveInventoryUseCase
from tests.unit.application.fakes import InMemoryState, fake_uow_factory


def test_projection_worker_is_idempotent_per_event_id() -> None:
    state = InMemoryState()
    uow_factory = fake_uow_factory(state)
    CreateOrderUseCase(uow_factory).execute(
        CreateOrderCommand("key-1", [OrderLineInput("SKU-001", 1)])
    )
    event = state.events[0]
    use_case = ApplyOrderSummaryProjectionUseCase(uow_factory)

    use_case.execute(event)
    duplicate = use_case.execute(event)

    assert duplicate.duplicate is True
    assert state.order_summary.orders_created == 1


def test_rebuild_order_summary_replays_event_log_from_scratch() -> None:
    state = InMemoryState()
    uow_factory = fake_uow_factory(state)
    AdjustInventoryUseCase(uow_factory).execute(InventoryAdjustmentCommand("SKU-001", 10))
    CreateOrderUseCase(uow_factory).execute(
        CreateOrderCommand("key-1", [OrderLineInput("SKU-001", 1)])
    )
    order_created = state.events[1]
    ReserveInventoryUseCase(uow_factory).execute(order_created)
    inventory_reserved = state.events[-1]
    CreateShipmentUseCase(uow_factory).execute(inventory_reserved)
    state.order_summary.orders_created = 99

    summary = RebuildOrderSummaryUseCase(uow_factory).execute()

    assert summary.orders_created == 1
    assert summary.inventory_reserved == 1
    assert summary.inventory_rejected == 0
    assert summary.shipments_created == 1

