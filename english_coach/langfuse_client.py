from __future__ import annotations

import base64
from datetime import datetime

from english_coach.config import Config


def basic_auth_header(public: str, secret: str) -> str:
    token = base64.b64encode(f"{public}:{secret}".encode()).decode()
    return f"Basic {token}"


class LangfuseClient:
    def __init__(self, config: Config, client=None, page_limit: int = 100):
        self._config = config
        self._page_limit = page_limit
        if client is None:
            import httpx
            client = httpx.Client(timeout=30.0)
        self._client = client
        self._headers = {
            "Authorization": basic_auth_header(config.langfuse_public_key, config.langfuse_secret_key)
        }

    def fetch_traces(self, start_utc: datetime, end_utc: datetime) -> list[dict]:
        url = f"{self._config.langfuse_host}/api/public/traces"
        out: list[dict] = []
        page = 1
        while True:
            params = {
                "fromTimestamp": start_utc.isoformat(),
                "toTimestamp": end_utc.isoformat(),
                "page": page,
                "limit": self._page_limit,
            }
            resp = self._client.get(url, headers=self._headers, params=params)
            resp.raise_for_status()
            batch = resp.json().get("data", [])
            out.extend(batch)
            if len(batch) < self._page_limit:
                break
            page += 1
        return out

    def is_reachable(self) -> bool:
        url = f"{self._config.langfuse_host}/api/public/traces"
        try:
            resp = self._client.get(url, headers=self._headers, params={"page": 1, "limit": 1})
            return resp.status_code < 500
        except Exception:
            return False
