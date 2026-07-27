"""Sandbox 真实集成测试 — 需要 OpenSandbox 服务 + Docker。

前置条件：
  1. conda activate skill-ppt-agent
  2. OpenSandbox 服务已启动：uvx opensandbox-server
  3. .env 里 SANDBOX_ENABLED=true

运行：pytest tests/test_sandbox_real.py -v
"""

import asyncio
import os
import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.environ.get("SANDBOX_ENABLED", "").lower() in ("1", "true", "yes", "on"),
    reason="需要 SANDBOX_ENABLED=true 且 OpenSandbox 服务已启动",
)

from app import sandbox as sbx


@pytest.fixture(scope="module")
def _pool():
    asyncio.run(sbx.start_pool())
    yield
    asyncio.run(sbx.stop_pool())


def test_run_basic_command(_pool):
    r = sbx.run_sync("test_user", "echo hello sandbox", timeout=10)
    assert r["returncode"] == 0
    assert "hello sandbox" in r["stdout"]


def test_run_python_code(_pool):
    r = sbx.run_sync("test_user", 'python3 -c "print(1 + 1)"', timeout=10)
    assert r["returncode"] == 0
    assert r["stdout"].strip() == "2"


def test_stdout_truncation(_pool):
    long_output = "echo " + "A" * 10000
    r = sbx.run_sync("test_user", long_output, timeout=10)
    assert r["returncode"] == 0
    assert len(r["stdout"]) <= 8000


def test_multi_tenant_isolation(_pool):
    sbx.run_sync("user_a", 'echo "secret_a" > /tmp/data.txt', timeout=10)
    r = sbx.run_sync("user_b", "cat /tmp/data.txt 2>&1 || true", timeout=10)
    assert "secret_a" not in r["stdout"]


def test_same_tenant_reuses_sandbox(_pool):
    key = "test_reuse_user"
    sbx.run_sync(key, 'echo "shared" > /tmp/marker.txt', timeout=10)
    r = sbx.run_sync(key, "cat /tmp/marker.txt", timeout=10)
    assert r["stdout"].strip() == "shared"


def test_run_sync_works(_pool):
    r = sbx.run_sync("sync_user", "echo sync_works", timeout=10)
    assert r["returncode"] == 0
    assert "sync_works" in r["stdout"]


def test_release_and_reacquire(_pool):
    key = "release_test_user"
    sbx.run_sync(key, 'echo "before_release" > /tmp/rel.txt', timeout=10)
    asyncio.run(sbx.manager.release(key))
    r = sbx.run_sync(key, "cat /tmp/rel.txt 2>&1 || true", timeout=10)
    assert "before_release" not in r["stdout"]
