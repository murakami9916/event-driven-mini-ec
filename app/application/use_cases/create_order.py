from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4

from app.application.dto.models import CreateOrderCommand, OrderResult
from app.application.exceptions import IdempotencyConflict
from app.application.ports.uow import UnitOfWorkFactory
from app.domain.orders.models import Order, OrderItem


def _payload_hash(command: CreateOrderCommand) -> str:
    payload = {"items": [asdict(item) for item in command.items]}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def _result_to_dict(result: OrderResult) -> dict[str, object]:
    return {
        "order_id": result.order_id,
        "status": result.status,
        "items": result.items,
    }


def _result_from_dict(data: dict[str, object]) -> OrderResult:
    return OrderResult(
        order_id=str(data["order_id"]),
        status=str(data["status"]),
        items=list(data["items"]),  # type: ignore[arg-type]
    )


class CreateOrderUseCase:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def execute(self, command: CreateOrderCommand) -> OrderResult:
        if not command.idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")

        current_hash = _payload_hash(command)
        with self._uow_factory() as uow:
            existing = uow.idempotency.get(command.idempotency_key)
            if existing is not None:
                if existing.payload_hash != current_hash:
                    raise IdempotencyConflict("same Idempotency-Key used with different payload")
                return _result_from_dict(existing.response)

            order = Order.create(
                order_id=str(uuid4()),
                items=[OrderItem(sku=item.sku, quantity=item.quantity) for item in command.items],
            )
            uow.orders.add(order)
            uow.events.append(order.to_created_event())

            result = OrderResult(
                order_id=order.id,
                status=str(order.status),
                items=[{"sku": item.sku, "quantity": item.quantity} for item in order.items],
            )
            uow.idempotency.save(command.idempotency_key, current_hash, _result_to_dict(result))
            uow.commit()
            return result

