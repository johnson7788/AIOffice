"""ONLYOFFICE 插件的「结构化编辑意图」——LLM 只产受限 op（JSON），插件端翻译成 Builder API 执行。

见 docs/plan.md §4.6（先窄后宽：受限指令集，而非放开生成任意 Builder JS）。
本模块是纯函数 + 自检，不依赖 FastAPI/沙箱，可 `python -m app.office_ops` 直接跑校验。
"""

import json
import re

# op 类型 → 必填字段。插件 poll.js / code.js 里有一张对应的「op → Builder 代码」翻译表。
# 分三类编辑器：slide(pptx) / cell(xlsx) / word(docx)。侧栏(broker)只做「无选区可寻址」的整篇/整页/按坐标 op。
ALLOWED_OPS = {
    "replace_selection": ["text"],               # 选区改写：PasteText([text])（仅可视面板，需选区）
    "set_slide_background": ["slide", "color"],  # slide：改某页背景 SetBackground(SolidFill(color))
    "set_slide_text": ["slide", "shape", "text"],  # slide：改某页第 shape 个形状的文字
    "set_cell": ["cell", "value"],               # cell：GetRange(cell).SetValue(value)，cell=A1 或 A1:B2
    "replace_text": ["find", "replace"],         # word：全文查找替换 SearchAndReplace
    # 把用户【当前选中的图片】替换成 src(data URI)。靠"当前选区"定位，无需图片 ID/序号——
    # 用户在编辑器里选中哪张就改哪张，插件调 executeMethod("PutImageDataToSelection")。
    "replace_selected_image": ["src", "width", "height"],
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_CELLREF = re.compile(r"^[A-Za-z]{1,3}[0-9]{1,7}(:[A-Za-z]{1,3}[0-9]{1,7})?$")

# 给 LLM 的系统提示：把自然语言指令解析成一个 op。插件负责在编辑器里执行。
SYSTEM_PROMPT = (
    "你是文档编辑意图解析器。用户在办公编辑器里给出编辑指令，你把它解析成【一个】操作对象，"
    "只输出 JSON，不要解释、不要 markdown 代码围栏。可选操作：\n"
    '1) 改写选中文本：{"type":"replace_selection","text":"改写后的完整文本"}\n'
    '2) 设置某页背景色（仅 pptx）：{"type":"set_slide_background","slide":0,"color":"#RRGGBB"}'
    "（slide 从 0 开始，「第一页/首页」=0）\n"
    '3) 改某页某个形状的文字（仅 pptx）：{"type":"set_slide_text","slide":0,"shape":0,"text":"新文字"}'
    "（shape 从 0 开始，通常 0=标题）\n"
    '4) 表格填值（仅 xlsx）：{"type":"set_cell","cell":"B2","value":"42"}（cell 支持 A1 或 A1:B2 区域）\n'
    '5) 全文查找替换（仅 docx）：{"type":"replace_text","find":"原词","replace":"新词"}\n'
    "颜色必须是 #RRGGBB 十六进制。若有选中文本且指令是改写它，用操作 1；否则按目标编辑器类型选对应操作。"
)


# ---------------------------------------------------------------------------
# 信箱（P6.3 broker 桥）：助手侧栏经 agent 产的 op 暂存于此，等编辑器插件轮询取走。
# 助手侧栏跨 iframe 够不到编辑器插件（社区版无 Connector），两边都只跟后端讲话即可绕开。
# ponytail: 进程内 dict，单后端进程够用；多 worker 部署再换 redis。
# ponytail: 按 user_id 分桶——一个用户同一时刻编辑器里就一个活动文档；多文档并发再按 doc 细分。
# ---------------------------------------------------------------------------
_PENDING: dict[str, list[dict]] = {}


def enqueue_op(user_id: str, op: dict) -> None:
    """投递一个 op 给指定用户的编辑器插件（追加到队尾）。"""
    _PENDING.setdefault(user_id, []).append(op)


def drain_ops(user_id: str) -> list[dict]:
    """取走并清空该用户待执行的 op（插件轮询调用）。"""
    return _PENDING.pop(user_id, [])


# 反向桥：编辑器插件把用户当前选区上报到此，助手侧栏轮询取来预填聊天输入框。
# 只存"最新一份"（选区是当前态、非队列），按 user_id 覆盖。
# ponytail: 进程内 dict，与 _PENDING 同理；多 worker 再换 redis。
_SELECTION: dict[str, dict] = {}


def set_selection(user_id: str, sel: dict) -> None:
    """插件上报用户当前选区（覆盖旧值）。"""
    _SELECTION[user_id] = sel


def get_selection(user_id: str) -> dict:
    """取用户当前选区（助手侧栏轮询）；无则空 dict。"""
    return _SELECTION.get(user_id) or {}


def parse_office_op(raw: str) -> dict:
    """把 LLM 原始输出解析并校验成一个合法 op；非法则抛 ValueError。"""
    s = (raw or "").strip()
    # 去掉可能的 ```json 代码围栏
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", s).strip()
    # 容错：截取第一个 { 到最后一个 }
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i : j + 1]
    try:
        op = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"不是合法 JSON: {e}")
    if not isinstance(op, dict):
        raise ValueError("op 必须是对象")
    t = op.get("type")
    if t not in ALLOWED_OPS:
        raise ValueError(f"不支持的 op 类型: {t!r}")
    for f in ALLOWED_OPS[t]:
        if f not in op:
            raise ValueError(f"op {t} 缺少字段 {f}")
    if t == "set_slide_background":
        if not isinstance(op["slide"], int) or op["slide"] < 0:
            raise ValueError("slide 必须是非负整数")
        if not (isinstance(op["color"], str) and _HEX.match(op["color"])):
            raise ValueError("color 必须是 #RRGGBB")
    if t == "set_slide_text":
        if not isinstance(op["slide"], int) or op["slide"] < 0:
            raise ValueError("slide 必须是非负整数")
        if not isinstance(op["shape"], int) or op["shape"] < 0:
            raise ValueError("shape 必须是非负整数")
        if not isinstance(op["text"], str):
            raise ValueError("text 必须是字符串")
    if t == "set_cell":
        if not (isinstance(op["cell"], str) and _CELLREF.match(op["cell"])):
            raise ValueError("cell 必须是 A1 或 A1:B2 形式的引用")
        if not isinstance(op["value"], str):
            raise ValueError("value 必须是字符串")
    if t == "replace_selected_image":
        if not (isinstance(op["src"], str) and op["src"].startswith("data:")):
            raise ValueError("src 必须是 data: URI")
        for k in ("width", "height"):
            if not isinstance(op[k], int) or op[k] <= 0:
                raise ValueError(f"{k} 必须是正整数")
    # 只保留已知字段，防止插件收到多余键
    return {k: op[k] for k in (["type"] + ALLOWED_OPS[t])}


if __name__ == "__main__":
    # ponytail: 一个 assert 自检，跑 `python -m app.office_ops` 通过即 parser 正确
    assert parse_office_op('{"type":"replace_selection","text":"你好"}') == {
        "type": "replace_selection", "text": "你好"}
    assert parse_office_op('```json\n{"type":"set_slide_background","slide":0,"color":"#FFFACD"}\n```') == {
        "type": "set_slide_background", "slide": 0, "color": "#FFFACD"}
    assert parse_office_op('前言{"type":"replace_text","find":"a","replace":"b","junk":1}后语') == {
        "type": "replace_text", "find": "a", "replace": "b"}
    assert parse_office_op('{"type":"set_cell","cell":"B2","value":"42"}') == {
        "type": "set_cell", "cell": "B2", "value": "42"}
    assert parse_office_op('{"type":"set_cell","cell":"A1:C3","value":"x"}') == {
        "type": "set_cell", "cell": "A1:C3", "value": "x"}
    assert parse_office_op('{"type":"set_slide_text","slide":1,"shape":0,"text":"标题"}') == {
        "type": "set_slide_text", "slide": 1, "shape": 0, "text": "标题"}
    assert parse_office_op('{"type":"replace_selected_image","src":"data:image/png;base64,AAA","width":10,"height":20}') == {
        "type": "replace_selected_image", "src": "data:image/png;base64,AAA", "width": 10, "height": 20}
    for bad in ['{}', '{"type":"drop_table"}', '{"type":"set_slide_background","slide":-1,"color":"#FFFACD"}',
                '{"type":"set_slide_background","slide":0,"color":"red"}', 'not json',
                '{"type":"set_cell","cell":"ZZ","value":"1"}',  # 无行号
                '{"type":"set_cell","cell":"B2","value":7}',    # value 非字符串
                '{"type":"replace_selected_image","src":"http://x","width":1,"height":1}',  # src 非 data URI
                '{"type":"replace_selected_image","src":"data:x","width":0,"height":1}',    # width 非正
                '{"type":"set_slide_text","slide":0,"shape":-1,"text":"x"}']:
        try:
            parse_office_op(bad)
            raise AssertionError(f"应拒绝: {bad}")
        except ValueError:
            pass
    print("office_ops self-check OK")
