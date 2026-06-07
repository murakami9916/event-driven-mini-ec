from __future__ import annotations

from dataclasses import dataclass


class InsufficientInventory(Exception):
    def __init__(self, sku: str, requested: int, available: int) -> None:
        super().__init__(
            f"insufficient inventory for sku={sku}: requested={requested}, available={available}"
        )
        self.sku = sku
        self.requested = requested
        self.available = available


@dataclass
class InventoryItem:
    sku: str
    on_hand: int = 0
    reserved: int = 0

    def __post_init__(self) -> None:
        if not self.sku.strip():
            raise ValueError("sku is required")
        if self.on_hand < 0:
            raise ValueError("on_hand cannot be negative")
        if self.reserved < 0:
            raise ValueError("reserved cannot be negative")
        if self.reserved > self.on_hand:
            raise ValueError("reserved cannot exceed on_hand")

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved

    def adjust(self, delta: int) -> None:
        next_on_hand = self.on_hand + delta
        if next_on_hand < 0:
            raise ValueError("on_hand cannot be negative")
        if next_on_hand < self.reserved:
            raise ValueError("on_hand cannot be adjusted below reserved quantity")
        self.on_hand = next_on_hand

    def reserve(self, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if quantity > self.available:
            raise InsufficientInventory(self.sku, quantity, self.available)
        self.reserved += quantity

