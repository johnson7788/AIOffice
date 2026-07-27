"""
在线办公底座 E2E 测试 — P0 文件 API / P2 ONLYOFFICE 网关 / P3 save_to_workspace。

不依赖 Docker、不依赖已启动的服务、不依赖 LLM key：直接把 FastAPI app
挂到 httpx ASGITransport 上做进程内端到端请求。ONLYOFFICE 的 DocumentServer
容器无法在 CI 里跑，但网关的签发/验签/回写逻辑（真正会出错的部分）全在后端，
这里用一个临时本地 http.server 冒充 DocServer 来打通「保存回写」整条链路。

运行：
    cd test
    pytest test_office_files.py -v
"""
from __future__ import annotations

import contextlib
import http.server
import os
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

# 必须在 import server 之前设好——server 在模块加载时读取 OFFICE_JWT_SECRET
os.environ.setdefault("OFFICE_JWT_SECRET", "test-office-secret-at-least-32-bytes-long")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-used")

BACKEND = Path(__file__).resolve().parent.parent / "backend"
import sys

sys.path.insert(0, str(BACKEND))

import server  # noqa: E402  （env 已就绪后再导入）

ASGI = httpx.ASGITransport(app=server.app)
USER = f"test_office_{int(time.time())}"


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=ASGI, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def clean_user():
    """每个测试后清掉该用户的 uploads 目录，避免互相污染。"""
    yield
    import shutil

    d = server.UPLOADS_DIR / USER
    if d.exists():
        shutil.rmtree(d)


# ---------------------------------------------------------------------------
# P0 文件 API
# ---------------------------------------------------------------------------

async def test_files_roundtrip(client):
    # 写入
    r = await client.put(
        "/files/raw",
        json={"user_id": USER, "path": "notes/a.md", "content": "# hi"},
    )
    assert r.status_code == 200 and r.json()["success"]

    # 文件树能看到
    tree = (await client.get("/files/tree", params={"user_id": USER})).json()["tree"]
    notes = next(n for n in tree if n["name"] == "notes")
    assert notes["type"] == "directory"
    assert any(c["name"] == "a.md" for c in notes["children"])

    # 读回内容
    raw = await client.get("/files/raw", params={"user_id": USER, "path": "notes/a.md"})
    assert raw.status_code == 200 and raw.text == "# hi"

    # 删除
    d = await client.delete("/files", params={"user_id": USER, "path": "notes"})
    assert d.status_code == 200
    tree2 = (await client.get("/files/tree", params={"user_id": USER})).json()["tree"]
    assert tree2 == []


@pytest.mark.parametrize("path", ["../evil.txt", "../../etc/passwd", "sub/../../x"])
async def test_files_traversal_rejected(client, path):
    # 读、删都必须挡住越权路径
    r = await client.get("/files/raw", params={"user_id": USER, "path": path})
    assert r.status_code == 400
    d = await client.delete("/files", params={"user_id": USER, "path": path})
    assert d.status_code == 400
    w = await client.put(
        "/files/raw", json={"user_id": USER, "path": path, "content": "x"}
    )
    assert w.status_code == 400


async def test_files_raw_missing(client):
    r = await client.get("/files/raw", params={"user_id": USER, "path": "nope.md"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# P2 ONLYOFFICE 网关
# ---------------------------------------------------------------------------

async def _make_file(client, path: str, content: str = "dummy") -> None:
    r = await client.put(
        "/files/raw", json={"user_id": USER, "path": path, "content": content}
    )
    assert r.status_code == 200


async def test_office_config_signed(client):
    await _make_file(client, "deck.pptx", "PPTX-BYTES")
    r = await client.get("/office/config", params={"user_id": USER, "path": "deck.pptx"})
    assert r.status_code == 200
    body = r.json()
    cfg = body["config"]
    assert cfg["documentType"] == "slide"
    assert cfg["document"]["fileType"] == "pptx"
    assert len(cfg["document"]["key"]) == 32  # md5 hex
    assert "token" in cfg
    # config 整体签名可被后端验回，且 download url 里的 file_token 绑定 path+user
    server._office_verify(cfg["token"])
    token = cfg["document"]["url"].split("token=")[1]
    claims = server._office_verify(token)
    assert claims["path"] == "deck.pptx" and claims["user_id"] == USER


async def test_office_config_unsupported_type(client):
    await _make_file(client, "weird.xyz")
    r = await client.get("/office/config", params={"user_id": USER, "path": "weird.xyz"})
    assert r.status_code == 400


async def test_office_config_missing_file(client):
    r = await client.get("/office/config", params={"user_id": USER, "path": "ghost.docx"})
    assert r.status_code == 404


async def test_office_download_auth(client):
    await _make_file(client, "doc.docx", "REAL-CONTENT")
    good = server._office_sign(
        {"path": "doc.docx", "user_id": USER, "exp": int(time.time()) + 60}
    )
    ok = await client.get("/office/download", params={"token": good})
    assert ok.status_code == 200 and ok.text == "REAL-CONTENT"

    bad = await client.get("/office/download", params={"token": "garbage.token.here"})
    assert bad.status_code == 403


@contextlib.contextmanager
def _serve_bytes(payload: bytes):
    """临时起本地 http server 冒充 DocServer 提供「编辑后」文件。"""

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}/edited"
    finally:
        srv.shutdown()


async def test_office_callback_writeback(client):
    await _make_file(client, "report.docx", "OLD")
    token = server._office_sign(
        {"path": "report.docx", "user_id": USER, "exp": int(time.time()) + 60}
    )
    with _serve_bytes(b"NEW-EDITED") as edited_url:
        r = await client.post(
            "/office/callback",
            params={"token": token},
            json={"status": 2, "url": edited_url},
        )
    assert r.status_code == 200 and r.json()["error"] == 0
    # 文件已被编辑后内容覆盖
    raw = await client.get("/files/raw", params={"user_id": USER, "path": "report.docx"})
    assert raw.text == "NEW-EDITED"


async def test_office_callback_bad_token(client):
    r = await client.post(
        "/office/callback", params={"token": "nope"}, json={"status": 2, "url": "x"}
    )
    assert r.status_code == 403


async def test_office_callback_status_ignored(client):
    """status 非 2/6（如 1=编辑中）不应触发写回，直接 error 0。"""
    await _make_file(client, "live.docx", "KEEP")
    token = server._office_sign(
        {"path": "live.docx", "user_id": USER, "exp": int(time.time()) + 60}
    )
    r = await client.post(
        "/office/callback", params={"token": token}, json={"status": 1}
    )
    assert r.json()["error"] == 0
    raw = await client.get("/files/raw", params={"user_id": USER, "path": "live.docx"})
    assert raw.text == "KEEP"  # 未被改动


# ---------------------------------------------------------------------------
# P3 save_to_workspace — Agent 产物落地
# ---------------------------------------------------------------------------

def _ctx(user_id: str = USER):
    return SimpleNamespace(state={"_sbkey": user_id}, user_id=user_id)


async def test_save_to_workspace_appears_in_tree(client):
    from app.tools import save_to_workspace

    out = save_to_workspace("notes/summary.md", "# 研究综述", _ctx())
    assert out["success"] and out["path"] == "notes/summary.md"

    tree = (await client.get("/files/tree", params={"user_id": USER})).json()["tree"]
    notes = next(n for n in tree if n["name"] == "notes")
    assert any(c["name"] == "summary.md" for c in notes["children"])


def test_save_to_workspace_traversal_blocked():
    from app.tools import save_to_workspace

    assert "error" in save_to_workspace("../evil.txt", "x", _ctx())


def test_save_to_workspace_empty_name():
    from app.tools import save_to_workspace

    assert "error" in save_to_workspace("  ", "x", _ctx())
