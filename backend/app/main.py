"""AIOffice thin backend (M0).

Serves the AI streaming contract the browser docs app expects (see
frontend/apps/docs/src/renderer/web-adapter.ts). Tools run in the browser; the
backend only proxies model text + tool-call intents and a few egress helpers
(search / image fetch) that browsers can't do cross-origin.
"""
import asyncio
import base64
import json

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .llm import stream_turn

app = FastAPI(title="AIOffice backend", version="0.1.0")

# same-origin in prod (Vite dev proxy / nginx); permissive here for direct :8585 dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# requestId -> cancel flag; set by /ai/cancel, polled by the stream generator
_cancelled: set[str] = set()


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/ai/stream")
async def ai_stream(request: Request) -> StreamingResponse:
    body = await request.json()
    request_id = body["requestId"]
    system = body.get("system", "")
    messages = body.get("messages", [])
    tools = body.get("tools", [])

    def is_cancelled() -> bool:
        return request_id in _cancelled

    async def gen():
        try:
            async for chunk in stream_turn(request_id, system, messages, tools, is_cancelled):
                if await request.is_disconnected():
                    break
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        finally:
            _cancelled.discard(request_id)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/ai/cancel")
async def ai_cancel(request: Request) -> dict:
    body = await request.json()
    rid = body.get("requestId")
    if rid:
        _cancelled.add(rid)
    return {"ok": True}


@app.get("/ai/fetch-image")
async def fetch_image(url: str) -> JSONResponse:
    # server-side fetch bypasses browser CORS; returns base64 for insert_image
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            mime = r.headers.get("content-type", "image/png").split(";")[0]
            b64 = base64.b64encode(r.content).decode()
            return JSONResponse({"base64": b64, "mime": mime})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)


# ponytail: search is M1. The web-adapter already falls back to empty results on
# error, so return empty here instead of 404 noise. Wire a real provider later.
@app.get("/ai/web-search")
async def web_search(query: str, max: int = 6) -> dict:
    return {"results": [], "method": "unavailable"}


@app.get("/ai/image-search")
async def image_search(query: str, max: int = 8) -> dict:
    return {"images": [], "method": "unavailable"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8585)
