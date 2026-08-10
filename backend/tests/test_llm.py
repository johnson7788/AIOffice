"""Unit tests for the agent-core <-> litellm bridge (no network)."""
import asyncio
from types import SimpleNamespace

import app.llm as llm
from app.llm import _stop_reason, _to_litellm_messages, _to_litellm_tools, stream_turn


def drain(agen):
    async def _c():
        return [x async for x in agen]

    return asyncio.run(_c())


def _chunk(text=None, tool_calls=None, finish=None):
    delta = SimpleNamespace(content=text, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish)
    return SimpleNamespace(choices=[choice])


def _tc(index, id=None, name=None, args=None):
    fn = SimpleNamespace(name=name, arguments=args)
    return SimpleNamespace(index=index, id=id, function=fn)


def _patch_stream(monkeypatch, chunks):
    async def fake_acompletion(**kwargs):
        async def agen():
            for c in chunks:
                yield c

        return agen()

    monkeypatch.setattr(llm.litellm, "acompletion", fake_acompletion)


# ---- pure conversions ----

def test_to_messages_user_assistant_tool():
    msgs = _to_litellm_messages(
        "sys",
        [
            {"role": "user", "text": "hi"},
            {
                "role": "assistant",
                "text": "ok",
                "toolCalls": [{"id": "c1", "name": "insert", "input": {"text": "x"}}],
            },
            {"role": "tool", "results": [{"id": "c1", "name": "insert", "output": "done"}]},
        ],
    )
    assert msgs[0] == {"role": "system", "content": "sys"}
    assert msgs[1] == {"role": "user", "content": "hi"}
    a = msgs[2]
    assert a["role"] == "assistant" and a["content"] == "ok"
    assert a["tool_calls"][0]["function"] == {"name": "insert", "arguments": '{"text": "x"}'}
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "name": "insert", "content": "done"}


def test_to_messages_user_with_image():
    msgs = _to_litellm_messages(
        "", [{"role": "user", "text": "see", "images": [{"base64": "AAA", "mime": "image/png"}]}]
    )
    content = msgs[0]["content"]
    assert content[0] == {"type": "text", "text": "see"}
    assert content[1]["image_url"]["url"] == "data:image/png;base64,AAA"


def test_to_tools_maps_input_schema():
    tools = _to_litellm_tools([{"name": "f", "description": "d", "inputSchema": {"type": "object"}}])
    assert tools[0]["function"] == {"name": "f", "description": "d", "parameters": {"type": "object"}}


def test_stop_reason_maps_length_to_max_tokens():
    assert _stop_reason(None) is None
    assert _stop_reason("length") == "max_tokens"
    assert _stop_reason("stop") == "stop"


# ---- stream_turn ----

def test_stream_text_then_done(monkeypatch):
    _patch_stream(monkeypatch, [_chunk(text="Hel"), _chunk(text="lo"), _chunk(finish="stop")])
    out = drain(stream_turn("r", "s", [{"role": "user", "text": "hi"}], [], lambda: False))
    assert [c for c in out if c["type"] == "delta"] == [
        {"requestId": "r", "type": "delta", "text": "Hel"},
        {"requestId": "r", "type": "delta", "text": "lo"},
    ]
    assert out[-1] == {"requestId": "r", "type": "done", "stopReason": "stop"}


def test_stream_tool_call_accumulates_args(monkeypatch):
    _patch_stream(
        monkeypatch,
        [
            _chunk(tool_calls=[_tc(0, id="c1", name="insert", args='{"te')]),
            _chunk(tool_calls=[_tc(0, args='xt":"hi"}')]),
            _chunk(finish="tool_calls"),
        ],
    )
    out = drain(stream_turn("r", "s", [], [{"name": "insert"}], lambda: False))
    assert any(c["type"] == "ping" for c in out)  # re-arms silence watchdog
    call = [c for c in out if c["type"] == "tool-call"][0]["toolCall"]
    assert call == {"id": "c1", "name": "insert", "input": {"text": "hi"}}
    assert out[-1]["stopReason"] == "tool_calls"


def test_stream_tool_call_invalid_json_sets_input_error(monkeypatch):
    _patch_stream(
        monkeypatch,
        [_chunk(tool_calls=[_tc(0, id="c1", name="f", args="{bad")]), _chunk(finish="tool_calls")],
    )
    out = drain(stream_turn("r", "s", [], [{"name": "f"}], lambda: False))
    call = [c for c in out if c["type"] == "tool-call"][0]["toolCall"]
    assert call["input"] == {} and "inputError" in call


def test_stream_truncated_tool_call(monkeypatch):
    _patch_stream(
        monkeypatch,
        [_chunk(tool_calls=[_tc(0, id="c1", name="f", args='{"a":1}')]), _chunk(finish="length")],
    )
    out = drain(stream_turn("r", "s", [], [{"name": "f"}], lambda: False))
    call = [c for c in out if c["type"] == "tool-call"][0]["toolCall"]
    assert call["truncated"] is True
    assert out[-1]["stopReason"] == "max_tokens"


def test_stream_error_chunk_on_exception(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(llm.litellm, "acompletion", boom)
    out = drain(stream_turn("r", "s", [], [], lambda: False))
    assert out == [{"requestId": "r", "type": "error", "error": "provider down"}]


def test_stream_cancellation_stops_and_emits_done(monkeypatch):
    _patch_stream(monkeypatch, [_chunk(text="a"), _chunk(text="b"), _chunk(finish="stop")])
    out = drain(stream_turn("r", "s", [], [], lambda: True))  # cancelled from the start
    assert out == [{"requestId": "r", "type": "done"}]
