# Mini EC

## 概要｜障害に耐えるイベント駆動 EC の最小実装です。

PostgreSQL を正本にし、Transactional Outbox、Redis Streams、冪等 worker で
「注文作成 → 在庫予約 → 出荷作成 → 集計更新」を最終的に整合させます。

## アーキテクチャ構成

```mermaid
%%{init: {"theme": "base", "themeVariables": {"background": "#ffffff", "darkMode": false, "mainBkg": "#ffffff", "clusterBkg": "#ffffff", "clusterBorder": "#d0d7de", "lineColor": "#64748b", "textColor": "#0f172a", "edgeLabelBackground": "#ffffff"}}}%%
flowchart TB
    Client["クライアント<br/>ブラウザ / API Client"]

    subgraph ApiLayer["API Layer"]
        API["FastAPI<br/>注文API"]
    end

    subgraph SourceOfTruth["Source of Truth"]
        PG[(PostgreSQL<br/>orders / inventory / event_log)]
    end

    subgraph EventDelivery["Reliable Event Delivery"]
        Relay["Outbox Relay<br/>未配送イベントを再送"]
        Redis[(Redis Streams<br/>イベントストリーム)]
    end

    subgraph Consumers["Idempotent Consumers"]
        Inventory["在庫 Worker<br/>在庫予約"]
        Shipping["出荷 Worker<br/>出荷作成"]
        Projection["集計 Worker<br/>read model 更新"]
    end

    subgraph FaultInjection["Fault Injection"]
        Toxi["Toxiproxy<br/>依存先の切断 / 復旧"]
    end

    Client -->|"POST /orders"| API
    API -->|"同一トランザクションで保存"| PG
    PG -->|"未配送イベント"| Relay
    Relay -->|"publish / retry"| Redis
    Redis -->|"OrderCreated"| Inventory
    Redis -->|"InventoryReserved"| Shipping
    Redis -->|"ShipmentCreated"| Projection
    Inventory -->|"冪等 write"| PG
    Shipping -->|"冪等 write"| PG
    Projection -->|"冪等 write"| PG
    Toxi -.->|"PostgreSQL 障害"| PG
    Toxi -.->|"Redis 障害"| Redis

    class Client actor
    class API api
    class PG store
    class Relay,Redis delivery
    class Inventory,Shipping,Projection worker
    class Toxi fault

    classDef actor fill:#fff7ed,stroke:#fb923c,stroke-width:1px,color:#7c2d12;
    classDef api fill:#eff6ff,stroke:#60a5fa,stroke-width:1px,color:#1e3a8a;
    classDef store fill:#ecfdf5,stroke:#34d399,stroke-width:1px,color:#064e3b;
    classDef delivery fill:#f5f3ff,stroke:#a78bfa,stroke-width:1px,color:#4c1d95;
    classDef worker fill:#f8fafc,stroke:#94a3b8,stroke-width:1px,color:#0f172a;
    classDef fault fill:#fef2f2,stroke:#f87171,stroke-width:1px,color:#7f1d1d;
```

API は PostgreSQL に注文とイベントを同一トランザクションで保存し、
Outbox Relay が `event_log` の未配送イベントを Redis Streams に配信します。
各 Worker はイベントを購読し、在庫・出荷・集計を最終的に整合させます。


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

## 技術スタック

- API: FastAPI
- DB: PostgreSQL / SQLAlchemy
- Event Delivery: Redis Streams
- Reliability: Transactional Outbox / Idempotent Consumer
- Fault Injection: Toxiproxy
- Test: pytest
- Runtime: Docker Compose / uv

## 実装の見どころ

- `app/domain`: フレームワーク非依存の業務ルール
- `app/application`: use case と port
- `app/infrastructure/outbox`: outbox relay
- `app/infrastructure/redis`: Redis Streams publisher / consumer
- `tests/unit`: domain / application の振る舞い
- `tests/integration`: PostgreSQL と outbox 永続化
- `tests/fault`: Redis / PostgreSQL 障害と復旧

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
