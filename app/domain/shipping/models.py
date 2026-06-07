from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4


class ShipmentStatus(StrEnum):
    CREATED = "created"


@dataclass
class Shipment:
    id: str
    order_id: str
    status: ShipmentStatus = ShipmentStatus.CREATED

    @classmethod
    def create_for_order(cls, order_id: str, shipment_id: str | None = None) -> "Shipment":
        if not order_id.strip():
            raise ValueError("order_id is required")
        return cls(id=shipment_id or str(uuid4()), order_id=order_id)

