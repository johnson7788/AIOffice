"""L1 后端集成测试（无浏览器、无容器）：

- /office/edit：打桩 litellm → 断言返回合法 {op}；LLM 输出非法 → 500。
- /files/raw + /files：文本文件 PUT/GET/DELETE round-trip。

运行：.venv/bin/python tests/test_office_edit.py   或   pytest tests/test_office_edit.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from httpx import ASGITransport

import litellm
from server import app

TEST_USER = "e2e_test_user"


def _fake_completion(content: str):
    async def _acompletion(*args, **kwargs):
        return {"choices": [{"message": {"content": content}}]}
    return _acompletion


async def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _test_office_edit_returns_op():
    litellm.acompletion = _fake_completion(
        '{"type":"set_slide_background","slide":0,"color":"#FFFACD"}')
    async with await _client() as c:
        r = await c.post("/office/edit", json={
            "text": "", "instruction": "把第一页背景改成浅黄色", "doc_type": "slide"})
    assert r.status_code == 200, r.text
    assert r.json()["op"] == {"type": "set_slide_background", "slide": 0, "color": "#FFFACD"}


async def _test_office_edit_rewrite_selection():
    litellm.acompletion = _fake_completion('{"type":"replace_selection","text":"改写后的句子"}')
    async with await _client() as c:
        r = await c.post("/office/edit", json={
            "text": "原句", "instruction": "改正式点", "doc_type": "word"})
    assert r.json()["op"] == {"type": "replace_selection", "text": "改写后的句子"}


async def _test_office_edit_bad_llm_output_500():
    litellm.acompletion = _fake_completion("这不是 JSON")
    async with await _client() as c:
        r = await c.post("/office/edit", json={
            "text": "", "instruction": "乱来", "doc_type": "slide"})
    assert r.status_code == 500
    assert "error" in r.json()


async def _test_office_edit_missing_instruction_400():
    async with await _client() as c:
        r = await c.post("/office/edit", json={"text": "x", "instruction": "", "doc_type": "word"})
    assert r.status_code == 400


async def _test_files_roundtrip():
    name = "e2e_note.txt"
    async with await _client() as c:
        # PUT 写
        r = await c.put("/files/raw", json={"path": name, "content": "hello e2e", "user_id": TEST_USER})
        assert r.status_code == 200, r.text
        # GET 读原始内容
        r = await c.get("/files/raw", params={"path": name, "user_id": TEST_USER})
        assert r.status_code == 200
        assert r.text == "hello e2e"
        # 出现在文件树
        r = await c.get("/files/tree", params={"user_id": TEST_USER})
        assert any(n["name"] == name for n in r.json()["tree"])
        # DELETE
        r = await c.delete("/files", params={"path": name, "user_id": TEST_USER})
        assert r.status_code == 200
        r = await c.get("/files/raw", params={"path": name, "user_id": TEST_USER})
        assert r.status_code == 404


def _run(coro):
    asyncio.run(coro)


def test_office_edit_returns_op():
    _run(_test_office_edit_returns_op())


def test_office_edit_rewrite_selection():
    _run(_test_office_edit_rewrite_selection())


def test_office_edit_bad_llm_output_500():
    _run(_test_office_edit_bad_llm_output_500())


def test_office_edit_missing_instruction_400():
    _run(_test_office_edit_missing_instruction_400())


def test_files_roundtrip():
    _run(_test_files_roundtrip())


if __name__ == "__main__":
    for _name, _fn in list(globals().items()):
        if _name.startswith("test_"):
            _fn()
    print("ok")
