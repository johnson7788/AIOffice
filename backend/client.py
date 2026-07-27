#!/usr/bin/env python3
"""
技能过程解说 Agent — 命令行客户端（模拟前端）

通过 HTTP 请求服务端 SSE 接口，按 type 字段分类渲染三类输出：
  - type: "text"            → 正文回复（主聊天区）
  - type: "thought"         → 思考过程（侧边栏，使用服务端翻译好的 narrated 字段）
  - type: "narrator_card"   → 工具解说（步骤时间线）
  - type: "done"            → 流结束

本客户端不依赖任何 narrator.py 内部逻辑，仅消费服务端 API，
与未来 TypeScript 前端的行为完全一致。

用法：
    python client.py                                    # 交互模式
    python client.py "分析销售数据"                       # 自定义查询
    python client.py --skill data-analysis               # 预设技能演示
    python client.py --verbose "研究 AI 趋势"            # 显示原始思考
    python client.py --url http://localhost:9000 "..."   # 指定服务端地址

环境：
    需要 server.py 已启动（python server.py）
"""

from __future__ import annotations

import argparse
import json
import sys

import requests

# ---------------------------------------------------------------------------
# 预设演示查询（与 server 端一致，仅用于 CLI 交互选择）
# ---------------------------------------------------------------------------
DEFAULT_QUERIES = [
    (
        "data-analysis",
        "我有一份月度销售数据 CSV 文件，包含以下列：日期、产品、地区、营收、"
        "销售数量、客户满意度。请加载数据分析技能，按照其分步方法论，"
        "对这份数据集做一次完整的数据分析。",
    ),
    (
        "research-synthesis",
        "研究远程办公对员工生产力的影响。请使用研究综合技能进行全面分析："
        "定义范围、评估来源、综合发现，给我一份结构化报告。",
    ),
]

DIVIDER = "─" * 68


def _section(title: str, char: str = "─") -> None:
    print(f"\n{char * 68}")
    print(f"  {title}")
    print(f"{char * 68}")


# ---------------------------------------------------------------------------
# 渲染函数 — 仅根据 SSE 事件的 type 字段分发，不依赖任何内部模块
# ---------------------------------------------------------------------------
def _render_text(data: dict) -> None:
    """渲染正文回复（type: text）— 流式输出到主聊天区。"""
    sys.stdout.write(data.get("text", ""))
    sys.stdout.flush()


def _render_thought(data: dict, verbose: bool = False) -> str | None:
    """渲染思考过程（type: thought）— 使用服务端翻译好的 narrated 字段。"""
    narrated = data.get("narrated")
    raw = data.get("raw", "")

    if narrated:
        sys.stdout.write(f"\n  🧠 {narrated}\n")
    else:
        # 服务端未能匹配翻译模式，截断展示
        short = raw[:80] + ("…" if len(raw) > 80 else "")
        sys.stdout.write(f"\n  🧠 {short}\n")

    sys.stdout.flush()

    if verbose:
        sys.stdout.write(f"     └─ 原文: {raw[:120]}\n")
        sys.stdout.flush()

    return narrated or raw


def _render_narrator_card(data: dict) -> None:
    """渲染工具解说卡片（type: narrator_card）— 步骤时间线。"""
    card = data.get("card", {})
    idx = data.get("card_index", 0) + 1  # 从 1 开始

    icon = card.get("icon", "•")
    label = card.get("label", "")
    detail = card.get("detail", "")
    status = card.get("status", "")

    mark = "✓" if status == "done" else "…" if status == "running" else ""

    sys.stdout.write(f"\n  [{idx}] {icon} {label} {mark}")
    if detail:
        sys.stdout.write(f"\n      {detail}")
    sys.stdout.write("\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# 核心：连接 SSE 流，按 type 分发渲染
# ---------------------------------------------------------------------------
def run_stream(base_url: str, query: str, verbose: bool = False) -> None:
    """
    连接 GET /chat/stream SSE 接口，实时分类渲染。

    完全基于 HTTP + SSE 协议，不导入任何服务端内部模块。
    """
    url = f"{base_url}/chat/stream"
    params = {"message": query}

    _section("用户提问", "═")
    print(f"  {query}")

    # 收集所有卡片数据，用于最终汇总
    all_cards: list[dict] = []
    thought_items: list[str] = []
    card_count = 0
    has_text = False

    try:
        resp = requests.get(url, params=params, stream=True, timeout=300)
        resp.raise_for_status()
    except requests.ConnectionError:
        print(f"\n错误: 无法连接到 {base_url}")
        print("请确保 server.py 已启动: python server.py")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"\n错误: 请求失败 — {e}")
        sys.exit(1)

    # ---- 实时流式渲染 ----
    _section("正文回复（实时流式）", "═")
    print()

    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue

        payload = line[len("data: "):].strip()

        # 流结束标记
        if payload == "[DONE]":
            break

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue

        event_type = data.get("type")

        if event_type == "text":
            if not has_text:
                has_text = True
            _render_text(data)

        elif event_type == "thought":
            translated = _render_thought(data, verbose=verbose)
            if translated:
                thought_items.append(translated)

        elif event_type == "narrator_card":
            card = data.get("card", {})
            all_cards.append(card)
            if card_count == 0:
                # 第一次出现卡片时，打印分区标题
                _section("工具解说（Agent 幕后操作）")
            _render_narrator_card(data)
            card_count += 1

        elif event_type == "done":
            card_count = data.get("card_count", card_count)

    print()

    # ---- 最终汇总 ----
    if all_cards:
        _section("工具解说汇总（完整回顾）")
        print()
        for i, card in enumerate(all_cards, 1):
            icon = card.get("icon", "•")
            label = card.get("label", "")
            detail = card.get("detail", "")
            status = card.get("status", "")
            mark = "✓" if status == "done" else "…" if status == "running" else ""

            print(f"  [{i}] {icon} {label} {mark}")
            if detail:
                print(f"      {detail}")
            if card.get("args"):
                print(f"      → 参数: {card['args']}")
            print()
        print(f"  总计: {len(all_cards)} 个步骤")
        print()

    # ---- 统计 ----
    _section("本次运行统计", "═")
    print(f"  正文回复: {'有' if has_text else '无'}")
    print(f"  思考过程: {len(thought_items)} 条（已由服务端翻译）")
    print(f"  工具解说: {card_count} 张卡片")
    print()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="技能过程解说 Agent — 命令行客户端（模拟前端，通过 HTTP 调用服务端）"
    )
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="用户提问。不提供则进入交互选择模式。",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="显示 Agent 原始思考内容（调试用，普通用户无需开启）。",
    )
    parser.add_argument(
        "--skill",
        choices=["data-analysis", "research-synthesis"],
        default=None,
        help="运行指定技能的预设演示查询。",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8585",
        help="服务端地址（默认: http://localhost:8585）。",
    )
    args = parser.parse_args()

    # ---- 确定查询文本 ----
    if args.query:
        query = args.query
    elif args.skill:
        for name, q in DEFAULT_QUERIES:
            if name == args.skill:
                query = q
                break
        else:
            query = DEFAULT_QUERIES[0][1]
    else:
        # 交互模式
        print()
        print("可选的演示查询：")
        for i, (name, _) in enumerate(DEFAULT_QUERIES, 1):
            print(f"  {i}. {name}")
        print(f"  {len(DEFAULT_QUERIES) + 1}. 输入自定义查询")
        print()

        choice = input(f"请选择 (1-{len(DEFAULT_QUERIES) + 1}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(DEFAULT_QUERIES):
                query = DEFAULT_QUERIES[idx][1]
            else:
                query = input("请输入您的查询: ").strip()
        except (ValueError, IndexError):
            query = input("请输入您的查询: ").strip()

        if not query:
            print("未输入查询，退出。")
            sys.exit(0)

    run_stream(args.url, query, verbose=args.verbose)


if __name__ == "__main__":
    main()
