from app.application.dto.models import CreateOrderCommand, InventoryAdjustmentCommand, OrderLineInput
from app.application.use_cases.adjust_inventory import AdjustInventoryUseCase
from app.application.use_cases.create_order import CreateOrderUseCase
from app.application.use_cases.create_shipment import CreateShipmentUseCase
from app.application.use_cases.reserve_inventory import ReserveInventoryUseCase
from app.domain.events.models import (
    INVENTORY_REJECTED,
    INVENTORY_RESERVED,
    ORDER_CREATED,
    SHIPMENT_CREATED,
)
from app.domain.orders.models import OrderStatus
from tests.unit.application.fakes import InMemoryState, fake_uow_factory


def _create_order_event(state: InMemoryState, quantity: int = 2):
    CreateOrderUseCase(fake_uow_factory(state)).execute(
        CreateOrderCommand(
            idempotency_key=f"key-{quantity}",
            items=[OrderLineInput(sku="SKU-001", quantity=quantity)],
        )
    )
    return next(event for event in state.events if event.event_type == ORDER_CREATED)


def test_inventory_worker_reserves_available_inventory_once_for_duplicate_event() -> None:
    state = InMemoryState()
    uow_factory = fake_uow_factory(state)
    AdjustInventoryUseCase(uow_factory).execute(
        InventoryAdjustmentCommand(sku="SKU-001", delta=10)
    )
    order_created = _create_order_event(state)

    use_case = ReserveInventoryUseCase(uow_factory)
    first = use_case.execute(order_created)
    second = use_case.execute(order_created)

    assert first.handled is True
    assert second.duplicate is True
    assert state.inventory["SKU-001"].reserved == 2
    assert state.orders[order_created.aggregate_id].status == OrderStatus.INVENTORY_RESERVED
    assert [event.event_type for event in state.events].count(INVENTORY_RESERVED) == 1


def test_inventory_worker_rejects_order_when_stock_is_missing() -> None:
    state = InMemoryState()
    order_created = _create_order_event(state, quantity=5)

    ReserveInventoryUseCase(fake_uow_factory(state)).execute(order_created)

    assert state.orders[order_created.aggregate_id].status == OrderStatus.INVENTORY_REJECTED
    assert state.events[-1].event_type == INVENTORY_REJECTED
    assert state.events[-1].payload["shortages"][0]["available"] == 0


def test_shipping_worker_creates_single_shipment_for_duplicate_event() -> None:
    state = InMemoryState()
    uow_factory = fake_uow_factory(state)
    AdjustInventoryUseCase(uow_factory).execute(
        InventoryAdjustmentCommand(sku="SKU-001", delta=10)
    )
    order_created = _create_order_event(state)
    ReserveInventoryUseCase(uow_factory).execute(order_created)
    inventory_reserved = state.events[-1]

    use_case = CreateShipmentUseCase(uow_factory)
    use_case.execute(inventory_reserved)
    duplicate = use_case.execute(inventory_reserved)

    assert duplicate.duplicate is True
    assert len(state.shipments_by_order_id) == 1
    assert state.events[-1].event_type == SHIPMENT_CREATED
    assert [event.event_type for event in state.events].count(SHIPMENT_CREATED) == 1
