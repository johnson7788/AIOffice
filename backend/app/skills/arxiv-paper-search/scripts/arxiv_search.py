#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
arXiv 论文检索接口 — 支持关键词检索、最新论文、按分类/作者检索，以及自由检索表达式。
基于 arXiv 官方公开 API（http://export.arxiv.org/api/query），免费、无需 token。
通过命令行参数调用，输出 JSON 格式结果。
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

import aiohttp

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
API_URL = "http://export.arxiv.org/api/query"
DEFAULT_MAX_RESULTS = 20
REQUEST_TIMEOUT = 30

# Atom / arXiv XML 命名空间
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# 排序方式映射
SORT_MAP = {
    "relevant": "relevance",
    "recent": "submittedDate",
    "updated": "lastUpdatedDate",
}


# ---------------------------------------------------------------------------
# 检索表达式构造
# ---------------------------------------------------------------------------
def build_query(keywords: List[str], field: str = "all") -> str:
    """将多个关键词用 AND 连接为 arXiv 检索表达式。

    例如 ["transformer", "long context"] -> all:"transformer" AND all:"long context"
    """
    terms = [f'{field}:"{kw.strip()}"' for kw in keywords if kw.strip()]
    return " AND ".join(terms)


# ---------------------------------------------------------------------------
# XML 解析
# ---------------------------------------------------------------------------
def parse_entry(entry: ET.Element) -> Dict[str, Any]:
    """解析单条 arXiv Atom entry 为结构化字典。"""

    def text(path: str) -> str:
        node = entry.find(path, NS)
        return node.text.strip() if node is not None and node.text else ""

    authors = [
        a.text.strip()
        for a in entry.findall("atom:author/atom:name", NS)
        if a.text
    ]

    # arXiv id 形如 http://arxiv.org/abs/2401.01234v1
    abs_url = text("atom:id")
    arxiv_id = abs_url.rsplit("/", 1)[-1] if abs_url else ""

    pdf_url = ""
    for link in entry.findall("atom:link", NS):
        if link.get("title") == "pdf":
            pdf_url = link.get("href", "")
            break

    primary = entry.find("arxiv:primary_category", NS)
    primary_category = primary.get("term", "") if primary is not None else ""
    categories = [c.get("term", "") for c in entry.findall("atom:category", NS)]

    return {
        "id": arxiv_id,
        "title": " ".join(text("atom:title").split()),
        "abstract": " ".join(text("atom:summary").split()),
        "authors": ", ".join(authors),
        "primary_category": primary_category,
        "categories": categories,
        "published": text("atom:published"),
        "updated": text("atom:updated"),
        "comment": text("arxiv:comment"),
        "journal_ref": text("arxiv:journal_ref"),
        "doi": text("arxiv:doi"),
        "link": abs_url,
        "pdf": pdf_url,
    }


def parse_feed(xml_text: str) -> List[Dict[str, Any]]:
    """解析 arXiv API 返回的 Atom feed。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("解析 arXiv 响应失败: %s", exc)
        return []
    return [parse_entry(e) for e in root.findall("atom:entry", NS)]


# ---------------------------------------------------------------------------
# HTTP 检索
# ---------------------------------------------------------------------------
async def _fetch(
    session: aiohttp.ClientSession,
    search_query: str,
    sort_by: str = "relevance",
    max_results: int = DEFAULT_MAX_RESULTS,
) -> List[Dict[str, Any]]:
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": "descending",
    }
    try:
        async with session.get(
            API_URL, params=params, timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        ) as resp:
            resp.raise_for_status()
            xml_text = await resp.text()
            return parse_feed(xml_text)
    except Exception as exc:  # noqa: BLE001 - 检索失败返回空列表，不中断整体流程
        logger.warning("arXiv 检索失败 (%s): %s", search_query, exc)
        return []


async def search_one(
    search_query: str, sort_by: str = "relevance", max_results: int = DEFAULT_MAX_RESULTS
) -> List[Dict[str, Any]]:
    async with aiohttp.ClientSession() as session:
        return await _fetch(session, search_query, sort_by, max_results)


async def search_all(
    keywords: List[str], max_results: int = DEFAULT_MAX_RESULTS
) -> Dict[str, List[Dict[str, Any]]]:
    """并行检索多个维度：按相关性、按最新提交。"""
    query = build_query(keywords)
    async with aiohttp.ClientSession() as session:
        by_relevance, by_recent = await asyncio.gather(
            _fetch(session, query, "relevance", max_results),
            _fetch(session, query, "submittedDate", max_results),
        )
    return {
        "by_relevance": by_relevance,
        "by_recent": by_recent,
    }


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="arXiv 论文检索工具")
    parser.add_argument(
        "mode",
        choices=["all", "search", "recent", "category", "author", "free"],
        help="检索模式",
    )
    parser.add_argument("keywords", nargs="*", help="检索关键词（英文）")
    parser.add_argument("--category", "-c", default=None, help="arXiv 分类，如 cs.CL、cs.LG")
    parser.add_argument("--query", "-q", default=None, help="自由检索表达式（free 模式）")
    parser.add_argument(
        "--sort",
        "-s",
        choices=list(SORT_MAP.keys()),
        default="relevant",
        help="排序：relevant（默认）/ recent / updated",
    )
    parser.add_argument(
        "--max", "-m", type=int, default=DEFAULT_MAX_RESULTS, help="最大返回数量（默认 20）"
    )

    args = parser.parse_args()
    sort_by = SORT_MAP[args.sort]

    if args.mode == "all":
        if not args.keywords:
            print(json.dumps({"error": "all 模式需要至少一个关键词"}, ensure_ascii=False))
            sys.exit(0)
        result: Any = asyncio.run(search_all(args.keywords, args.max))

    elif args.mode == "search":
        result = asyncio.run(search_one(build_query(args.keywords), sort_by, args.max))

    elif args.mode == "recent":
        result = asyncio.run(
            search_one(build_query(args.keywords), "submittedDate", args.max)
        )

    elif args.mode == "category":
        if not args.category:
            print(json.dumps({"error": "category 模式需要 --category"}, ensure_ascii=False))
            sys.exit(0)
        query = f"cat:{args.category}"
        if args.keywords:
            query = f"({build_query(args.keywords)}) AND {query}"
        result = asyncio.run(search_one(query, sort_by, args.max))

    elif args.mode == "author":
        result = asyncio.run(search_one(build_query(args.keywords, field="au"), sort_by, args.max))

    elif args.mode == "free":
        if not args.query:
            print(json.dumps({"error": "free 模式需要 --query"}, ensure_ascii=False))
            sys.exit(0)
        result = asyncio.run(search_one(args.query, sort_by, args.max))

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
