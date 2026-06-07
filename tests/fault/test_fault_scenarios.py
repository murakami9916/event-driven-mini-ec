from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, TypeVar
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.infrastructure.toxiproxy.client import ToxiproxyClient


pytestmark = pytest.mark.skipif(
    os.getenv("FAULT_TESTS") != "1",
    reason="FAULT_TESTS=1 is required for live Docker/Toxiproxy fault tests",
)

T = TypeVar("T")


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for live Docker/Toxiproxy fault tests")
    return value


@pytest.fixture
def api_client() -> httpx.Client:
    base_url = os.getenv("API_URL", "http://localhost:18000")
    timeout = httpx.Timeout(10.0, connect=3.0)
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        yield client


@pytest.fixture
def db_engine() -> Engine:
    engine = create_engine(_require_env("TEST_DATABASE_URL"), pool_pre_ping=True, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def toxiproxy() -> ToxiproxyClient:
    _require_env("REDIS_URL")
    client = ToxiproxyClient(_require_env("TOXIPROXY_URL"))
    _restore_dependencies(client)
    try:
        yield client
    finally:
        _restore_dependencies(client)


def test_redis_outage_keeps_order_in_postgres_and_replays_outbox(
    api_client: httpx.Client,
    db_engine: Engine,
    toxiproxy: ToxiproxyClient,
) -> None:
    sku = f"FAULT-REDIS-{uuid4().hex[:12]}"
    idempotency_key = f"fault-redis-{uuid4()}"

    _post_json(api_client, "/inventory/adjustments", {"sku": sku, "delta": 5})
    baseline_summary = _get_json(api_client, "/read-models/order-summary")

    toxiproxy.set_enabled("redis", False)

    created = _post_json(
        api_client,
        "/orders",
        {"items": [{"sku": sku, "quantity": 2}]},
        headers={"Idempotency-Key": idempotency_key},
    )
    order_id = created["order_id"]

    stored_order = _stored_order(db_engine, order_id)
    assert stored_order["status"] == "created"
    assert stored_order["order_created_published_at"] is None

    toxiproxy.set_enabled("redis", True)

    _wait_until(
        lambda: _assert_order_flow_converged(
            api_client,
            db_engine,
            order_id=order_id,
            sku=sku,
            baseline_summary=baseline_summary,
        ),
        timeout_seconds=45.0,
    )


def test_postgres_outage_returns_503_and_recovers(
    api_client: httpx.Client,
    toxiproxy: ToxiproxyClient,
) -> None:
    toxiproxy.set_enabled("postgres", False)
    try:
        response = api_client.post(
            "/orders",
            json={"items": [{"sku": f"FAULT-PG-{uuid4().hex[:12]}", "quantity": 1}]},
            headers={"Idempotency-Key": f"fault-postgres-down-{uuid4()}"},
        )
        assert response.status_code == 503
        assert "database unavailable" in response.json()["detail"]
    finally:
        toxiproxy.set_enabled("postgres", True)

    _wait_until(lambda: _assert_api_available(api_client), timeout_seconds=30.0)

    response = api_client.post(
        "/inventory/adjustments",
        json={"sku": f"FAULT-PG-RECOVERED-{uuid4().hex[:12]}", "delta": 1},
    )
    assert response.status_code == 200


def _restore_dependencies(toxiproxy: ToxiproxyClient) -> None:
    for proxy_name in ("postgres", "redis"):
        toxiproxy.set_enabled(proxy_name, True)


def _wait_until(
    assertion: Callable[[], T],
    *,
    timeout_seconds: float,
    interval_seconds: float = 0.5,
) -> T:
    deadline = time.monotonic() + timeout_seconds
    last_error: BaseException | None = None
    while time.monotonic() < deadline:
        try:
            return assertion()
        except (AssertionError, httpx.HTTPError, SQLAlchemyError) as exc:
            last_error = exc
            time.sleep(interval_seconds)
    raise AssertionError(f"condition was not met within {timeout_seconds:.1f}s") from last_error


def _get_json(client: httpx.Client, path: str) -> dict[str, Any]:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def _post_json(
    client: httpx.Client,
    path: str,
    json_body: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = client.post(path, json=json_body, headers=headers)
    response.raise_for_status()
    return response.json()


def _stored_order(engine: Engine, order_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    orders.status AS status,
                    event_log.published_at AS order_created_published_at
                FROM orders
                JOIN event_log ON event_log.aggregate_id = orders.id
                WHERE orders.id = :order_id
                  AND event_log.event_type = 'OrderCreated'
                """
            ),
            {"order_id": order_id},
        ).mappings().one()
    return dict(row)


def _assert_order_flow_converged(
    client: httpx.Client,
    engine: Engine,
    *,
    order_id: str,
    sku: str,
    baseline_summary: dict[str, Any],
) -> None:
    order = _get_json(client, f"/orders/{order_id}")
    assert order["status"] == "shipment_created"
    assert order["shipment"] is not None

    inventory = _get_json(client, f"/inventory/{sku}")
    assert inventory == {"sku": sku, "on_hand": 5, "reserved": 2, "available": 3}

    summary = _get_json(client, "/read-models/order-summary")
    assert summary["orders_created"] >= baseline_summary["orders_created"] + 1
    assert summary["inventory_reserved"] >= baseline_summary["inventory_reserved"] + 1
    assert summary["shipments_created"] >= baseline_summary["shipments_created"] + 1

    events = _order_flow_events(engine, order_id)
    event_types = {event["event_type"] for event in events}
    assert {"OrderCreated", "InventoryReserved", "ShipmentCreated"} <= event_types
    assert all(event["published_at"] is not None for event in events)
    assert _projection_processed_all(engine, [event["event_id"] for event in events])


def _order_flow_events(engine: Engine, order_id: str) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT event_id, event_type, published_at
                FROM event_log
                WHERE (
                    aggregate_id = :order_id
                    AND event_type = 'OrderCreated'
                )
                OR (
                    payload ->> 'order_id' = :order_id
                    AND event_type IN ('InventoryReserved', 'ShipmentCreated')
                )
                ORDER BY id
                """
            ),
            {"order_id": order_id},
        ).mappings().all()
    return [dict(row) for row in rows]


def _projection_processed_all(engine: Engine, event_ids: list[str]) -> bool:
    with engine.connect() as connection:
        processed_count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM processed_events
                WHERE consumer_name = 'projection-worker'
                  AND event_id IN :event_ids
                """
            ).bindparams(bindparam("event_ids", expanding=True)),
            {"event_ids": event_ids},
        ).scalar_one()
    return processed_count == len(event_ids)


def _assert_api_available(client: httpx.Client) -> None:
    response = client.get("/read-models/order-summary")
    assert response.status_code == 200
