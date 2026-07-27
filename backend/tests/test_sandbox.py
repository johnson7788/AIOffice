"""SandboxManager 的租户映射/复用/回收逻辑。

不依赖真实 OpenSandbox 服务或 SDK：用假的 pool/sandbox 注入，
并 stub 掉 run() 内部按需 import 的 RunCommandOpts。
运行：python tests/test_sandbox.py   或   pytest tests/test_sandbox.py
"""

import asyncio
import sys
import types

# --- stub opensandbox.models.execd.RunCommandOpts（run() 内部按需 import）---
_execd = types.ModuleType("opensandbox.models.execd")


class RunCommandOpts:
    def __init__(self, timeout=None):
        self.timeout = timeout


_execd.RunCommandOpts = RunCommandOpts
sys.modules.setdefault("opensandbox", types.ModuleType("opensandbox"))
sys.modules.setdefault("opensandbox.models", types.ModuleType("opensandbox.models"))
sys.modules["opensandbox.models.execd"] = _execd

from app.sandbox import SandboxManager  # noqa: E402


class _Msg:
    def __init__(self, text):
        self.text = text


class _Logs:
    def __init__(self, out, err):
        self.stdout = [_Msg(o) for o in out]
        self.stderr = [_Msg(e) for e in err]


class _Exec:
    def __init__(self, out, err, code):
        self.logs = _Logs(out, err)
        self.exit_code = code


class _Sandbox:
    def __init__(self, sid):
        self.sid = sid
        self.killed = False
        self.renews = 0

    async def renew(self, ttl):
        self.renews += 1

    async def kill(self):
        self.killed = True

    @property
    def commands(self):
        return self

    async def run(self, command, opts=None):
        return _Exec([f"out:{command}@{self.sid}"], ["err"], 0)


class _Pool:
    def __init__(self):
        self.acquires = 0

    async def acquire(self, sandbox_timeout=None):
        self.acquires += 1
        return _Sandbox(self.acquires)


def _mgr():
    m = SandboxManager()
    m._pool = _Pool()
    return m


async def _test_same_key_reuses_one_sandbox():
    m = _mgr()
    a = await m._get("u1")
    b = await m._get("u1")
    assert a is b
    assert m._pool.acquires == 1
    assert b.renews == 1  # 复用时续期


async def _test_distinct_keys_isolated():
    m = _mgr()
    a = await m._get("u1")
    b = await m._get("u2")
    assert a is not b
    assert m._pool.acquires == 2


async def _test_run_maps_result():
    m = _mgr()
    r = await m.run("u1", "echo hi", timeout=5)
    assert r["returncode"] == 0
    assert r["stdout"] == "out:echo hi@1"
    assert r["stderr"] == "err"


async def _test_release_kills_and_reacquires():
    m = _mgr()
    sb = await m._get("u1")
    await m.release("u1")
    assert sb.killed is True
    sb2 = await m._get("u1")
    assert sb2 is not sb
    assert m._pool.acquires == 2


def test_run_sync_bridges_to_loop():
    """同步入口 run_sync 应把协程投递到专用循环并阻塞拿到结果。"""
    from app import sandbox as sbx
    asyncio.run(sbx.start_pool())
    sbx.manager._pool = _Pool()

    try:
        r = sbx.run_sync("u1", "echo hi", timeout=5)
        assert r["returncode"] == 0
        assert r["stdout"] == "out:echo hi@1"
    finally:
        sbx.stop_loop()


def _run(coro):
    asyncio.run(coro)


def test_same_key_reuses_one_sandbox():
    _run(_test_same_key_reuses_one_sandbox())


def test_distinct_keys_isolated():
    _run(_test_distinct_keys_isolated())


def test_run_maps_result():
    _run(_test_run_maps_result())


def test_release_kills_and_reacquires():
    _run(_test_release_kills_and_reacquires())


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print("ok")
