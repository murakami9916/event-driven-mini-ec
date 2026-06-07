import pytest

from app.domain.events.models import ORDER_CREATED
from app.domain.orders.models import Order, OrderItem, OrderStatus


def test_order_requires_at_least_one_item() -> None:
    with pytest.raises(ValueError):
        Order.create("order-1", [])


def test_order_created_event_contains_lines() -> None:
    order = Order.create("order-1", [OrderItem("SKU-001", 2)])

    event = order.to_created_event()

    assert event.event_type == ORDER_CREATED
    assert event.payload == {
        "order_id": "order-1",
        "items": [{"sku": "SKU-001", "quantity": 2}],
    }


def test_order_status_transitions_follow_business_flow() -> None:
    order = Order.create("order-1", [OrderItem("SKU-001", 1)])

    order.mark_inventory_reserved()
    order.mark_shipment_created()

    assert order.status == OrderStatus.SHIPMENT_CREATED


def test_shipment_cannot_be_created_before_inventory_reservation() -> None:
    order = Order.create("order-1", [OrderItem("SKU-001", 1)])

    with pytest.raises(ValueError):
        order.mark_shipment_created()

