"""Integration tests for the FastAPI routes (TestClient, no live model)."""
import json
from types import SimpleNamespace

import app.main as main
from fastapi.testclient import TestClient

client = TestClient(main.app)


def _parse_sse(body: str) -> list[dict]:
    frames = [f for f in body.split("\n\n") if f.strip()]
    return [json.loads(f[len("data:"):].strip()) for f in frames]


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_ai_stream_frames_are_sse(monkeypatch):
    async def fake_stream(request_id, system, messages, tools, is_cancelled):
        yield {"requestId": request_id, "type": "delta", "text": "hi"}
        yield {"requestId": request_id, "type": "done", "stopReason": "stop"}

    monkeypatch.setattr(main, "stream_turn", fake_stream)
    r = client.post(
        "/ai/stream",
        json={"requestId": "r1", "system": "s", "messages": [], "tools": []},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    chunks = _parse_sse(r.text)
    assert chunks == [
        {"requestId": "r1", "type": "delta", "text": "hi"},
        {"requestId": "r1", "type": "done", "stopReason": "stop"},
    ]


def test_ai_cancel_marks_request():
    main._cancelled.discard("rc")
    assert client.post("/ai/cancel", json={"requestId": "rc"}).json() == {"ok": True}
    assert "rc" in main._cancelled
    main._cancelled.discard("rc")


def test_search_stubs_return_empty():
    assert client.get("/ai/web-search", params={"query": "x"}).json()["results"] == []
    assert client.get("/ai/image-search", params={"query": "x"}).json()["images"] == []


def test_fetch_image_returns_base64(monkeypatch):
    class FakeResp:
        headers = {"content-type": "image/png"}
        content = b"\x89PNG"

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url):
            return FakeResp()

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    r = client.get("/ai/fetch-image", params={"url": "http://x/i.png"})
    assert r.status_code == 200
    body = r.json()
    assert body["mime"] == "image/png"
    import base64

    assert base64.b64decode(body["base64"]) == b"\x89PNG"


def test_fetch_image_error_returns_502(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url):
            raise RuntimeError("boom")

    monkeypatch.setattr(main.httpx, "AsyncClient", FakeClient)
    r = client.get("/ai/fetch-image", params={"url": "http://x/i.png"})
    assert r.status_code == 502
