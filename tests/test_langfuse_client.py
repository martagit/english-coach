import base64
from datetime import datetime, timezone
from english_coach.langfuse_client import basic_auth_header, LangfuseClient
from english_coach.config import Config
from pathlib import Path


def _cfg():
    return Config("http://localhost:3000", "pk", "sk", "ak", Path("."), Path("."))


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def get(self, url, headers=None, params=None):
        self.calls.append(params)
        page = params["page"]
        return FakeResponse({"data": self._pages.get(page, [])})


def test_basic_auth_header():
    h = basic_auth_header("pk", "sk")
    assert h == "Basic " + base64.b64encode(b"pk:sk").decode()


def test_fetch_traces_paginates():
    pages = {1: [{"id": "a"}, {"id": "b"}], 2: [{"id": "c"}], 3: []}
    fake = FakeClient(pages)
    client = LangfuseClient(_cfg(), client=fake, page_limit=2)
    traces = client.fetch_traces(datetime(2026, 7, 5, tzinfo=timezone.utc),
                                 datetime(2026, 7, 6, tzinfo=timezone.utc))
    assert [t["id"] for t in traces] == ["a", "b", "c"]
    assert fake.calls[0]["fromTimestamp"].startswith("2026-07-05")


def test_is_reachable_true_on_200():
    client = LangfuseClient(_cfg(), client=FakeClient({1: []}))
    assert client.is_reachable() is True


def test_default_page_limit_is_100():
    client = LangfuseClient(_cfg(), client=FakeClient({1: []}))
    assert client._page_limit == 100
