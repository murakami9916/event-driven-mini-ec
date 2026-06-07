# Mini EC

障害に耐えるイベント駆動 EC の最小実装です。

PostgreSQL を正本にし、Transactional Outbox、Redis Streams、冪等 worker で
「注文作成 → 在庫予約 → 出荷作成 → 集計更新」を最終的に整合させます。

## このリポジトリで見せたいこと

- Redis が落ちても注文は PostgreSQL に保存される
- Redis 復旧後、outbox relay が未配送イベントを再送する
- worker はイベントを冪等に処理し、在庫・出荷・集計を整合させる
- PostgreSQL 障害時、API は `503 Service Unavailable` を返す
- DDD / Clean Architecture で、domain 層は FastAPI・SQLAlchemy・Redis に依存しない

## 障害テストで確認していること

`tests/fault/test_fault_scenarios.py` で、Toxiproxy を使って実際に依存先を切断します。

| 観点 | テストで実施する障害 | PASS 判定 | 結果 |
| --- | --- | --- | --- |
| Redis 断でも注文を失わない | Redis を切断したまま `POST /orders` を実行 | API は注文を作成し、PostgreSQL の `orders` と `event_log` に保存される | PASS |
| Redis 復旧後にイベントを再送する | Redis を復旧し、outbox relay の再送を待つ | `OrderCreated` / `InventoryReserved` / `ShipmentCreated` がすべて publish 済みになる | PASS |
| worker が最終整合させる | Redis 復旧後、各 worker の処理完了を待つ | 注文は `shipment_created`、在庫は予約済み、出荷と集計 read model も更新される | PASS |
| PostgreSQL 断では API を失敗させる | PostgreSQL を切断して `POST /orders` を実行 | API は `503 Service Unavailable` を返す | PASS |
| PostgreSQL 復旧後に通常処理へ戻る | PostgreSQL を復旧して通常 API を実行 | `GET /read-models/order-summary` と `POST /inventory/adjustments` が成功する | PASS |

実行済み:

```bash
FAULT_TESTS=1 \
API_URL=http://localhost:18000 \
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:15432/mini_ec \
REDIS_URL=redis://localhost:16379/0 \
TOXIPROXY_URL=http://localhost:18474 \
uv run pytest tests/fault/test_fault_scenarios.py
```

## 処理フロー

```text
POST /orders
  -> PostgreSQL: orders + event_log
  -> outbox-relay
  -> Redis Streams
  -> inventory-worker
  -> shipping-worker
  -> projection-worker
  -> read model
```

## 技術スタック

- API: FastAPI
- DB: PostgreSQL / SQLAlchemy
- Event Delivery: Redis Streams
- Reliability: Transactional Outbox / Idempotent Consumer
- Fault Injection: Toxiproxy
- Test: pytest
- Runtime: Docker Compose / uv

## 起動

```bash
docker compose up --build
```

UI:

<http://localhost:18000/>

## テスト

通常テスト:

```bash
uv run pytest
```

障害テストは Docker Compose で PostgreSQL、Redis、Toxiproxy、API、relay、worker が
起動している前提です。実行コマンドは上記の「障害テストで確認していること」に記載しています。

## API

- `POST /orders`
- `GET /orders/{order_id}`
- `POST /inventory/adjustments`
- `GET /inventory/{sku}`
- `GET /read-models/order-summary`
- `POST /admin/projections/order-summary/rebuild`
- `POST /admin/events/{event_id}/replay`
- `POST /admin/dlq/{dead_letter_id}/redrive`
- `POST /admin/faults/{target}/{action}`

`POST /orders` は `Idempotency-Key` ヘッダー必須です。
同じ key と同じ payload は同じ結果を返し、同じ key で payload が違う場合は
`409 Conflict` を返します。

## 実装の見どころ

- `app/domain`: フレームワーク非依存の業務ルール
- `app/application`: use case と port
- `app/infrastructure/outbox`: outbox relay
- `app/infrastructure/redis`: Redis Streams publisher / consumer
- `tests/unit`: domain / application の振る舞い
- `tests/integration`: PostgreSQL と outbox 永続化
- `tests/fault`: Redis / PostgreSQL 障害と復旧
