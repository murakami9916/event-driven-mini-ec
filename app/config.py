from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    redis_url: str
    toxiproxy_url: str
    event_stream: str
    outbox_poll_seconds: float


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/mini_ec",
        ),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        toxiproxy_url=os.getenv("TOXIPROXY_URL", "http://localhost:8474"),
        event_stream=os.getenv("EVENT_STREAM", "domain-events"),
        outbox_poll_seconds=float(os.getenv("OUTBOX_POLL_SECONDS", "1.0")),
    )

