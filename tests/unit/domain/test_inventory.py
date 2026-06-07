import pytest

from app.domain.inventory.models import InsufficientInventory, InventoryItem


def test_inventory_available_is_on_hand_minus_reserved() -> None:
    item = InventoryItem(sku="SKU-001", on_hand=10, reserved=3)

    assert item.available == 7


def test_inventory_reserve_reduces_available_quantity() -> None:
    item = InventoryItem(sku="SKU-001", on_hand=10)

    item.reserve(4)

    assert item.reserved == 4
    assert item.available == 6


def test_inventory_cannot_reserve_more_than_available() -> None:
    item = InventoryItem(sku="SKU-001", on_hand=2)

    with pytest.raises(InsufficientInventory):
        item.reserve(3)


def test_inventory_adjustment_cannot_drop_below_reserved() -> None:
    item = InventoryItem(sku="SKU-001", on_hand=10, reserved=8)

    with pytest.raises(ValueError):
        item.adjust(-3)

