import pytest

from app.application.dto.models import CreateOrderCommand, OrderLineInput
from app.application.exceptions import IdempotencyConflict
from app.application.use_cases.create_order import CreateOrderUseCase
from app.domain.events.models import ORDER_CREATED
from tests.unit.application.fakes import InMemoryState, fake_uow_factory


def test_create_order_persists_order_event_and_idempotency_response() -> None:
    state = InMemoryState()
    use_case = CreateOrderUseCase(fake_uow_factory(state))

    result = use_case.execute(
        CreateOrderCommand(
            idempotency_key="key-1",
            items=[OrderLineInput(sku="SKU-001", quantity=2)],
        )
    )

    assert result.order_id in state.orders
    assert state.events[0].event_type == ORDER_CREATED
    assert state.idempotency["key-1"].response["order_id"] == result.order_id


def test_create_order_reuses_same_response_for_same_idempotency_key_and_payload() -> None:
    state = InMemoryState()
    use_case = CreateOrderUseCase(fake_uow_factory(state))
    command = CreateOrderCommand(
        idempotency_key="key-1",
        items=[OrderLineInput(sku="SKU-001", quantity=2)],
    )

    first = use_case.execute(command)
    second = use_case.execute(command)

    assert first == second
    assert len(state.orders) == 1
    assert len(state.events) == 1


def test_create_order_rejects_same_idempotency_key_with_different_payload() -> None:
    state = InMemoryState()
    use_case = CreateOrderUseCase(fake_uow_factory(state))
    use_case.execute(
        CreateOrderCommand(
            idempotency_key="key-1",
            items=[OrderLineInput(sku="SKU-001", quantity=2)],
        )
    )

    with pytest.raises(IdempotencyConflict):
        use_case.execute(
            CreateOrderCommand(
                idempotency_key="key-1",
                items=[OrderLineInput(sku="SKU-001", quantity=3)],
            )
        )

