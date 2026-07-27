"""
Narrator / Explainer module for the arXiv research agent.

Translates raw tool calls, thinking processes, and technical outputs into
user-friendly explanation cards. This is a programmatic "旁路解说者"
(side-channel narrator) that intercepts agent activity and renders it
in plain language — without blocking the main agent's workflow.

Cards are stored in session.state["_narrator_cards"] for retrieval
by client code or frontend displays.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.context import Context
from google.adk.models import LlmResponse
from google.adk.tools.base_tool import BaseTool

from .narrator_rules import NARRATOR_STATE_KEY, THINKING_PATTERNS, TOOL_LABELS

logger = logging.getLogger(__name__)


def _find_tool_label(tool_name: str) -> dict[str, str]:
    """Find the best matching label for a tool, falling back to pattern matching."""
    if tool_name in TOOL_LABELS:
        return TOOL_LABELS[tool_name]

    for pattern, info in TOOL_LABELS.items():
        if pattern.startswith("_") and pattern[1:] in tool_name.lower():
            return info

    # Ultimate fallback
    return {
        "label": tool_name.replace("_", " ").title(),
        "icon": "🔧",
        "detail": f"正在执行 {tool_name}",
    }


def _explain_thinking(text: str) -> str | None:
    """Try to match thinking text to a user-friendly explanation."""
    for pattern, explanation in THINKING_PATTERNS:
        if re.search(pattern, text):
            return explanation
    return None


def _summarize_args(args: dict[str, Any]) -> str:
    """Create a human-readable summary of tool arguments."""
    if not args:
        return ""

    parts = []
    for key, value in args.items():
        if isinstance(value, str):
            parts.append(f"{key}={value}")
        elif isinstance(value, (int, float, bool)):
            parts.append(f"{key}={value}")
        elif isinstance(value, list):
            parts.append(f"{key}=[{len(value)} items]")
        elif isinstance(value, dict):
            parts.append(f"{key}={{...}}")
        else:
            parts.append(f"{key}=...")

    return ", ".join(parts)


def _summarize_result(result: Any) -> str:
    """Create a human-readable summary of a tool result."""
    if result is None:
        return "无返回内容"

    if isinstance(result, str):
        lines = result.strip().split("\n")
        line_count = len(lines)
        char_count = len(result)
        first_line = lines[0].strip() if lines else ""

        if line_count == 1:
            return f"返回: {result}"
        else:
            return (
                f"返回 {line_count} 行 ({char_count} 字符)，"
                f"开头: {first_line}"
            )

    if isinstance(result, dict):
        keys = list(result.keys())
        # 特化 run_skill_script 的结果摘要
        if "status" in keys and "stdout" in keys:
            status = result.get("status", "")
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            if status == "success":
                return f"脚本执行成功，stdout 输出 {len(stdout)} 字符"
            elif status == "warning":
                return f"脚本执行成功（有警告），stdout 输出 {len(stdout)} 字符，stderr: {stderr[:100]}"
            elif status == "error" and stdout.strip():
                return f"脚本有 stderr 但 stdout 包含有效数据（{len(stdout)} 字符），数据可用"
            else:
                return f"脚本执行失败: {stderr[:200] if stderr else '无输出'}"

        if "error" in keys:
            return f"错误: {str(result['error'])}"
        return f"返回结构化数据，包含 {len(keys)} 个字段: {', '.join(keys[:5])}"

    if isinstance(result, list):
        return f"返回列表，共 {len(result)} 条数据"

    return str(result)


# ===========================================================================
# Callback Functions
# ===========================================================================


def before_tool_callback(
    *, tool: BaseTool, args: dict[str, Any], tool_context: Context
) -> dict[str, Any] | None:
    """
    Called before each tool execution. Adds a narrator card explaining
    what the agent is about to do, in plain language.

    ADK calls with keyword args:
      callback(tool=tool, args=args, tool_context=tool_context)

    Returns None (no modification to the tool call) but stores a card
    in session state.
    """
    tool_name = tool.name
    info = _find_tool_label(tool_name)
    args_summary = _summarize_args(args)

    card = {
        "phase": "before_tool",
        "tool": tool_name,
        "icon": info["icon"],
        "label": info["label"],
        "detail": info["detail"],
        "args": args_summary,
        "status": "running",
    }

    _store_card(tool_context, card)
    return None  # Don't modify the tool call


def after_tool_callback(
    *, tool: BaseTool, args: dict[str, Any], tool_context: Context, tool_response: Any
) -> Any:
    """
    Called after each tool execution. Adds a narrator card explaining
    what the tool produced, in plain language.

    ADK calls with keyword args:
      callback(tool=tool, args=args, tool_context=tool_context, tool_response=response)

    Returns the result (possibly modified for clarity) and stores a completion card.
    """
    tool_name = tool.name
    info = _find_tool_label(tool_name)

    # 优化：当 run_skill_script 返回 status="error" 但 stdout 有有效数据时，
    # 在结果中注入提示，防止模型误判为失败而进行不必要的重试
    if (
        tool_name == "run_skill_script"
        and isinstance(tool_response, dict)
        and tool_response.get("status") == "error"
        and tool_response.get("stdout", "").strip()
    ):
        tool_response = dict(tool_response)  # shallow copy
        tool_response["_hint"] = (
            "脚本执行产生了有效数据（见 stdout），可以直接使用。"
            "stderr 中的信息通常是日志或警告，不影响数据有效性。"
        )

    result_summary = _summarize_result(tool_response)

    card = {
        "phase": "after_tool",
        "tool": tool_name,
        "icon": info["icon"],
        "label": f"{info['label']} - 完成",
        "detail": result_summary,
        "status": "done",
    }

    _store_card(tool_context, card)
    return tool_response


def after_model_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    """
    Called after each LLM response.

    不再生成思考卡片：
    - 流式思考已通过 SSE "thought" 事件实时推送
    - 回调生成的卡片始终追加在正文末尾（参考文献之后），无法正确定位
    """
    return None  # Don't modify the LLM response


# ===========================================================================
# Helper Functions
# ===========================================================================


def _store_card(ctx: Context, card: dict[str, Any]) -> None:
    """
    Store a narrator card in session state for later retrieval.

    Appends to a list stored at NARRATOR_STATE_KEY in the session state.
    Uses ADK's State dict-like interface: read via .get(), write via []=.
    """
    try:
        state = ctx.state
        if state is None:
            return

        # state is a google.adk.sessions.state.State object — supports dict-like ops
        cards: list[dict[str, Any]] = state.get(NARRATOR_STATE_KEY, [])
        cards.append(card)
        state[NARRATOR_STATE_KEY] = cards
    except Exception:
        logger.debug("Could not store narrator card in session state", exc_info=True)


def get_narrator_cards(session_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """
    Retrieve all narrator cards stored in session state.

    Args:
        session_state: The session state dict from the runner.

    Returns:
        List of narrator card dicts, or empty list if none found.
    """
    if not session_state:
        return []
    return session_state.get(NARRATOR_STATE_KEY, [])


def format_cards_for_display(cards: list[dict[str, Any]]) -> str:
    """
    Format a list of narrator cards into a readable text display.

    Used by client.py to show the narrated process to users.
    """
    if not cards:
        return "(无解说数据)"

    lines = []
    lines.append("=" * 68)
    lines.append("  过程解说 — Agent 做了什么，为什么这么做")
    lines.append("=" * 68)

    for i, card in enumerate(cards, 1):
        icon = card.get("icon", "•")
        label = card.get("label", "")
        detail = card.get("detail", "")
        status = card.get("status", "")
        tool = card.get("tool", "")

        status_mark = "✓" if status == "done" else "…" if status == "running" else ""

        lines.append(f"\n  [{i}] {icon} {label} {status_mark}")
        if detail:
            lines.append(f"      {detail}")

        phase = card.get("phase", "")
        if phase == "before_tool" and card.get("args"):
            lines.append(f"      → 参数: {card['args']}")

    lines.append("\n" + "=" * 68)
    lines.append(f"  总计: {len(cards)} 个步骤")
    lines.append("=" * 68)

    return "\n".join(lines)


def format_cards_as_conversation(cards: list[dict[str, Any]]) -> str:
    """
    Format narrator cards as a natural-language conversation,
    suitable for non-technical users.
    """
    if not cards:
        return ""

    lines = ["\n--- 幕后过程 ---"]
    for card in cards:
        icon = card.get("icon", "")
        detail = card.get("detail", "")
        label = card.get("label", "")
        status = card.get("status", "")

        if status == "running":
            lines.append(f"  {icon} {detail}")
        elif status == "done":
            lines.append(f"  {icon} {detail}")
        elif status == "info":
            lines.append(f"  {icon} {label}: {detail}")
        else:
            lines.append(f"  {icon} {label}")

    lines.append("---")
    return "\n".join(lines)
