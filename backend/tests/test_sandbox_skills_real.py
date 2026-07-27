"""Sandbox skill 文件上传与执行 — 真实集成测试。

前置条件：
  1. OpenSandbox 服务已启动：uvx opensandbox-server
  2. .env 里 SANDBOX_ENABLED=true

运行：pytest tests/test_sandbox_skills_real.py -v
"""

import asyncio
import json
import os

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.environ.get("SANDBOX_ENABLED", "").lower() in ("1", "true", "yes", "on"),
    reason="需要 SANDBOX_ENABLED=true 且 OpenSandbox 服务已启动",
)

from app import sandbox as sbx
from app.sandbox import ensure_skills_sync, write_file_sync


@pytest.fixture(scope="module")
def _pool():
    asyncio.run(sbx.start_pool())
    yield
    asyncio.run(sbx.stop_pool())


# 所有依赖沙箱的命令都用同一个 key，避免多租户干扰
_KEY = "test_user"


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------

def test_write_file_and_read_back(_pool):
    """上传文件到沙箱，然后通过 cat 确认内容。"""
    write_file_sync(_KEY, "/tmp/hello.txt", "hello sandbox")
    r = sbx.run_sync(_KEY, "cat /tmp/hello.txt", timeout=10)
    assert r["returncode"] == 0
    assert "hello sandbox" in r["stdout"]


def test_write_file_utf8(_pool):
    """上传 UTF-8 中文文件并验证。"""
    write_file_sync(_KEY, "/tmp/中文.txt", "你好，沙箱")
    r = sbx.run_sync(_KEY, "cat /tmp/中文.txt", timeout=10)
    assert "你好，沙箱" in r["stdout"]


def test_write_file_overwrite(_pool):
    """写入相同路径应覆盖已有文件。"""
    write_file_sync(_KEY, "/tmp/overwrite.txt", "first")
    write_file_sync(_KEY, "/tmp/overwrite.txt", "second")
    r = sbx.run_sync(_KEY, "cat /tmp/overwrite.txt", timeout=10)
    assert r["stdout"].strip() == "second"


def test_write_file_diff_tenant_isolated(_pool):
    """不同租户写入同名文件互不干扰。"""
    write_file_sync("user_a", "/tmp/secret.txt", "aaa")
    write_file_sync("user_b", "/tmp/secret.txt", "bbb")
    r_a = sbx.run_sync("user_a", "cat /tmp/secret.txt", timeout=10)
    r_b = sbx.run_sync("user_b", "cat /tmp/secret.txt", timeout=10)
    assert r_a["stdout"].strip() == "aaa"
    assert r_b["stdout"].strip() == "bbb"


# ---------------------------------------------------------------------------
# file_exists
# ---------------------------------------------------------------------------

def test_file_exists_true(_pool):
    """文件存在时 file_exists 返回 True。"""
    write_file_sync(_KEY, "/tmp/exists.txt", "data")
    assert asyncio.run(sbx.manager.file_exists(_KEY, "/tmp/exists.txt")) is True


def test_file_exists_false(_pool):
    """文件不存在时 file_exists 返回 False。"""
    assert asyncio.run(sbx.manager.file_exists(_KEY, "/tmp/nope.txt")) is False


# ---------------------------------------------------------------------------
# ensure_skills
# ---------------------------------------------------------------------------

def _install_skill_deps(key: str, deps: list[str]) -> None:
    """在沙箱中安装 Python 依赖（先配清华镜像加速）。"""
    r = sbx.run_sync(key, "pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple", timeout=10)
    assert r["returncode"] == 0, f"pip config failed: {r['stderr']}"
    pkgs = " ".join(deps)
    r = sbx.run_sync(key, f"pip install {pkgs} -q", timeout=300)
    assert r["returncode"] == 0, f"pip install failed: {r['stderr']}"


def test_ensure_skills_bingsearch_scripts_exist(_pool):
    """同步 bingsearch 后，安装依赖并在沙箱中执行脚本。"""
    ensure_skills_sync(_KEY, "bingsearch")

    # 确认文件存在
    r = sbx.run_sync(_KEY, "ls /skills/bingsearch/scripts/", timeout=10)
    assert "bing_search.py" in r["stdout"]
    r = sbx.run_sync(_KEY, "ls /skills/bingsearch/", timeout=10)
    assert "SKILL.md" in r["stdout"]
    assert "_meta.json" in r["stdout"]

    # 安装依赖并执行脚本
    _install_skill_deps(_KEY, ["aiohttp", "beautifulsoup4", "lxml"])
    r = sbx.run_sync(_KEY, "python3 /skills/bingsearch/scripts/bing_search.py --help", timeout=15)
    print(r["stdout"])
    assert r["returncode"] == 0
    assert "usage:" in r["stdout"]


def test_ensure_skills_arxiv_scripts_exist(_pool):
    """同步 arxiv-paper-search 后，安装依赖并在沙箱中执行脚本。"""
    ensure_skills_sync(_KEY, "arxiv-paper-search")
    r = sbx.run_sync(_KEY, "ls /skills/arxiv-paper-search/scripts/", timeout=10)
    assert "arxiv_search.py" in r["stdout"]

    _install_skill_deps(_KEY, ["aiohttp"])
    r = sbx.run_sync(_KEY, "python3 /skills/arxiv-paper-search/scripts/arxiv_search.py --help", timeout=15)
    assert r["returncode"] == 0
    assert "usage:" in r["stdout"]


def test_ensure_skills_idempotent(_pool):
    """重复 ensure_skills 不报错。"""
    ensure_skills_sync(_KEY, "bingsearch")
    # 第二次调用不应报错
    ensure_skills_sync(_KEY, "bingsearch")


def test_ensure_skills_nonexistent(_pool):
    """同步不存在的 skill 应抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        asyncio.run(sbx.manager.ensure_skills(_KEY, "nonexistent_skill"))


# ---------------------------------------------------------------------------
# 上传脚本 + 执行（不依赖第三方包）
# ---------------------------------------------------------------------------

TEST_SCRIPT = """\
import json, sys
data = {"language": "python", "test": "sandbox", "args": sys.argv[1:]}
print(json.dumps(data))
"""


def test_write_python_script_and_execute(_pool):
    """上传 Python 脚本到沙箱，执行并验证输出。"""
    write_file_sync(_KEY, "/scripts/test_tool.py", TEST_SCRIPT)
    r = sbx.run_sync(_KEY, "python3 /scripts/test_tool.py", timeout=10)
    assert r["returncode"] == 0
    assert json.loads(r["stdout"]) == {"language": "python", "test": "sandbox", "args": []}


def test_write_and_run_script_with_args(_pool):
    """上传脚本后带参数执行。"""
    write_file_sync(_KEY, "/scripts/args_test.py", TEST_SCRIPT)
    r = sbx.run_sync(
        _KEY,
        "python3 /scripts/args_test.py keyword1 keyword2",
        timeout=10,
    )
    assert r["returncode"] == 0
    result = json.loads(r["stdout"])
    assert result["args"] == ["keyword1", "keyword2"]


def test_ensure_skills_then_run_python(_pool):
    """同步 skill 后，编写一个调用 skill 模块的 Python 脚本并执行。"""
    ensure_skills_sync(_KEY, "bingsearch")

    # 直接验证文件可读
    r = sbx.run_sync(
        _KEY,
        "python3 -c \"print(open('/skills/bingsearch/SKILL.md').read()[:50])\"",
        timeout=10,
    )
    assert "bingsearch" in r["stdout"]


# ---------------------------------------------------------------------------
# ensure_skills + 工具联动
# ---------------------------------------------------------------------------

def test_ensure_skills_then_list_files_via_terminal(_pool):
    """同步后通过 terminal 列出 skill 文件，模拟工具联动。"""
    # 先清除旧数据：用不同租户
    key = "test_list_user"
    ensure_skills_sync(key, "bingsearch")
    ensure_skills_sync(key, "arxiv-paper-search")

    r = sbx.run_sync(key, "ls /skills/bingsearch/scripts/ /skills/arxiv-paper-search/scripts/", timeout=10)
    assert "bing_search.py" in r["stdout"]
    assert "arxiv_search.py" in r["stdout"]


# ---------------------------------------------------------------------------
# 多租户隔离
# ---------------------------------------------------------------------------

def test_ensure_skills_tenant_isolation(_pool):
    """不同租户同步同一 skill，文件互不影响。"""
    ensure_skills_sync("tenant_a", "bingsearch")
    ensure_skills_sync("tenant_b", "bingsearch")

    # tenant_a 改文件
    sbx.run_sync(
        "tenant_a",
        "echo 'print(\"tenant_a_version\")' > /skills/bingsearch/scripts/bing_search.py",
        timeout=10,
    )

    # tenant_b 不受影响
    r = sbx.run_sync("tenant_b", "cat /skills/bingsearch/scripts/bing_search.py", timeout=10)
    assert "tenant_a_version" not in r["stdout"]

# ---------------------------------------------------------------------------
# 多租户完整流程：上传 skill → 查看目录 → 执行脚本
# ---------------------------------------------------------------------------

def test_multi_tenant_full_flow(_pool):
    """多租户完整流程：各自上传 skill、验证目录结构、安装依赖、执行脚本。"""
    tenants = ["mt_tenant_a", "mt_tenant_b"]

    # 1. 每个租户同步两个 skill
    for t in tenants:
        ensure_skills_sync(t, "bingsearch")
        ensure_skills_sync(t, "arxiv-paper-search")
        # 为每个租户安装依赖（共享镜像配置）
        _install_skill_deps(t, ["aiohttp", "beautifulsoup4", "lxml"])

    # 2. 验证目录结构
    for t in tenants:
        r = sbx.run_sync(t, "ls /skills/bingsearch/scripts/", timeout=10)
        assert "bing_search.py" in r["stdout"], f"{t}: bing_search.py 不存在"
        r = sbx.run_sync(t, "ls /skills/arxiv-paper-search/scripts/", timeout=10)
        assert "arxiv_search.py" in r["stdout"], f"{t}: arxiv_search.py 不存在"

    # 3. 执行脚本 — 验证租户间互不影响
    for t in tenants:
        r = sbx.run_sync(t, "python3 /skills/bingsearch/scripts/bing_search.py --help", timeout=15)
        assert r["returncode"] == 0, f"{t}: bing_search --help 失败"
        assert "usage:" in r["stdout"], f"{t}: 输出缺少 usage:"
        print(f"{t} bing_search --help 成功")

    # 4. 验证真正隔离：在 mt_tenant_a 里篡改 bing_search.py
    sbx.run_sync(
        "mt_tenant_a",
        "echo 'print(\"hacked_by_A\")' > /skills/bingsearch/scripts/bing_search.py",
        timeout=5,
    )
    r_a = sbx.run_sync("mt_tenant_a", "python3 /skills/bingsearch/scripts/bing_search.py", timeout=10)
    assert r_a["stdout"].strip() == "hacked_by_A"

    # mt_tenant_b 的文件不受影响
    r_b = sbx.run_sync("mt_tenant_b", "python3 /skills/bingsearch/scripts/bing_search.py --help", timeout=15)
    assert r_b["returncode"] == 0
    assert "usage:" in r_b["stdout"], "tenant_b 脚本被意外篡改"
