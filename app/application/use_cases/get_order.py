from __future__ import annotations

from app.application.dto.models import OrderDetails
from app.application.exceptions import NotFound
from app.application.ports.uow import UnitOfWorkFactory


class GetOrderUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self, order_id: str) -> OrderDetails:
        with self._uow_factory() as uow:
            order = uow.orders.get(order_id)
            if order is None:
                raise NotFound(f"order not found: {order_id}")
            shipment = uow.shipments.get_by_order_id(order_id)
            return OrderDetails(
                order_id=order.id,
                status=order.status,
                items=[{"sku": item.sku, "quantity": item.quantity} for item in order.items],
                shipment=None
                if shipment is None
                else {
                    "shipment_id": shipment.id,
                    "order_id": shipment.order_id,
                    "status": str(shipment.status),
                },
            )

