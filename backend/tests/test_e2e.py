"""End-to-end: real uvicorn subprocess + real model over the SSE wire.

Hits the network and needs a working model key in the repo-root .env, so it is
gated behind AIOFFICE_E2E=1 (default runs skip it). This is the exact contract
the browser web-adapter consumes.

    AIOFFICE_E2E=1 uv run pytest tests/test_e2e.py -s
"""
import json
import os
import socket
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AIOFFICE_E2E") != "1", reason="set AIOFFICE_E2E=1 to run live model E2E"
)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{url}/healthz", timeout=1).json().get("ok"):
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("backend did not come up")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _stream(url: str, payload: dict) -> list[dict]:
    chunks: list[dict] = []
    with httpx.stream("POST", f"{url}/ai/stream", json=payload, timeout=60) as r:
        assert r.status_code == 200
        buf = ""
        for text in r.iter_text():
            buf += text
            while "\n\n" in buf:
                frame, buf = buf.split("\n\n", 1)
                frame = frame.strip()
                if frame.startswith("data:"):
                    chunks.append(json.loads(frame[len("data:"):].strip()))
    return chunks


def test_live_text_stream(base_url):
    chunks = _stream(
        base_url,
        {
            "requestId": "e2e-text",
            "system": "You are terse.",
            "messages": [{"role": "user", "text": "Reply with the single word: pong"}],
            "tools": [],
        },
    )
    assert any(c["type"] == "delta" for c in chunks)
    assert chunks[-1]["type"] == "done"
    text = "".join(c.get("text", "") for c in chunks if c["type"] == "delta")
    assert "pong" in text.lower()


def test_live_tool_call(base_url):
    chunks = _stream(
        base_url,
        {
            "requestId": "e2e-tool",
            "system": "Call the tool when the user asks to edit the document.",
            "messages": [{"role": "user", "text": 'Insert a heading "Report" into the document.'}],
            "tools": [
                {
                    "name": "insert_content",
                    "description": "Insert markdown content into the document",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                }
            ],
        },
    )
    calls = [c["toolCall"] for c in chunks if c["type"] == "tool-call"]
    assert calls, "model did not emit a tool call"
    assert calls[0]["name"] == "insert_content"
    assert "text" in calls[0]["input"]
    assert chunks[-1]["type"] == "done"
