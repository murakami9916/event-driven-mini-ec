from __future__ import annotations

import http.client
import json
from urllib.parse import urlparse


class ToxiproxyClient:
    def __init__(self, base_url: str) -> None:
        parsed = urlparse(base_url)
        self._host = parsed.hostname or "localhost"
        self._port = parsed.port or 8474

    def set_enabled(self, proxy_name: str, enabled: bool) -> dict[str, object]:
        body = json.dumps({"enabled": enabled}).encode("utf-8")
        conn = http.client.HTTPConnection(self._host, self._port, timeout=5)
        conn.request(
            "PATCH",
            f"/proxies/{proxy_name}",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        payload = response.read().decode("utf-8")
        if response.status >= 400:
            raise RuntimeError(f"toxiproxy error {response.status}: {payload}")
        return json.loads(payload) if payload else {"enabled": enabled, "name": proxy_name}

