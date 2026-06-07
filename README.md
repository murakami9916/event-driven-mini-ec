# Mini EC

## 概要｜障害に耐えるイベント駆動 EC の最小実装です。

PostgreSQL を正本にし、Transactional Outbox、Redis Streams、冪等 worker で
「注文作成 → 在庫予約 → 出荷作成 → 集計更新」を最終的に整合させます。

## 最短で動かす

### 前提

- Docker
- Docker Compose
- Python 3.12 と uv: ローカルで pytest / ruff を実行する場合に必要

この README の Docker コマンドは `docker compose` で書いています。
環境によって `docker compose` が使えない場合は、同じコマンドを `docker-compose` に置き換えてください。

使う主なポート:

| 用途 | URL / Port |
| --- | --- |
| Web UI / API | `http://localhost:18000` |
| PostgreSQL direct | `localhost:5432` |
| PostgreSQL via Toxiproxy | `localhost:15432` |
| Redis direct | `localhost:6379` |
| Redis via Toxiproxy | `localhost:16379` |
| Toxiproxy API | `http://localhost:18474` |

### 起動

```bash
docker compose up --build -d
```

サービス状態を確認します。

```bash
docker compose ps
```

API が起動したら、以下が `200 OK` になります。

```bash
curl -i http://localhost:18000/read-models/order-summary
```

ブラウザで動かす場合は `http://localhost:18000` を開きます。

### API で注文フローを確認する

以下の期待値は初期状態の DB を前提にしています。
同じ手順をもう一度試す場合は `docker compose down -v` で初期化するか、
`sku` と `Idempotency-Key` を別の値に変えてください。

1. 在庫を追加します。

```bash
curl -sS -X POST http://localhost:18000/inventory/adjustments \
  -H 'Content-Type: application/json' \
  -d '{"sku":"SKU-001","delta":5}'
```

期待するレスポンス:

```json
{"sku":"SKU-001","on_hand":5,"reserved":0,"available":5}
```

2. 注文を作成します。`Idempotency-Key` は必須です。

```bash
curl -sS -X POST http://localhost:18000/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-order-001' \
  -d '{"items":[{"sku":"SKU-001","quantity":2}]}'
```

レスポンスの `order_id` を控えます。

```json
{"order_id":"<order-id>","status":"created","items":[{"sku":"SKU-001","quantity":2}]}
```

3. worker が処理するまで数秒待ち、注文状態を確認します。

```bash
ORDER_ID=<order-id>
curl -sS http://localhost:18000/orders/$ORDER_ID
```

最終的に `status` が `shipment_created` になり、`shipment` が入ります。

4. 在庫と集計 read model を確認します。

```bash
curl -sS http://localhost:18000/inventory/SKU-001
curl -sS http://localhost:18000/read-models/order-summary
```

在庫は `reserved: 2`、`available: 3` になります。
集計は `orders_created`、`inventory_reserved`、`shipments_created` が増えます。

### 停止

コンテナだけ止める場合:

```bash
docker compose down
```

PostgreSQL のデータも消して最初からやり直す場合:

```bash
docker compose down -v
```

## アーキテクチャ構成

```mermaid
%%{init: {"theme": "base", "themeCSS": "svg { background-color: #ffffff !important; }", "flowchart": {"diagramPadding": 0}, "themeVariables": {"background": "#ffffff", "darkMode": false, "mainBkg": "#ffffff", "clusterBkg": "#ffffff", "clusterBorder": "#d0d7de", "lineColor": "#64748b", "textColor": "#0f172a", "edgeLabelBackground": "#ffffff"}}}%%
flowchart TB
    subgraph Canvas[" "]
        direction TB
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
    end

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
    style Canvas fill:#ffffff,stroke:#ffffff,color:#ffffff;
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

## 設計判断

### PostgreSQL を Source of Truth にした理由
注文作成時に、注文データと発行予定イベントを同一トランザクションで保存したかったため。
Redis への publish を API 処理内で直接行うと、DB commit 成功後に publish 失敗した場合にイベント欠損が起きる。
そのため PostgreSQL の event_log を outbox として扱い、relay が未配送イベントを再送する設計にした。

### 冪等 Consumer にした理由
Outbox relay の再送により、イベントは at-least-once delivery になる。
そのため consumer 側では event_id や業務キーを使って処理済み判定を行い、同じイベントが複数回来ても状態が壊れないようにした。

## 障害テストで確認していること

`tests/fault/test_fault_scenarios.py` で、Toxiproxy を使って実際に依存先を切断します。

| 観点 | テストで実施する障害 | PASS 判定 |
| --- | --- | --- |
| Redis 断でも注文を失わない | Redis を切断したまま `POST /orders` を実行 | API は注文を作成し、PostgreSQL の `orders` と `event_log` に保存される |
| Redis 復旧後にイベントを再送する | Redis を復旧し、outbox relay の再送を待つ | `OrderCreated` / `InventoryReserved` / `ShipmentCreated` がすべて publish 済みになる |
| worker が最終整合させる | Redis 復旧後、各 worker の処理完了を待つ | 注文は `shipment_created`、在庫は予約済み、出荷と集計 read model も更新される |
| PostgreSQL 断では API を失敗させる | PostgreSQL を切断して `POST /orders` を実行 | API は `503 Service Unavailable` を返す |
| PostgreSQL 復旧後に通常処理へ戻る | PostgreSQL を復旧して通常 API を実行 | `GET /read-models/order-summary` と `POST /inventory/adjustments` が成功する |

実行手順:

```bash
docker compose up --build -d
uv sync --locked --dev
```

API の起動を待ちます。

```bash
curl -i http://localhost:18000/read-models/order-summary
```

障害テストを実行します。

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

依存関係を入れます。

```bash
uv sync --locked --dev
```

静的チェック:

```bash
uv run ruff check .
```

DB なしで実行できるテスト:

```bash
uv run pytest
```

カバレッジを出す場合:

```bash
uv run pytest --cov=app --cov-report=term-missing
```

HTML レポートも出す場合:

```bash
uv run pytest --cov=app --cov-report=term-missing --cov-report=html
```

HTML は `htmlcov/index.html` に出力されます。
カバレッジは「テスト実行時に app 配下のどの行・分岐が通ったか」を見る指標です。
高いほど安心材料にはなりますが、テストの品質そのものを保証する数字ではありません。

`TEST_DATABASE_URL` を指定しない場合、PostgreSQL integration test と fault test は skip されます。

PostgreSQL integration test も含める場合:

```bash
docker compose up -d postgres
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/mini_ec \
  uv run pytest
```

Toxiproxy を使う障害テストは、上記の「障害テストで確認していること」の手順で実行します。

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

### リクエスト例

在庫追加:

```bash
curl -sS -X POST http://localhost:18000/inventory/adjustments \
  -H 'Content-Type: application/json' \
  -d '{"sku":"SKU-001","delta":5}'
```

注文作成:

```bash
curl -sS -X POST http://localhost:18000/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-order-001' \
  -d '{"items":[{"sku":"SKU-001","quantity":2}]}'
```

注文取得:

```bash
curl -sS http://localhost:18000/orders/<order-id>
```

在庫取得:

```bash
curl -sS http://localhost:18000/inventory/SKU-001
```

集計取得:

```bash
curl -sS http://localhost:18000/read-models/order-summary
```

Toxiproxy 経由で依存先を切断 / 復旧:

```bash
curl -sS -X POST http://localhost:18000/admin/faults/redis/cut
curl -sS -X POST http://localhost:18000/admin/faults/redis/restore
curl -sS -X POST http://localhost:18000/admin/faults/postgres/cut
curl -sS -X POST http://localhost:18000/admin/faults/postgres/restore
```

## トラブルシュート

### `docker compose` が使えない

standalone 版の Docker Compose だけが入っている環境では、`docker compose` の代わりに
`docker-compose` を使います。

```bash
docker-compose up --build -d
docker-compose ps
```

### ポートがすでに使われている

このリポジトリは `18000`、`5432`、`6379`、`15432`、`16379`、`18474` を使います。
他の PostgreSQL / Redis / Docker Compose stack が起動している場合は停止するか、
`docker-compose.yml` の左側のポート番号を変更してください。

### API がまだ起動していない

`docker compose up -d` 直後は DB 初期化中のことがあります。
以下が `200 OK` になるまで数秒待ちます。

```bash
curl -i http://localhost:18000/read-models/order-summary
```

ログを見る場合:

```bash
docker compose logs api
```

### 同じ注文を再実行したら同じ `order_id` が返る

仕様です。`POST /orders` は `Idempotency-Key` で冪等化しています。
同じ key と同じ payload は同じ結果を返します。
別の注文として作りたい場合は `Idempotency-Key` を変えてください。

### データを初期化したい

PostgreSQL volume を削除します。

```bash
docker compose down -v
docker compose up --build -d
```
