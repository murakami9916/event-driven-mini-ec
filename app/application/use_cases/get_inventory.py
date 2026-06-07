from __future__ import annotations

from app.application.dto.models import InventoryResult
from app.application.exceptions import NotFound
from app.application.ports.uow import UnitOfWorkFactory


class GetInventoryUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self, sku: str) -> InventoryResult:
        with self._uow_factory() as uow:
            item = uow.inventory.get(sku)
            if item is None:
                raise NotFound(f"inventory item not found: {sku}")
            return InventoryResult(
                sku=item.sku,
                on_hand=item.on_hand,
                reserved=item.reserved,
                available=item.available,
            )

