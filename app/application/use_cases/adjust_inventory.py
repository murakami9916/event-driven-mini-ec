from __future__ import annotations

from app.application.dto.models import InventoryAdjustmentCommand, InventoryResult
from app.application.ports.uow import UnitOfWorkFactory
from app.domain.events.models import DomainEvent, INVENTORY_ADJUSTED
from app.domain.inventory.models import InventoryItem


class AdjustInventoryUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self, command: InventoryAdjustmentCommand) -> InventoryResult:
        with self._uow_factory() as uow:
            item = uow.inventory.get_for_update(command.sku)
            if item is None:
                item = InventoryItem(sku=command.sku)
                uow.inventory.add(item)

            item.adjust(command.delta)
            uow.inventory.save(item)
            uow.events.append(
                DomainEvent(
                    event_type=INVENTORY_ADJUSTED,
                    aggregate_type="inventory",
                    aggregate_id=item.sku,
                    payload={
                        "sku": item.sku,
                        "delta": command.delta,
                        "on_hand": item.on_hand,
                        "reserved": item.reserved,
                        "available": item.available,
                    },
                )
            )
            uow.commit()
            return InventoryResult(
                sku=item.sku,
                on_hand=item.on_hand,
                reserved=item.reserved,
                available=item.available,
            )

