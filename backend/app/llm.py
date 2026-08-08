"""Bridge agent-core's wire format to litellm streaming.

The frontend (packages/agent-core) speaks one shape both ways:
  request  = { system, messages: AgentMessage[], tools: AgentToolDef[] }
  response = IpcStreamChunk { requestId, type, text?, toolCall?, stopReason?, ... }

Tools are executed in the browser; here we only forward model text + the parsed
tool_call intents, matching packages/agent-core/src/ipc-transport.ts.
"""
import json
from collections.abc import AsyncIterator
from typing import Any

import litellm

from .config import resolve_model


def _to_litellm_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        role = m["role"]
        if role == "user":
            imgs = m.get("images") or []
            if imgs:
                content: list[dict] = [{"type": "text", "text": m.get("text", "")}]
                for img in imgs:
                    url = f"data:{img['mime']};base64,{img['base64']}"
                    content.append({"type": "image_url", "image_url": {"url": url}})
                out.append({"role": "user", "content": content})
            else:
                out.append({"role": "user", "content": m.get("text", "")})
        elif role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("text", "") or None}
            calls = m.get("toolCalls") or []
            if calls:
                msg["tool_calls"] = [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c.get("input", {}))},
                    }
                    for c in calls
                ]
            out.append(msg)
        elif role == "tool":
            for r in m.get("results", []):
                out.append(
                    {"role": "tool", "tool_call_id": r["id"], "name": r["name"], "content": r["output"]}
                )
    return out


def _to_litellm_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("inputSchema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _stop_reason(finish: str | None) -> str | None:
    if finish is None:
        return None
    return "max_tokens" if finish in ("length", "max_tokens") else finish


async def stream_turn(
    request_id: str, system: str, messages: list[dict], tools: list[dict], is_cancelled
) -> AsyncIterator[dict]:
    """Yield IpcStreamChunk dicts for one model turn. `is_cancelled()` -> bool."""
    model, kwargs = resolve_model()
    lm_messages = _to_litellm_messages(system, messages)
    call_kwargs: dict[str, Any] = {"model": model, "messages": lm_messages, "stream": True, **kwargs}
    if tools:
        call_kwargs["tools"] = _to_litellm_tools(tools)

    # accumulate streamed tool_call fragments by index
    acc: dict[int, dict] = {}
    finish: str | None = None
    try:
        response = await litellm.acompletion(**call_kwargs)
        async for chunk in response:
            if is_cancelled():
                break
            choice = chunk.choices[0]
            delta = choice.delta
            if getattr(choice, "finish_reason", None):
                finish = choice.finish_reason
            text = getattr(delta, "content", None)
            if text:
                yield {"requestId": request_id, "type": "delta", "text": text}
            for tc in getattr(delta, "tool_calls", None) or []:
                idx = tc.index if tc.index is not None else 0
                slot = acc.setdefault(idx, {"id": None, "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args"] += fn.arguments
                # re-arm the renderer's silence watchdog during a long args stream
                yield {"requestId": request_id, "type": "ping"}
    except Exception as e:  # noqa: BLE001 - surface any provider/network error to the client
        yield {"requestId": request_id, "type": "error", "error": str(e)}
        return

    if is_cancelled():
        yield {"requestId": request_id, "type": "done"}
        return

    truncated = _stop_reason(finish) == "max_tokens" and bool(acc)
    for slot in acc.values():
        call: dict[str, Any] = {"id": slot["id"] or "", "name": slot["name"]}
        try:
            call["input"] = json.loads(slot["args"]) if slot["args"] else {}
        except json.JSONDecodeError as e:
            call["input"] = {}
            call["inputError"] = str(e)
        if truncated:
            call["truncated"] = True
        yield {"requestId": request_id, "type": "tool-call", "toolCall": call}

    done: dict[str, Any] = {"requestId": request_id, "type": "done"}
    sr = _stop_reason(finish)
    if sr:
        done["stopReason"] = sr
    yield done
