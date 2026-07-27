"""
共享 pytest fixtures — SSE 流式测试基础设施。

用法：
    pytest test/ -v --timeout=300
    TEST_SERVER_URL=http://host:port pytest test/ -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------
DEFAULT_SERVER_URL = "http://localhost:8585"
TEST_USER_PREFIX = "test_sse_"
# LLM 调用可能耗时较长，默认 3 分钟
DEFAULT_TIMEOUT = 600.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def server_url() -> str:
    """后端服务地址，可通过 TEST_SERVER_URL 环境变量覆盖。"""
    return os.environ.get("TEST_SERVER_URL", DEFAULT_SERVER_URL)


@pytest.fixture(scope="session")
def ppt_file_path() -> Path:
    """测试用 PPT 文件路径（LongContextLLM.pptx）。"""
    p = Path(__file__).parent / "LongContextLLM.pptx"
    assert p.exists(), f"PPT 测试文件不存在: {p}"
    return p


@pytest.fixture
def test_user_id(request) -> str:
    """每个测试函数独立的 user_id，避免互相干扰。"""
    return f"{TEST_USER_PREFIX}{request.node.name}"


@pytest.fixture
async def client(server_url: str):
    """异步 HTTP 客户端（自动关闭连接）。"""
    async with httpx.AsyncClient(base_url=server_url, timeout=DEFAULT_TIMEOUT) as c:
        yield c


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

async def collect_sse_events(response) -> list[dict]:
    """
    从 httpx StreamingResponse 中收集所有 SSE 事件。

    SSE 格式: ``data: {json}\\n\\n``
    返回按顺序排列的事件 dict 列表。
    """
    events: list[dict] = []
    buffer = ""
    async for raw_chunk in response.aiter_text():
        buffer += raw_chunk
        # 按双换行分割事件
        while "\n\n" in buffer:
            event_str, buffer = buffer.split("\n\n", 1)
            for line in event_str.strip().split("\n"):
                if line.startswith("data: "):
                    payload = line[len("data: "):]
                    try:
                        events.append(json.loads(payload))
                    except json.JSONDecodeError:
                        # 忽略无法解析的行
                        pass
    # 处理缓冲区中残留的数据
    if buffer.strip():
        for line in buffer.strip().split("\n"):
            if line.startswith("data: "):
                try:
                    events.append(json.loads(line[len("data: "):]))
                except json.JSONDecodeError:
                    pass
    return events


def extract_full_text(events: list[dict]) -> str:
    """从 SSE 事件列表中提取拼接后的完整正文文本。"""
    return "".join(e["text"] for e in events if e.get("type") == "text")


def get_events_by_type(events: list[dict], event_type: str) -> list[dict]:
    """按类型筛选 SSE 事件。"""
    return [e for e in events if e.get("type") == event_type]


def get_tool_names(events: list[dict]) -> list[str]:
    """从 tool_step 事件中提取所有工具名（去重、保序）。"""
    seen: set[str] = set()
    names: list[str] = []
    for step in get_events_by_type(events, "tool_step"):
        for call in step.get("calls", []):
            name = call.get("tool_name", "")
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names
