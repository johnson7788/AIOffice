"""
Agent 沙箱隔离 E2E 测试 — 验证不同 user_id 的沙箱互不干扰。

前置条件：
  1. 后端已启动（SANDBOX_ENABLED=true）：bash start.sh
  2. OpenSandbox 服务已运行：bash start_sandbox.sh
  3. DEEPSEEK_API_KEY 已配置

测试场景：
  - 用户 A 通过 Agent 的 terminal 工具在沙箱写文件
  - 用户 B 尝试读取该文件 → 应该读不到（隔离）
  - 用户 A 再次读取 → 应该读得到（持久化）
  - 并发场景：两个用户同时操作不互相阻塞

运行方式：
  cd test
  pytest test_sandbox_isolation.py -v --timeout=300
"""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
from conftest import (
    collect_sse_events,
    extract_full_text,
    get_events_by_type,
    DEFAULT_TIMEOUT,
)

SERVER_URL = "http://localhost:8585"
MARKER_PREFIX = f"isol_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

async def send_terminal_request(
    client: httpx.AsyncClient, user_id: str, command_desc: str
) -> dict:
    """向 Agent 发送需要 terminal 工具的请求，返回结构化结果。

    返回:
        {
            "events": [...],        # 所有 SSE 事件
            "text": str,            # 拼接后的正文
            "tool_calls": [...],    # tool_call 事件列表
            "terminal_results": [str],  # terminal 工具的 result_summary 列表
        }
    """
    prompt = (
        f"请在终端执行以下命令（不要修改，直接执行），然后告诉我输出结果：\n"
        f"{command_desc}"
    )
    resp = await client.get(
        "/chat/stream",
        params={"message": prompt, "user_id": user_id},
    )
    assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"

    events = await collect_sse_events(resp)
    text = extract_full_text(events)
    tool_calls = get_events_by_type(events, "tool_call")

    terminal_results = []
    for tc in tool_calls:
        if tc.get("call_id", "") and tc.get("result_summary"):
            # 检查是否是 terminal 工具的结果（通过查找上层 tool_step）
            result_str = tc["result_summary"]
            try:
                result = json.loads(result_str)
                if "stdout" in result or "stderr" in result or "returncode" in result:
                    terminal_results.append(result)
            except (json.JSONDecodeError, TypeError):
                pass

    return {
        "events": events,
        "text": text,
        "tool_calls": tool_calls,
        "terminal_results": terminal_results,
    }


def get_terminal_stdout(result: dict, field: str = "stdout") -> str:
    """从 terminal 结果中提取 stdout。"""
    return result.get(field, "")


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------

class TestSandboxIsolation:
    """不同 user_id 的沙箱隔离测试。"""

    async def test_filesystem_isolation(self, client, test_user_id: str):
        """
        核心隔离测试：
        1. 用户 A 写入标记文件
        2. 用户 B 尝试读取 → 不应看到 A 的内容
        3. 用户 A 再次读取 → 应看到自己的内容
        """
        user_a = f"{test_user_id}_A"
        user_b = f"{test_user_id}_B"
        marker = f"{MARKER_PREFIX}_fs"
        filename = "/tmp/agent_isolation_test.txt"

        # --- Step 1: 用户 A 写文件 ---
        result_a_write = await send_terminal_request(
            client, user_a,
            f'echo "{marker}" > {filename} && cat {filename}',
        )
        assert result_a_write["terminal_results"], (
            f"用户 A 写入时未触发 terminal 工具。"
            f"正文: {result_a_write['text'][:300]}"
        )
        stdout_a = get_terminal_stdout(result_a_write["terminal_results"][-1])
        assert marker in stdout_a, (
            f"用户 A 写入后读回失败。stdout: {stdout_a}"
        )
        print(f"\n[Step 1] 用户 A 写入成功: {stdout_a.strip()}")

        # --- Step 2: 用户 B 尝试读取 ---
        result_b_read = await send_terminal_request(
            client, user_b,
            f'cat {filename} 2>&1; echo "EXIT_CODE=$?"',
        )
        assert result_b_read["terminal_results"], (
            f"用户 B 读取时未触发 terminal 工具。"
            f"正文: {result_b_read['text'][:300]}"
        )
        stdout_b = get_terminal_stdout(result_b_read["terminal_results"][-1])
        assert marker not in stdout_b, (
            f"隔离失败！用户 B 读到了用户 A 的文件内容: {stdout_b}"
        )
        print(f"[Step 2] 用户 B 读取结果（不应含标记）: {stdout_b.strip()}")

        # --- Step 3: 用户 A 再次确认 ---
        result_a_read = await send_terminal_request(
            client, user_a,
            f'cat {filename}',
        )
        assert result_a_read["terminal_results"], (
            f"用户 A 二次读取时未触发 terminal 工具。"
        )
        stdout_a2 = get_terminal_stdout(result_a_read["terminal_results"][-1])
        assert marker in stdout_a2, (
            f"用户 A 的文件丢失了！stdout: {stdout_a2}"
        )
        print(f"[Step 3] 用户 A 二次读取成功: {stdout_a2.strip()}")

    async def test_env_var_isolation(self, client, test_user_id: str):
        """
        环境变量隔离：用户 A 设置的环境变量，用户 B 看不到。
        """
        user_a = f"{test_user_id}_envA"
        user_b = f"{test_user_id}_envB"
        secret_val = f"{MARKER_PREFIX}_secret"

        # 用户 A 设置并读取环境变量
        result_a = await send_terminal_request(
            client, user_a,
            f'export MY_SECRET="{secret_val}" && echo "MY_SECRET=$MY_SECRET"',
        )
        assert result_a["terminal_results"], "用户 A 未触发 terminal"
        stdout_a = get_terminal_stdout(result_a["terminal_results"][-1])
        assert secret_val in stdout_a, f"用户 A 设置环境变量失败: {stdout_a}"
        print(f"\n[ENV] 用户 A 设置成功: {stdout_a.strip()}")

        # 用户 B 尝试读取
        result_b = await send_terminal_request(
            client, user_b,
            'echo "MY_SECRET=${MY_SECRET:-UNSET}"',
        )
        assert result_b["terminal_results"], "用户 B 未触发 terminal"
        stdout_b = get_terminal_stdout(result_b["terminal_results"][-1])
        assert secret_val not in stdout_b, (
            f"环境变量泄漏！用户 B 看到了: {stdout_b}"
        )
        print(f"[ENV] 用户 B 读取结果（不应含密钥）: {stdout_b.strip()}")

    async def test_concurrent_execution(self, client, test_user_id: str):
        """
        并发隔离：两个用户同时执行命令，结果不互相串扰。
        """
        user_a = f"{test_user_id}_concA"
        user_b = f"{test_user_id}_concB"
        tag_a = f"{MARKER_PREFIX}_CONC_A"
        tag_b = f"{MARKER_PREFIX}_CONC_B"

        # 并发发送
        task_a = send_terminal_request(
            client, user_a,
            f'sleep 2 && echo "{tag_a}"',
        )
        task_b = send_terminal_request(
            client, user_b,
            f'sleep 2 && echo "{tag_b}"',
        )
        result_a, result_b = await asyncio.gather(task_a, task_b)

        stdout_a = ""
        stdout_b = ""
        if result_a["terminal_results"]:
            stdout_a = get_terminal_stdout(result_a["terminal_results"][-1])
        if result_b["terminal_results"]:
            stdout_b = get_terminal_stdout(result_b["terminal_results"][-1])

        # 各自应看到自己的标记，不应看到对方的
        if stdout_a:
            assert tag_a in stdout_a, f"用户 A 未看到自己的标记: {stdout_a}"
            assert tag_b not in stdout_a, f"用户 A 看到了 B 的标记: {stdout_a}"
        if stdout_b:
            assert tag_b in stdout_b, f"用户 B 未看到自己的标记: {stdout_b}"
            assert tag_a not in stdout_b, f"用户 B 看到了 A 的标记: {stdout_b}"

        print(f"\n[并发] A: {stdout_a.strip()[:80]}")
        print(f"[并发] B: {stdout_b.strip()[:80]}")

    async def test_same_user_persistent_sandbox(self, client, test_user_id: str):
        """
        同一用户的多次请求应复用同一沙箱（文件持久化）。
        """
        user = f"{test_user_id}_persist"
        marker = f"{MARKER_PREFIX}_persist"
        filename = "/tmp/persist_test.txt"

        # 第一次：写入文件
        r1 = await send_terminal_request(
            client, user,
            f'echo "{marker}" > {filename}',
        )
        assert r1["terminal_results"], "第一次请求未触发 terminal"

        # 第二次：读取文件（同一 user_id → 同一沙箱）
        r2 = await send_terminal_request(
            client, user,
            f'cat {filename}',
        )
        assert r2["terminal_results"], "第二次请求未触发 terminal"
        stdout = get_terminal_stdout(r2["terminal_results"][-1])
        assert marker in stdout, (
            f"同一用户的沙箱未持久化！第二次读取结果: {stdout}"
        )
        print(f"\n[持久化] 同一用户两次请求间文件保持: {stdout.strip()}")
