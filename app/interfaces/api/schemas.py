from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OrderLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)
    quantity: int = Field(gt=0)


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[OrderLineRequest] = Field(min_length=1)


class OrderResponse(BaseModel):
    order_id: str
    status: str
    items: list[dict[str, object]]


class OrderDetailsResponse(BaseModel):
    order_id: str
    status: str
    items: list[dict[str, object]]
    shipment: dict[str, object] | None = None


class InventoryAdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1)
    delta: int


class InventoryResponse(BaseModel):
    sku: str
    on_hand: int
    reserved: int
    available: int


class OrderSummaryResponse(BaseModel):
    orders_created: int
    inventory_reserved: int
    inventory_rejected: int
    shipments_created: int


class ReplayResponse(BaseModel):
    event_id: str
    redis_message_id: str


class RedriveResponse(BaseModel):
    dead_letter_id: int
    event_id: str
    redis_message_id: str

