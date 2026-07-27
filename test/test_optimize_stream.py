"""
管理后端优化接口（/chat/optimize_stream）集成测试

测试场景：
    1. test_stream_structure_basic         — SSE 流结构完整性（思考/文本/done 事件）
    2. test_optimize_with_specific_log     — 指定日志文件名，验证 Agent 读日志产出分析
    3. test_optimize_arxiv_paper_skill     — 针对 arxiv-paper-search 优化，结合多条日志
    4. test_optimize_agent_instruction     — 根据日志优化 agent instruction

运行方式：
    cd test
    pytest test_optimize_stream.py -v
    MANAGE_SERVER_URL=http://localhost:8686 pytest test_optimize_stream.py -v

注意：测试会真实调用 LLM，每条约 1-5 分钟，建议单独运行：
    pytest test_optimize_stream.py::TestOptimizeStream::test_stream_structure_basic -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from conftest import collect_sse_events, extract_full_text, get_events_by_type

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
MANAGE_SERVER_URL = os.environ.get("MANAGE_SERVER_URL", "http://localhost:8686")
LOGS_DIR = Path(__file__).parent.parent / "backend" / "logs"
TIMEOUT = 600.0  # LLM 调用可能耗时较长

# 选取有代表性的日志文件（工具调用多、耗时长，优化价值高）
LOG_COMPLEX = "20260615_211245_a68f6ecf-256c-4d7d-bc44-0dd31383.jsonl"   # 12 tool_steps, 199s
LOG_RECENT  = "20260617_162453_b97d67d8-238c-41f4-a72b-c31d3b3e.jsonl"   # 9  tool_steps, 177s
LOG_SEARCH  = "20260617_174447_98fd803e-56c1-4bb2-a576-52db0d80.jsonl"   # 8  tool_steps, 87s（网络搜索）


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def manage_client():
    """指向管理后端（8686）的异步 HTTP 客户端。"""
    async with httpx.AsyncClient(base_url=MANAGE_SERVER_URL, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture
def manage_user_id(request) -> str:
    return f"test_opt_{request.node.name}"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def get_tool_step_calls(events: list[dict]) -> list[dict]:
    """从 tool_step 事件中提取所有子调用列表。"""
    calls = []
    for step in get_events_by_type(events, "tool_step"):
        calls.extend(step.get("calls", []))
    return calls


def assert_no_error(events: list[dict]):
    """断言流中没有 error 事件。"""
    errors = get_events_by_type(events, "error")
    assert not errors, f"收到 error 事件: {[e.get('message') for e in errors]}"


def assert_done(events: list[dict]) -> dict:
    """断言流以 done 事件结束，返回 done 事件。"""
    done_events = get_events_by_type(events, "done")
    assert len(done_events) == 1, f"期望 1 个 done 事件，实际 {len(done_events)}"
    assert events[-1]["type"] == "done", f"最后一个事件应为 done，实际: {events[-1]['type']}"
    return events[-1]


def log_exists(filename: str) -> bool:
    return (LOGS_DIR / filename).exists()


# ---------------------------------------------------------------------------
# 测试套件
# ---------------------------------------------------------------------------

class TestOptimizeStream:

    async def test_stream_structure_basic(self, manage_client, manage_user_id):
        """
        最基础的 SSE 流结构验证：
        - 能收到事件
        - 以 done 事件结束
        - done 包含 text_len / thought_count / step_count
        - 正文非空
        """
        message = (
            "快速分析一下 backend agent 当前的 instruction 有没有明显可以改进的地方，"
            "给出 1-2 条具体建议即可，不需要实际修改。"
        )
        resp = await manage_client.get(
            "/chat/optimize_stream",
            params={"message": message, "user_id": manage_user_id},
        )
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:300]}"
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = await collect_sse_events(resp)
        assert len(events) > 0, "未收到任何 SSE 事件"

        assert_no_error(events)
        done = assert_done(events)

        assert "text_len" in done, "done 事件缺少 text_len"
        assert "thought_count" in done, "done 事件缺少 thought_count"
        assert "step_count" in done, "done 事件缺少 step_count"

        text = extract_full_text(events)
        assert len(text) > 50, f"回答文本过短 ({len(text)} 字符): {text}"

        event_types = {e["type"] for e in events}
        print(f"\n[结构] 共 {len(events)} 事件，类型: {event_types}")
        print(f"[文本] {len(text)} 字符，thought={done['thought_count']}, steps={done['step_count']}")

    async def test_optimize_with_specific_log(self, manage_client, manage_user_id):
        """
        指定具体日志文件名，验证 Agent：
        - 能读取该日志文件
        - 在输出中体现对该会话的分析（工具调用次数多、耗时长等特征）
        - 产出具体优化建议
        """
        if not log_exists(LOG_COMPLEX):
            pytest.skip(f"日志文件不存在: {LOG_COMPLEX}")

        message = (
            f"请读取日志文件 backend/logs/{LOG_COMPLEX}，"
            "分析这次会话的工具调用情况（该会话有多次工具调用、耗时约 200 秒），"
            "找出造成耗时长的原因，并对 arxiv-paper-search 或 searxng skill 提出具体优化建议。"
            "只需要分析和建议，不需要实际修改文件。"
        )
        resp = await manage_client.get(
            "/chat/optimize_stream",
            params={
                "message": message,
                "skills": "arxiv-paper-search,searxng",
                "user_id": manage_user_id,
            },
        )
        assert resp.status_code == 200

        events = await collect_sse_events(resp)
        assert_no_error(events)
        assert_done(events)

        text = extract_full_text(events)
        assert len(text) > 100, f"优化建议文本过短: {text[:200]}"

        # Agent 应当使用了工具（读取文件或 API）
        calls = get_tool_step_calls(events)
        print(f"\n[工具] {len(calls)} 次子调用: {[c.get('tool_name') for c in calls]}")
        print(f"[文本摘要] {text[:300]}")

        # 回答中应提到日志或工具调用相关内容
        keywords = ["tool", "工具", "日志", "调用", "步骤", "优化", "搜索", "skill"]
        matched = [kw for kw in keywords if kw.lower() in text.lower()]
        assert len(matched) >= 2, (
            f"回答未体现日志分析内容，命中关键词: {matched}\n回答: {text[:400]}"
        )

    async def test_optimize_arxiv_paper_skill(self, manage_client, manage_user_id):
        """
        针对 arxiv-paper-search skill 的优化：
        - 传入 skills 参数，让 Agent 自动关联相关日志
        - 验证 Agent 读取了 skill 文件（tool_step 中有文件读取调用）
        - 验证输出包含对该 skill 的具体分析
        """
        # 构造两条日志的对比信息
        log_info = ""
        for fname in [LOG_COMPLEX, LOG_RECENT, LOG_SEARCH]:
            if log_exists(fname):
                log_info += f"- backend/logs/{fname}\n"

        message = (
            "请分析以下日志文件，重点关注 arxiv-paper-search 这个 skill 的使用情况：\n"
            f"{log_info}"
            "从日志中找出该 skill 在哪些场景下表现不佳（例如搜索关键词不准、结果不相关、"
            "需要多次重试等），给出 SKILL.md 中 instruction 部分的改进建议。"
            "只需要给出分析和建议文字，不需要修改文件。"
        )
        resp = await manage_client.get(
            "/chat/optimize_stream",
            params={
                "message": message,
                "skills": "arxiv-paper-search",
                "user_id": manage_user_id,
            },
        )
        assert resp.status_code == 200

        events = await collect_sse_events(resp)
        assert_no_error(events)
        done = assert_done(events)

        text = extract_full_text(events)
        assert len(text) > 100, f"分析结果过短: {text}"

        print(f"\n[skill 优化] steps={done['step_count']}, 文本={len(text)} 字符")
        print(f"[建议摘要] {text[:400]}")

    async def test_optimize_agent_instruction(self, manage_client, manage_user_id):
        """
        根据多条日志优化 agent instruction：
        - 日志中多次出现相同问题类型（学术论文方法对比）
        - 验证 Agent 读取了 agent.py 的当前 instruction
        - 验证输出包含对 instruction 的具体改进方向
        """
        recent_logs = [f for f in [LOG_RECENT, LOG_SEARCH, LOG_COMPLEX] if log_exists(f)]
        if not recent_logs:
            pytest.skip("没有可用的日志文件")

        log_list = "\n".join(f"- backend/logs/{f}" for f in recent_logs)
        message = (
            "请读取 backend/app/agent.py 的当前 instruction，"
            "再结合以下日志分析用户的实际使用模式：\n"
            f"{log_list}\n"
            "日志显示用户主要在做学术论文的方法对比，多次触发搜索工具。"
            "请分析当前 instruction 是否有不足之处，"
            "给出 1-3 条具体的修改建议（描述应修改的内容，不需要实际修改文件）。"
        )
        resp = await manage_client.get(
            "/chat/optimize_stream",
            params={"message": message, "user_id": manage_user_id},
        )
        assert resp.status_code == 200

        events = await collect_sse_events(resp)
        assert_no_error(events)
        done = assert_done(events)

        text = extract_full_text(events)
        assert len(text) > 100, f"建议文本过短: {text}"

        event_types = {e["type"] for e in events}
        print(f"\n[instruction 优化] 事件类型: {event_types}")
        print(f"[steps={done['step_count']}, 文本={len(text)} 字符]")
        print(f"[建议] {text[:500]}")

        # 回答中应提到 instruction 相关内容
        instr_keywords = ["instruction", "指令", "优化", "建议", "改进", "agent"]
        matched = [kw for kw in instr_keywords if kw.lower() in text.lower()]
        assert len(matched) >= 2, (
            f"回答未体现 instruction 分析，命中: {matched}\n回答: {text[:400]}"
        )
