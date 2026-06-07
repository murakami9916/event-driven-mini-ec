from __future__ import annotations

import json

from redis import Redis

from app.application.dto.models import StoredEvent


class RedisStreamPublisher:
    def __init__(self, redis_url: str, stream_name: str) -> None:
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._stream_name = stream_name

    def publish(self, event: StoredEvent) -> str:
        return str(
            self._client.xadd(
                self._stream_name,
                {
                    "event_log_id": str(event.id),
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "aggregate_type": event.aggregate_type,
                    "aggregate_id": event.aggregate_id,
                    "payload": json.dumps(event.payload, sort_keys=True),
                    "occurred_at": event.occurred_at.isoformat(),
                },
            )
        )

