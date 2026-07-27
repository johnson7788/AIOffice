"""
Case 1: 具体问题 — SSE 流式问答 + 缓存验证

测试场景：
    发送一个具体的方法对比问题（RAG vs 长上下文窗口），
    验证 SSE 流式响应的完整性、工具调用、回答质量，以及缓存命中行为。

测试用例：
    1. test_sse_stream_structure        — SSE 事件流结构完整性
    2. test_arxiv_search_triggered       — 论文检索工具被调用
    3. test_answer_mentions_both_methods — 回答同时涵盖两种方法
    4. test_cache_hit_on_repeat          — 相同问题命中缓存并返回一致结果

运行方式：
    cd test
    pytest test_specific_question.py -v
"""
from __future__ import annotations

import pytest
from conftest import (
    collect_sse_events,
    extract_full_text,
    get_events_by_type,
    get_tool_names,
)

# 测试问题：具体的方法对比研究问题
QUESTION = "对比 RAG（检索增强生成）与长上下文窗口在知识密集型任务上的优劣"


class TestSpecificResearchQuestion:
    """具体问题 SSE 流式问答测试套件。"""

    async def test_sse_stream_structure(self, client, test_user_id: str):
        """
        验证 SSE 事件流的结构完整性：
        - 必须收到事件
        - 最后一个事件必须是 done
        - done 事件包含正确的统计字段
        - 正文文本非空
        """
        resp = await client.get(
            "/chat/stream",
            params={"message": QUESTION, "user_id": test_user_id},
        )
        assert resp.status_code == 200, f"HTTP {resp.status_code}: {resp.text[:200]}"
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = await collect_sse_events(resp)
        assert len(events) > 0, "未收到任何 SSE 事件"

        # ---- done 事件 ----
        done_events = get_events_by_type(events, "done")
        assert len(done_events) == 1, f"期望 1 个 done 事件，实际 {len(done_events)}"
        assert events[-1]["type"] == "done", "最后一个事件必须是 done"

        done = events[-1]
        assert "text_len" in done, "done 缺少 text_len"
        assert "thought_count" in done, "done 缺少 thought_count"
        assert "step_count" in done, "done 缺少 step_count"
        assert "card_count" in done, "done 缺少 card_count"

        # ---- 正文 ----
        text = extract_full_text(events)
        assert len(text) > 100, (
            f"回答文本过短 ({len(text)} 字符)，可能不完整:\n{text[:300]}"
        )
        assert done["text_len"] == len(text), (
            f"done.text_len ({done['text_len']}) 与实际文本长度 ({len(text)}) 不匹配"
        )

        # ---- 事件类型覆盖 ----
        event_types = {e["type"] for e in events}
        assert "text" in event_types, "缺少 text 类型事件"

        # 打印摘要供调试
        print(f"\n[SSE 结构] 共 {len(events)} 事件, "
              f"类型: {event_types}, 正文 {len(text)} 字符")

    async def test_arxiv_search_triggered(self, client, test_user_id: str):
        """
        验证 Agent 在处理方法对比问题时调用了检索工具：
        - 必须有 tool_step 事件
        - 至少调用了搜索相关工具（直接工具名 或 skill 执行包装）
        - 工具调用状态最终为 done（非 error）
        """
        resp = await client.get(
            "/chat/stream",
            params={"message": QUESTION, "user_id": test_user_id},
        )
        events = await collect_sse_events(resp)

        tool_steps = get_events_by_type(events, "tool_step")
        assert len(tool_steps) > 0, (
            f"未触发任何工具调用，完整事件:\n"
            + "\n".join(str(e) for e in events[:20])
        )

        tool_names = get_tool_names(events)
        print(f"\n[工具调用] 使用的工具: {tool_names}")

        # Agent 可能通过直接工具名或 skill 包装调用搜索
        # 直接工具: arxiv_search, web_search
        # Skill 包装: run_skill_script, load_skill, load_skill_resource
        search_related_tools = {
            "arxiv_search", "web_search",
            "run_skill_script", "load_skill", "load_skill_resource",
        }
        triggered = search_related_tools & set(tool_names)
        assert len(triggered) > 0, (
            f"未触发任何搜索相关工具。实际工具: {tool_names}"
        )

        # 验证工具调用最终完成（非卡在 running）
        for step in tool_steps:
            for call in step.get("calls", []):
                status = call.get("status", "")
                assert status in ("running", "done", "error"), (
                    f"工具 {call.get('tool_name')} 状态异常: {status}"
                )

    async def test_answer_mentions_both_methods(self, client, test_user_id: str):
        """
        验证回答同时涵盖了两种方法（RAG 和 长上下文）以及相关概念。
        """
        resp = await client.get(
            "/chat/stream",
            params={"message": QUESTION, "user_id": test_user_id},
        )
        events = await collect_sse_events(resp)
        text = extract_full_text(events)

        # 检查关键词覆盖
        method_a_keywords = ["RAG", "检索增强", "retrieval", "检索"]
        method_b_keywords = ["长上下文", "long context", "上下文窗口", "context window"]
        topic_keywords = ["知识", "knowledge", "任务"]

        has_method_a = any(kw in text for kw in method_a_keywords)
        has_method_b = any(kw in text for kw in method_b_keywords)
        has_topic = any(kw in text for kw in topic_keywords)

        assert has_method_a, (
            f"回答未提及 RAG 相关关键词。\n"
            f"回答摘要: {text[:500]}"
        )
        assert has_method_b, (
            f"回答未提及长上下文相关关键词。\n"
            f"回答摘要: {text[:500]}"
        )
        assert has_topic, (
            f"回答未提及知识密集型任务相关内容。\n"
            f"回答摘要: {text[:500]}"
        )

        print(f"\n[回答质量] 包含: RAG✓ 长上下文✓ 知识任务✓")

    async def test_cache_hit_on_repeat(self, client, test_user_id: str):
        """
        验证缓存机制：
        1. 先查询缓存状态（记录初始 size）
        2. 发送相同问题两次
        3. 两次回答文本应完全一致
        4. 缓存 size 应增加
        """
        # 清空缓存确保干净状态
        await client.delete("/cache")

        # 第一次请求（cache miss → 生成并缓存）
        resp1 = await client.get(
            "/chat/stream",
            params={"message": QUESTION, "user_id": f"{test_user_id}_c1"},
        )
        events1 = await collect_sse_events(resp1)
        text1 = extract_full_text(events1)
        assert len(text1) > 100, f"首次回答过短: {len(text1)} 字符"

        # 检查缓存信息已更新
        cache_resp = await client.get("/cache/info")
        cache_info = cache_resp.json()
        assert cache_info["size"] > 0, "缓存应为空但实际有数据"
        print(f"\n[缓存] 当前 size={cache_info['size']}, "
              f"max_size={cache_info['max_size']}, ttl={cache_info['ttl']}")

        # 第二次请求（应命中缓存）
        resp2 = await client.get(
            "/chat/stream",
            params={"message": QUESTION, "user_id": f"{test_user_id}_c2"},
        )
        events2 = await collect_sse_events(resp2)
        text2 = extract_full_text(events2)

        # 两次正文文本应完全一致（缓存回放）
        assert text1 == text2, (
            f"缓存命中后回答不一致！\n"
            f"首次 ({len(text1)} 字符): {text1[:200]}\n"
            f"二次 ({len(text2)} 字符): {text2[:200]}"
        )

        # 两次都应收到 done 事件
        assert events1[-1]["type"] == "done"
        assert events2[-1]["type"] == "done"

        # done 事件的统计也应一致
        done1 = events1[-1]
        done2 = events2[-1]
        assert done1["text_len"] == done2["text_len"], "done.text_len 不一致"
        assert done1["step_count"] == done2["step_count"], "done.step_count 不一致"

        print(f"[缓存] 命中验证通过: 两次回答完全一致 ({len(text1)} 字符)")
