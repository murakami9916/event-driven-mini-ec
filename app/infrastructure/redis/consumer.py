from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable

from redis import Redis
from redis.exceptions import RedisError, ResponseError, TimeoutError as RedisTimeoutError

from app.application.dto.models import StoredEvent


LOGGER = logging.getLogger(__name__)
EventHandler = Callable[[StoredEvent], object]
DeadLetterHandler = Callable[[StoredEvent, str, int], None]


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)


def event_from_stream_fields(fields: dict[str, str]) -> StoredEvent:
    return StoredEvent(
        id=int(fields.get("event_log_id", "0")),
        event_id=fields["event_id"],
        event_type=fields["event_type"],
        aggregate_type=fields.get("aggregate_type", ""),
        aggregate_id=fields.get("aggregate_id", ""),
        payload=json.loads(fields["payload"]),
        occurred_at=_parse_datetime(fields.get("occurred_at", "")),
    )


class RedisStreamConsumer:
    def __init__(
        self,
        redis_url: str,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        handler: EventHandler,
        dead_letter_handler: DeadLetterHandler,
        max_failures: int = 5,
    ) -> None:
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._stream_name = stream_name
        self._group_name = group_name
        self._consumer_name = consumer_name
        self._handler = handler
        self._dead_letter_handler = dead_letter_handler
        self._max_failures = max_failures
        self._failures: dict[str, int] = {}

    def ensure_group(self) -> None:
        try:
            self._client.xgroup_create(
                self._stream_name,
                self._group_name,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def run_forever(self, block_ms: int = 5000, count: int = 10) -> None:
        self.ensure_group()
        while True:
            try:
                self.run_once(block_ms=block_ms, count=count)
            except RedisError:
                LOGGER.exception("redis stream read failed")
                time.sleep(1)

    def run_once(self, block_ms: int = 1000, count: int = 10) -> int:
        self.ensure_group()
        messages = self._client.xreadgroup(
            self._group_name,
            self._consumer_name,
            {self._stream_name: "0"},
            count=count,
        )
        if not any(stream_messages for _, stream_messages in messages):
            try:
                messages = self._client.xreadgroup(
                    self._group_name,
                    self._consumer_name,
                    {self._stream_name: ">"},
                    count=count,
                    block=block_ms,
                )
            except RedisTimeoutError:
                return 0
        handled = 0
        for _, stream_messages in messages:
            for message_id, fields in stream_messages:
                event = event_from_stream_fields(fields)
                try:
                    self._handler(event)
                    self._client.xack(self._stream_name, self._group_name, message_id)
                    self._failures.pop(event.event_id, None)
                    handled += 1
                except Exception as exc:
                    failure_count = self._failures.get(event.event_id, 0) + 1
                    self._failures[event.event_id] = failure_count
                    LOGGER.exception(
                        "failed to handle event_id=%s failure=%s",
                        event.event_id,
                        failure_count,
                    )
                    if failure_count >= self._max_failures:
                        self._dead_letter_handler(event, str(exc), failure_count)
                        self._client.xack(self._stream_name, self._group_name, message_id)
                        self._failures.pop(event.event_id, None)
                        handled += 1
        return handled
