"""SearXNG search proxy.

Browsers can't hit the search instance cross-origin, so the backend forwards
queries to a self-hosted SearXNG JSON endpoint and reshapes results into the
{results/images, method, error} contract the docs adapter expects
(frontend/apps/docs/src/shared/ipc.ts webSearch/imageSearch).
"""
import httpx

from .settings import SEARXNG_URL

_HEADERS = {"Accept": "application/json", "User-Agent": "AIOffice/1.0"}


async def _query(query: str, categories: str, language: str = "zh") -> dict:
    params = {
        "q": query,
        "format": "json",
        "language": language,
        "categories": categories,
        "safesearch": 0,
    }
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(SEARXNG_URL, params=params, headers=_HEADERS)
        r.raise_for_status()
        return r.json()


async def web_search(query: str, max_results: int = 6) -> dict:
    if not SEARXNG_URL:
        return {"results": [], "method": "unavailable"}
    try:
        data = await _query(query, "general")
    except Exception as e:  # noqa: BLE001
        return {"results": [], "method": "error", "error": str(e)}
    results = [
        {"title": it.get("title", ""), "url": it.get("url", ""), "snippet": it.get("content", "")}
        for it in data.get("results", [])[:max_results]
    ]
    out = {"results": results, "method": "searxng"}
    answers = data.get("answers") or []
    if answers:
        # answers may be strings or {answer: ...} dicts depending on engine
        first = answers[0]
        out["answer"] = first.get("answer") if isinstance(first, dict) else str(first)
    return out


async def image_search(query: str, max_results: int = 8) -> dict:
    if not SEARXNG_URL:
        return {"images": [], "method": "unavailable"}
    try:
        data = await _query(query, "images")
    except Exception as e:  # noqa: BLE001
        return {"images": [], "method": "error", "error": str(e)}
    images = []
    for it in data.get("results", []):
        img = it.get("img_src") or it.get("thumbnail_src")
        if not img:
            continue
        images.append(
            {
                "title": it.get("title", ""),
                "imageUrl": img,
                "sourceUrl": it.get("url", ""),
                "source": it.get("source") or it.get("engine", ""),
            }
        )
        if len(images) >= max_results:
            break
    return {"images": images, "method": "searxng"}
