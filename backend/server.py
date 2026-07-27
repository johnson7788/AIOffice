#!/usr/bin/env python3
"""
学术论文研究智能体 — FastAPI 服务端（协议 v2）

SSE 事件类型（GET /chat/stream）：

  type: "text"          正文增量（打字机）
  type: "thought"       思考过程（含 narrated 翻译）
  type: "tool_step"     Agent 单轮工具步骤（含子调用列表）
  type: "tool_call"     单次工具调用结束（含 status/result 摘要）
  type: "done"          流结束汇总

前端凭 tool_step 渲染可折叠的工具卡片，凭 tool_call 更新子条目状态。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

# 禁用系统代理 — macOS 系统代理 127.0.0.1:7890 未运行时会导致所有 API 请求失败
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

if not os.environ.get("DEEPSEEK_API_KEY"):
    print("错误: DEEPSEEK_API_KEY 未设置。")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("skill_ppt_agent")

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.artifacts import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from app.agent import root_agent, UPLOADS_DIR
from app.file_reader import read_file
from app.narrator import _explain_thinking, get_narrator_cards
from app.narrator_rules import TOOL_LABELS

# ---------------------------------------------------------------------------
APP_NAME = "arxiv-research-agent"

app = FastAPI(title="学术论文研究智能体")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health")
async def health():
    return {"status": "ok"}

session_service = InMemorySessionService()
artifact_service = InMemoryArtifactService()
runner = Runner(
    agent=root_agent,
    session_service=session_service,
    artifact_service=artifact_service,
    app_name=APP_NAME,
)

NARRATOR_STATE_KEY = "_narrator_cards"


@app.on_event("startup")
async def _start_sandbox_pool() -> None:
    from app import sandbox as sbx
    if sbx.enabled():
        await sbx.start_pool()
        logger.info("Sandbox pool started (multi-tenant isolation ON)")


@app.on_event("shutdown")
async def _stop_sandbox_pool() -> None:
    from app import sandbox as sbx
    if sbx.enabled():
        await sbx.stop_pool()


# ---------------------------------------------------------------------------
# SSE 响应缓存 — 持久化到本地 cache/ 目录，重启不丢失，方便回溯
# ---------------------------------------------------------------------------
CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class SSECache:
    """
    基于文件系统的 SSE 事件缓存。

    每个缓存条目是一个 JSON 文件：cache/{md5}.json
    文件内容包含原始消息、事件列表和元信息，方便人工回溯。
    TTL 和 LRU 基于文件的修改时间（mtime）。
    """

    def __init__(self, max_size: int = 500, ttl: int = 86400, enabled: bool = True):
        self._max_size = max_size
        self._ttl = ttl
        self._enabled = enabled

    @staticmethod
    def _make_key(message: str) -> str:
        """生成缓存 key：对消息文本归一化后取 MD5。"""
        normalized = " ".join(message.strip().lower().split())
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return CACHE_DIR / f"{key}.json"

    def get(self, message: str) -> list | None:
        if not self._enabled:
            return None
        key = self._make_key(message)
        p = self._path(key)
        if not p.exists():
            return None

        # TTL 检查（基于文件修改时间）
        mtime = p.stat().st_mtime
        if time.time() - mtime > self._ttl:
            p.unlink(missing_ok=True)
            return None

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            # 更新 mtime（touch）以支持 LRU
            p.touch()
            return data.get("events")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Cache read error for %s: %s", key, e)
            p.unlink(missing_ok=True)
            return None

    def set(self, message: str, events: list) -> None:
        if not self._enabled:
            return
        key = self._make_key(message)
        self._evict_if_needed()

        data = {
            "key": key,
            "message": message[:500],  # 保留原始消息前 500 字符，方便人工识别
            "event_count": len(events),
            "created_at": datetime.now().isoformat(),
            "events": events,
        }
        try:
            self._path(key).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("Cache write error for %s: %s", key, e)

    def _evict_if_needed(self) -> None:
        """如果缓存文件数超过 max_size，按 mtime 淘汰最旧的。"""
        files = sorted(CACHE_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime)
        while len(files) >= self._max_size:
            oldest = files.pop(0)
            oldest.unlink(missing_ok=True)

    def clear(self) -> int:
        files = list(CACHE_DIR.glob("*.json"))
        for f in files:
            f.unlink(missing_ok=True)
        return len(files)

    def info(self) -> dict:
        files = list(CACHE_DIR.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "enabled": self._enabled,
            "size": len(files),
            "max_size": self._max_size,
            "ttl": self._ttl,
            "total_size_kb": round(total_size / 1024, 1),
            "dir": str(CACHE_DIR),
        }


# 模块级缓存实例（可通过环境变量配置）
# SSE_CACHE_ENABLED 控制是否启用缓存（true/1/yes/on 启用，默认启用）
_sse_cache = SSECache(
    max_size=int(os.environ.get("SSE_CACHE_MAX_SIZE", "500")),
    ttl=int(os.environ.get("SSE_CACHE_TTL", "86400")),  # 默认 24 小时
    enabled=os.environ.get("SSE_CACHE_ENABLED", "true").strip().lower()
    in ("true", "1", "yes", "on"),
)


# ---------------------------------------------------------------------------
# Session 日志 — 每个会话独立 JSONL 文件，记录完整交互过程
# ---------------------------------------------------------------------------
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class SessionLogger:
    """
    每个 session 写入一个独立的 JSONL 日志文件。

    文件格式：logs/{YYYYMMDD_HHMMSS}_{session_id}.jsonl
    每行一个 JSON 对象，类型包括：
      - meta:        会话元信息（user_id, message, session_id, start_time）
      - text:        正文增量
      - thought:     思考过程
      - tool_step:   工具步骤
      - tool_call:   工具调用结果
      - narrator_card: 解说卡片
      - done:        流结束汇总
      - error:       异常信息
    """

    def __init__(self, session_id: str, user_id: str, message: str):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_id = session_id.replace("/", "_").replace("\\", "_")[:32]
        self.path = LOGS_DIR / f"{ts}_{safe_id}.jsonl"
        self._fh = open(self.path, "w", encoding="utf-8")
        self._event_count = 0
        self._start_time = time.time()

        # 写入元信息
        self._write({
            "type": "meta",
            "session_id": session_id,
            "user_id": user_id,
            "message": message,
            "start_time": datetime.now().isoformat(),
        })
        logger.info("Session log → %s", self.path.name)

    def _write(self, record: dict) -> None:
        """写入一行 JSONL。"""
        record["ts"] = time.time()
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()

    def log_event(self, evt: dict) -> None:
        """记录一个 SSE 事件（text/thought/tool_step/tool_call/narrator_card/done）。"""
        self._write(evt)
        self._event_count += 1

    def log_error(self, error: str) -> None:
        """记录异常。"""
        self._write({"type": "error", "error": error})

    def close(self) -> None:
        """写入汇总并关闭文件。"""
        elapsed = round(time.time() - self._start_time, 2)
        self._write({
            "type": "summary",
            "event_count": self._event_count,
            "elapsed_seconds": elapsed,
            "end_time": datetime.now().isoformat(),
        })
        self._fh.close()
        logger.info("Session log closed: %d events, %.1fs → %s",
                     self._event_count, elapsed, self.path.name)


class ChatRequest(BaseModel):
    message: str
    user_id: str = "default_user"


# ---------------------------------------------------------------------------
# 工具步骤解析助手
# ---------------------------------------------------------------------------

def _extract_tool_info(event) -> dict | None:
    """
    从 ADK event 中提取工具调用信息。
    返回:
      {
        "step_summary": str,    # 本轮 Agent 的简短思维摘要（从 thought/text 提取）
        "calls": [              # 本轮所有工具调用
          {
            "id": str,
            "tool_name": str,
            "display_name": str,  # 更友好的显示名
            "args_summary": str,  # 参数摘要（截断）
            "status": "running"|"done"|"error",
            "result_summary": str | None,
          }
        ]
      }
    若本 event 不含工具调用则返回 None。
    """
    if not event.content or not event.content.parts:
        return None

    calls = []
    step_summary_parts = []

    for part in event.content.parts:
        # 思考文本 → 作为 step_summary
        if hasattr(part, "thought") and part.thought:
            raw = (part.text or "").strip()
            if raw:
                step_summary_parts.append(raw)
            continue

        # 普通文本（Agent 自述）→ 也收入 step_summary
        if hasattr(part, "text") and part.text and not calls:
            step_summary_parts.append(part.text.strip())
            continue

        # function_call
        if hasattr(part, "function_call") and part.function_call:
            fc = part.function_call
            args = fc.args or {}
            # 优先使用工具参数中的 description（LLM 填写的操作目的）
            desc = (args.get("description") or "").strip()
            if not desc:
                reasoning = " ".join(step_summary_parts)
                if reasoning:
                    desc = reasoning
                elif fc.name == "run_skill_script":
                    skill = (args.get("skill_name") or args.get("name") or "").replace("-", " ")
                    desc = f"运行技能：{skill}" if skill else "执行技能脚本"
                elif fc.name == "todo":
                    todos = args.get("todos")
                    count = len(todos) if isinstance(todos, list) else 0
                    desc = f"规划 {count} 项任务" if count else "查询任务进度"
            calls.append({
                "id": fc.id or str(uuid.uuid4())[:8],
                "tool_name": fc.name,
                "display_name": _friendly_tool_name(fc.name),
                "args_summary": desc,
                "status": "running",
                "result_summary": None,
            })

        # function_response
        if hasattr(part, "function_response") and part.function_response:
            fr = part.function_response
            result_raw = fr.response or {}
            status = "error" if _is_error_result(result_raw) else "done"
            if fr.name == "todo":
                todos = result_raw.get("todos", [])
                result_str = json.dumps(todos, ensure_ascii=False)
            else:
                stdout = result_raw.get("stdout", b"")
                if isinstance(stdout, bytes):
                    stdout = stdout.decode("utf-8", errors="ignore")
                result_str = stdout[:10000]
            calls.append({
                "id": fr.id or str(uuid.uuid4())[:8],
                "tool_name": fr.name,
                "display_name": _friendly_tool_name(fr.name),
                "args_summary": "",
                "status": status,
                "result_summary": result_str,
            })

    if not calls:
        return None

    return {
        "step_summary": " ".join(step_summary_parts) or calls[0]["display_name"],
        "calls": calls,
    }


def _friendly_tool_name(raw: str) -> str:
    """把内部工具名转换为用户友好的中文显示名。"""
    mapping = {
        "arxiv_search": "arXiv 论文检索",
        "write_file": "写入文件",
        "read_file": "读取文件",
        "list_files": "列出文件",
        "execute_command": "执行命令",
        "load_skill": "加载技能",
        "web_search": "网络搜索",
        "generate_questionnaire": "生成问卷",
        "todo": "任务规划",
        "terminal": "终端命令",
        "execute_code": "运行代码",
        "vision_analyze": "图片分析",
        "clarify": "请求澄清",
        "run_skill_script": "执行技能脚本",
        "list_skills": "查看可用技能",
        "load_skill_resource": "加载参考资料",
        "generate_ppt": "生成 PPT",
        "save_to_workspace": "保存到工作台",
        "sync_sandbox_to_workspace": "同步产物到工作台",
    }
    return mapping.get(raw, raw)


def _tool_description(tool_name: str) -> str:
    """从 TOOL_LABELS 获取工具的人类可读描述。"""
    info = TOOL_LABELS.get(tool_name)
    if info:
        return info.get("detail", "")
    return _friendly_tool_name(tool_name)


def _is_error_result(result: dict) -> bool:
    if not isinstance(result, dict):
        return False
    return (
        result.get("error")
        or result.get("status") == "error"
        or "Error" in str(result.get("output", ""))
    )


# DeepSeek 思考 token 会在 CJK 字符间插入空格（如 "用 户 想 对 比"），
# 此函数去除 CJK 汉字之间的多余空格，保留中英文之间的自然间隔。
_CJK_IDEOGRAPHS = (
    r"\u4e00-\u9fff"       # CJK 统一汉字（基本区，覆盖 99%+ 常用字）
    r"\u3400-\u4dbf"       # CJK 扩展 A
    r"\uf900-\ufaff"       # CJK 兼容汉字
)
_CJK_RE = re.compile(rf"([{_CJK_IDEOGRAPHS}])\s+([{_CJK_IDEOGRAPHS}])")


def _fix_thought_spacing(text: str) -> str:
    """修复 DeepSeek thinking tokens 中 CJK 字符间的多余空格。"""
    prev = ""
    while prev != text:
        prev = text
        text = _CJK_RE.sub(r"\1\2", text)
    return text


# ---------------------------------------------------------------------------
# 文件辅助
# ---------------------------------------------------------------------------
#TODO:修改为从沙盒获取？
def _get_uploaded_files_info(user_id: str) -> list[dict]:
    user_dir = UPLOADS_DIR / user_id
    if not user_dir.exists():
        return []
    files = [
        {
            "name": f.name,
            "size": f.stat().st_size,
            "path": str(f.absolute()),
            "modified": f.stat().st_mtime,
        }
        for f in user_dir.iterdir() if f.is_file()
    ]
    return sorted(files, key=lambda x: x["modified"], reverse=True)


def _build_message_with_files(message: str, user_id: str) -> str:
    files = _get_uploaded_files_info(user_id)
    if not files:
        return message
    parts = [message, "", "---",
             "[系统提示] 以下是你可用的已上传文件（已包含位置标记，引用时必须注明文件名和位置）："]
    for f_info in files:
        fpath = Path(f_info["path"])
        content = read_file(fpath)
        parts.append(f"\n### 文件: {f_info['name']}\n大小: {f_info['size']} bytes\n内容:\n{content}")
    parts.append(
        "\n## 引用规则（重要）\n"
        "- 回答中引用上传文件内容时，必须注明文件名和页码/幻灯片号。\n"
        "- PDF: `（来源: xxx.pdf 第X页）` | PPT: `（来源: xxx.pptx 幻灯片X）` | 文本: `（来源: xxx.txt）`\n"
    )
    return "\n".join(parts)


async def _get_current_cards(user_id: str, session_id: str) -> list[dict]:
    try:
        sess = await session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id
        )
        if sess and sess.state:
            return get_narrator_cards(sess.state)
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------
#TODO:修改为上传到模型沙盒？？？
@app.post("/upload")
async def upload_file(file: UploadFile = File(...), user_id: str = Form(default="default_user")):
    user_dir = UPLOADS_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    safe_name = file.filename or "unnamed"
    dest_path = user_dir / safe_name
    if dest_path.exists():
        stem, suffix = os.path.splitext(safe_name)
        counter = 1
        while dest_path.exists():
            dest_path = user_dir / f"{stem}_{counter}{suffix}"
            counter += 1
    content = await file.read()
    dest_path.write_bytes(content)
    return JSONResponse({"success": True, "filename": dest_path.name, "size": len(content)})


@app.get("/uploads")
async def list_uploads(user_id: str = "default_user"):
    return JSONResponse({"user_id": user_id, "files": _get_uploaded_files_info(user_id)})


@app.get("/download")
async def download_file(user_id: str = "default_user", file: str = ""):
    """下载用户目录下的产物文件（如生成的 .pptx）。仅限 uploads/<user_id>/ 内。"""
    user_dir = (UPLOADS_DIR / user_id).resolve()
    target = (user_dir / os.path.basename(file)).resolve()
    if not str(target).startswith(str(user_dir)) or not target.is_file():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(str(target), filename=target.name)


@app.delete("/uploads")
async def clear_uploads(user_id: str = "default_user"):
    import shutil
    user_dir = UPLOADS_DIR / user_id
    if user_dir.exists():
        shutil.rmtree(user_dir)
        user_dir.mkdir(parents=True, exist_ok=True)
    return JSONResponse({"success": True})


# ---------------------------------------------------------------------------
# 文件工作台 API — 以 uploads/<user_id>/ 为用户的文档空间（产物、上传件都在这）
# 供文件树、Excalidraw、ONLYOFFICE 网关共用。
# ponytail: 用户文档空间 = 本地 uploads/<user_id>/（现有产物/下载都在这），
#           沙箱仍是代码执行环境；需要时用 agent 的 sync_upload_to_sandbox 打通。
# ---------------------------------------------------------------------------

def _safe_user_path(user_id: str, rel: str) -> Path:
    """把用户相对路径解析为 uploads/<user_id>/ 内的绝对路径，越权则抛 ValueError。"""
    root = (UPLOADS_DIR / user_id).resolve()
    target = (root / rel.lstrip("/")).resolve()
    if target != root and not str(target).startswith(str(root) + os.sep):
        raise ValueError("越权路径")
    return target


def _build_tree(base: Path, root: Path) -> list[dict]:
    nodes = []
    for p in sorted(base.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        st = p.stat()
        node = {
            "name": p.name,
            "path": str(p.relative_to(root)),
            "type": "directory" if p.is_dir() else "file",
            "size": st.st_size,
            "modified": st.st_mtime,
        }
        if p.is_dir():
            node["children"] = _build_tree(p, root)
        nodes.append(node)
    return nodes


@app.get("/files/tree")
async def files_tree(user_id: str = "default_user"):
    """列出用户文档空间的完整文件树。"""
    root = UPLOADS_DIR / user_id
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve()
    return JSONResponse({"user_id": user_id, "tree": _build_tree(root, root)})


@app.get("/files/raw")
async def files_raw_get(user_id: str = "default_user", path: str = ""):
    """读取单个文件原始内容（Excalidraw 加载 / 预览 / ONLYOFFICE 下载共用）。"""
    if not path:
        return JSONResponse({"error": "缺少 path"}, status_code=400)
    try:
        target = _safe_user_path(user_id, path)
    except ValueError:
        return JSONResponse({"error": "非法路径"}, status_code=400)
    if not target.is_file():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(str(target), filename=target.name)


class WriteFileRequest(BaseModel):
    path: str
    content: str
    user_id: str = "default_user"


@app.put("/files/raw")
async def files_raw_put(req: WriteFileRequest):
    """写入文本文件（Excalidraw 保存 / 新建文件）。"""
    if not req.path:
        return JSONResponse({"error": "缺少 path"}, status_code=400)
    try:
        target = _safe_user_path(req.user_id, req.path)
    except ValueError:
        return JSONResponse({"error": "非法路径"}, status_code=400)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")
    return JSONResponse({"success": True, "path": req.path, "size": len(req.content)})


@app.delete("/files")
async def files_delete(user_id: str = "default_user", path: str = ""):
    """删除文件或目录。"""
    import shutil
    if not path:
        return JSONResponse({"error": "缺少 path"}, status_code=400)
    try:
        target = _safe_user_path(user_id, path)
    except ValueError:
        return JSONResponse({"error": "非法路径"}, status_code=400)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.is_file():
        target.unlink()
    else:
        return JSONResponse({"error": "不存在"}, status_code=404)
    return JSONResponse({"success": True})


# ---------------------------------------------------------------------------
# ONLYOFFICE 网关 — DocumentServer 通过 URL 拉取/回写文件，后端当文件网关。
# JWT 是安全边界：config 后端签发，callback 后端验签。密钥只在后端。
# ---------------------------------------------------------------------------
import jwt as _pyjwt

OFFICE_SECRET = os.environ.get("OFFICE_JWT_SECRET", "")
# 浏览器访问 DocumentServer 的地址（加载 api.js）；OpenSandbox 占用 8080，故默认 8081
OFFICE_DOCSERVER_URL = os.environ.get("OFFICE_DOCSERVER_URL", "http://localhost:8081")
# DocumentServer 容器回访本后端的地址（download/callback）——不能用 localhost（那是容器自己）
OFFICE_BACKEND_URL = os.environ.get("OFFICE_BACKEND_URL", "http://host.docker.internal:8585")

# 文件后缀 → ONLYOFFICE documentType
_OFFICE_TYPES = {
    "docx": "word", "doc": "word", "odt": "word", "rtf": "word", "txt": "word",
    "xlsx": "cell", "xls": "cell", "ods": "cell", "csv": "cell",
    "pptx": "slide", "ppt": "slide", "odp": "slide",
    "pdf": "pdf",
}


def _office_sign(payload: dict) -> str:
    return _pyjwt.encode(payload, OFFICE_SECRET, algorithm="HS256")


def _office_verify(token: str) -> dict:
    return _pyjwt.decode(token, OFFICE_SECRET, algorithms=["HS256"])


@app.get("/office/config")
async def office_config(path: str = "", user_id: str = "default_user"):
    """签发 DocEditor 配置（含签名 token + 供浏览器加载 api.js 的 docserver 地址）。"""
    if not OFFICE_SECRET:
        return JSONResponse({"error": "未配置 OFFICE_JWT_SECRET，无法在线编辑"}, status_code=503)
    if not path:
        return JSONResponse({"error": "缺少 path"}, status_code=400)
    try:
        target = _safe_user_path(user_id, path)
    except ValueError:
        return JSONResponse({"error": "非法路径"}, status_code=400)
    if not target.is_file():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    ext = target.suffix.lower().lstrip(".")
    doc_type = _OFFICE_TYPES.get(ext)
    if not doc_type:
        return JSONResponse({"error": f"不支持在线编辑的类型: .{ext}"}, status_code=400)

    # key 绑定内容版本：mtime 变则 key 变，避免编辑器显示缓存旧内容
    key = hashlib.md5(f"{user_id}:{path}:{target.stat().st_mtime}".encode()).hexdigest()
    # download/callback 用短期 JWT 绑定 path+user，DocServer 凭此回访
    file_token = _office_sign({
        "path": path, "user_id": user_id, "exp": int(time.time()) + 24 * 3600,
    })
    config = {
        "document": {
            "fileType": ext,
            "key": key,
            "title": target.name,
            "url": f"{OFFICE_BACKEND_URL}/office/download?token={file_token}",
        },
        "documentType": doc_type,
        "editorConfig": {
            "mode": "edit",
            "lang": "zh-CN",
            "callbackUrl": f"{OFFICE_BACKEND_URL}/office/callback?token={file_token}",
            # 让后台轮询插件(poll.js)读到 user_id，才能拉对信箱（读不到退回 default_user）
            "user": {"id": user_id, "name": user_id},
            # 让「AI 桥」后台常驻插件开编辑器就自动跑轮询（无需手动开面板）——P6.3 broker 桥的轮询端。
            # 注意：autostart 与工具栏按钮都启动 variations[0]，所以后台插件必须与可视「AI 改写」拆成两个插件。
            "plugins": {"autostart": ["asc.b2c3d4e5-ai-bridge-poll-0001"]},
        },
    }
    config["token"] = _office_sign(config)  # 整个 config 签名，DocServer 校验
    return JSONResponse({"config": config, "docserverUrl": OFFICE_DOCSERVER_URL})


@app.get("/office/download")
async def office_download(token: str = ""):
    """DocumentServer 拉取原始文件：验签 token → 返回文件字节流。"""
    try:
        claims = _office_verify(token)
    except Exception:
        return JSONResponse({"error": "invalid token"}, status_code=403)
    try:
        target = _safe_user_path(claims["user_id"], claims["path"])
    except (ValueError, KeyError):
        return JSONResponse({"error": "非法路径"}, status_code=400)
    if not target.is_file():
        return JSONResponse({"error": "文件不存在"}, status_code=404)
    return FileResponse(str(target), filename=target.name)


@app.post("/office/callback")
async def office_callback(request: Request, token: str = ""):
    """DocumentServer 保存回调：验签 → status 2/6 时下载编辑后文件写回。"""
    try:
        claims = _office_verify(token)
    except Exception:
        return JSONResponse({"error": 1}, status_code=403)
    body = await request.json()
    # JWT_ENABLED 时回调体带 token（DocServer 对 body 的签名），验证来源真实性
    inner = body.get("token")
    if inner:
        try:
            _office_verify(inner)
        except Exception:
            return JSONResponse({"error": 1}, status_code=403)

    status = body.get("status")
    # 2=MustSave（编辑结束需保存）, 6=ForceSave（强制保存）
    if status in (2, 6):
        edited_url = body.get("url")
        if edited_url:
            import httpx
            try:
                async with httpx.AsyncClient() as client:
                    r = await client.get(edited_url, timeout=60)
                    r.raise_for_status()
                target = _safe_user_path(claims["user_id"], claims["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(r.content)
                logger.info("ONLYOFFICE 保存回写: %s (%d bytes)", claims["path"], len(r.content))
            except Exception as e:
                logger.error("ONLYOFFICE 回写失败: %s", e)
                return JSONResponse({"error": 1})
    return JSONResponse({"error": 0})


class OfficeEditIn(BaseModel):
    text: str = ""          # 当前选区文本（无选区时为空，做全文级操作）
    instruction: str
    doc_type: str = "slide"  # word / cell / slide，供 LLM 判断可用操作


@app.post("/office/edit")
async def office_edit(body: OfficeEditIn):
    """ONLYOFFICE 插件的编辑意图解析：收选区文本+指令 → LLM 产【结构化 op】→ 插件在编辑器里执行。

    见 docs/plan.md §4：AI 不改文件，只产"要在编辑器里做的操作"，回写由插件 Builder API 在 live 会话里完成。
    """
    from app.office_ops import SYSTEM_PROMPT, parse_office_op

    text = (body.text or "").strip()
    instruction = (body.instruction or "").strip()
    if not instruction:
        return JSONResponse({"error": "缺少 instruction"}, status_code=400)

    import litellm
    from app.agent import MODEL_PROVIDER, MODEL_NAME
    model = MODEL_NAME if "/" in MODEL_NAME else f"{MODEL_PROVIDER}/{MODEL_NAME}"
    user_msg = f"文档类型：{body.doc_type}\n选中文本：{text or '（无）'}\n指令：{instruction}"
    try:
        resp = await litellm.acompletion(
            model=model,
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
        )
        raw = resp["choices"][0]["message"]["content"].strip()
        op = parse_office_op(raw)
    except Exception as e:
        logger.error("office_edit 解析失败: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"op": op})


@app.get("/office/pending")
async def office_pending_poll(user_id: str = "default_user"):
    """编辑器后台插件轮询：取走并清空该用户待执行的 op（助手侧栏经 agent 投递的）。

    P6.3 broker 桥：助手侧栏跨 iframe 够不到编辑器插件（社区版无 Connector），
    改由 agent 把 op 投进后端信箱、插件在编辑器里轮询取走，用 callCommand 在 live 会话落地。
    """
    from app.office_ops import drain_ops
    return JSONResponse({"ops": drain_ops(user_id)})


# ---------------------------------------------------------------------------
# SSE 缓存管理接口
# ---------------------------------------------------------------------------
@app.get("/cache/info")
async def cache_info():
    """查看 SSE 缓存状态。"""
    return JSONResponse(_sse_cache.info())


@app.delete("/cache")
async def cache_clear():
    """清空 SSE 缓存。"""
    count = _sse_cache.clear()
    return JSONResponse({"success": True, "cleared": count})


# ---------------------------------------------------------------------------
# POST /chat — 非流式完整响应
# ---------------------------------------------------------------------------
@app.post("/chat")
async def chat(req: ChatRequest):
    session = await session_service.create_session(
        user_id=req.user_id, app_name=APP_NAME, state={"_sbkey": req.user_id}
    )
    full_message = _build_message_with_files(req.message, req.user_id)
    message = types.Content(role="user", parts=[types.Part.from_text(text=full_message)])
    slog = SessionLogger(session.id, req.user_id, req.message)

    full_response: list[str] = []
    thoughts: list[dict] = []
    tool_steps: list[dict] = []

    try:
        async for event in runner.run_async(
            new_message=message,
            user_id=req.user_id,
            session_id=session.id,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
            if not event.content or not event.content.parts:
                continue
            if getattr(event, "partial", True) is False:
                continue

            tool_info = _extract_tool_info(event)
            if tool_info:
                tool_steps.append(tool_info)
                slog.log_event({"type": "tool_step", **tool_info})
                continue

            for part in event.content.parts:
                if hasattr(part, "thought") and part.thought:
                    raw = (part.text or "")
                    if raw.strip():
                        t = {"raw": raw, "narrated": _explain_thinking(raw.strip())}
                        thoughts.append(t)
                        slog.log_event({"type": "thought", **t})
                    continue
                if hasattr(part, "text") and part.text:
                    full_response.append(part.text)
                    slog.log_event({"type": "text", "text": part.text})

        cards = await _get_current_cards(req.user_id, session.id)
        for i, card in enumerate(cards):
            slog.log_event({"type": "narrator_card", "card": card, "card_index": i})

        slog.log_event({
            "type": "done",
            "text_len": sum(len(t) for t in full_response),
            "thought_count": len(thoughts),
            "step_count": len(tool_steps),
            "card_count": len(cards),
        })

        return {
            "response": "".join(full_response),
            "thoughts": thoughts,
            "tool_steps": tool_steps,
            "narrator_cards": cards,
        }
    except Exception as e:
        slog.log_error(str(e))
        raise
    finally:
        slog.close()


# ---------------------------------------------------------------------------
# 核心流式执行 — 被 /chat/stream 与 /chat/answer 复用
# ---------------------------------------------------------------------------
async def _run_agent_stream(session_id: str, user_id: str, new_message, emit, state: dict):
    """运行一次 Agent 并以 SSE 帧产出过程事件。

    参数:
      emit(evt_dict) -> sse_frame: 调用方提供，负责收集/记录事件并格式化为 SSE 帧。
      state: 可变 dict，用于回传标志位（如 state["clarify"]=True 表示触发了澄清提问，
             调用方据此跳过缓存）。

    clarify（人在回路）处理:
      检测到 clarify 工具的 function_call 时，发出一个 "clarify" 事件
      （含 session_id / call_id / question / choices）并结束本轮；用户回答后由
      /chat/answer 以 function_response 回灌同一 session 续跑。
    """
    last_card_count = 0
    last_card_check = 0.0
    thought_count = 0
    step_count = 0
    text_len = 0

    pending_calls: dict[str, str] = {}   # call_id → step_id
    pending_code: dict[str, str] = {}    # code 块 id → step_id
    emitted_code_ids: set[str] = set()

    async for event in runner.run_async(
        new_message=new_message,
        user_id=user_id,
        session_id=session_id,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        if not event.content or not event.content.parts:
            continue
        if getattr(event, "partial", True) is False and not event.get_function_calls():
            continue

        # ---- clarify 优先检测（人在回路）----
        clarify_fc = None
        for p in event.content.parts:
            fc = getattr(p, "function_call", None)
            if fc:
                print('function calling')
            if fc and fc.name == "clarify":
                clarify_fc = fc
                break
        if clarify_fc is not None:
            args = clarify_fc.args or {}
            state["clarify"] = True
            yield emit({
                "type": "clarify",
                "session_id": session_id,
                "call_id": clarify_fc.id or "",
                "question": args.get("question", ""),
                "choices": list(args.get("choices") or []),
            })
            continue
        # clarify 的 pending function_response 占位，不渲染成工具卡片
        if any(
            getattr(p, "function_response", None) and p.function_response.name == "clarify"
            for p in event.content.parts
        ):
            continue

        # ---- 工具调用事件 ----
        has_fc = any(
            hasattr(p, "function_call") and p.function_call
            or hasattr(p, "function_response") and p.function_response
            for p in event.content.parts
        )
        if has_fc:
            step_id = f"step_{step_count}"
            calls_out = []
            summary_parts = []

            for part in event.content.parts:
                if hasattr(part, "thought") and part.thought:
                    summary_parts.append((part.text or "").strip())
                elif hasattr(part, "text") and part.text:
                    summary_parts.append(part.text.strip())
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    cid = fc.id or str(uuid.uuid4())[:8]
                    args = fc.args or {}
                    # 优先使用工具参数中的 description（LLM 填写的操作目的）
                    desc = (args.get("description") or "").strip()
                    if not desc:
                        reasoning = " ".join(summary_parts)
                        if reasoning:
                            desc = reasoning
                        elif fc.name == "run_skill_script":
                            skill = (args.get("skill_name") or args.get("name") or "").replace("-", " ")
                            desc = f"运行技能：{skill}" if skill else "执行技能脚本"
                        elif fc.name == "todo":
                            todos = args.get("todos")
                            count = len(todos) if isinstance(todos, list) else 0
                            desc = f"规划 {count} 项任务" if count else "查询任务进度"
                    call_entry = {
                        "id": cid,
                        "tool_name": fc.name,
                        "display_name": _friendly_tool_name(fc.name),
                        "args_summary": desc,
                        "status": "running",
                        "result_summary": None,
                    }
                    calls_out.append(call_entry)
                    pending_calls[cid] = step_id
                elif hasattr(part, "function_response") and part.function_response:
                    fr = part.function_response
                    rid = fr.id or ""
                    result_raw = fr.response or {}
                    status = "error" if _is_error_result(result_raw) else "done"

                    # todo 工具：传递结构化数据让前端渲染待办列表
                    if fr.name == "todo":
                        todos = result_raw.get("todos", [])
                        result_str = json.dumps(todos, ensure_ascii=False)
                    else:
                        # 普通工具：纯文本截断
                        stdout = result_raw.get("stdout", b"")
                        if isinstance(stdout, bytes):
                            stdout = stdout.decode("utf-8", errors="ignore")
                        result_str = stdout[:10000]

                    call_entry = {
                        "id": rid,
                        "tool_name": fr.name,
                        "display_name": _friendly_tool_name(fr.name),
                        "args_summary": "",
                        "status": status,
                        "result_summary": result_str,
                    }
                    calls_out.append(call_entry)
                    if rid in pending_calls:
                        yield emit({
                            "type": "tool_call",
                            "step_id": pending_calls[rid],
                            "call_id": rid,
                            "status": status,
                            "result_summary": result_str,
                        })
                        del pending_calls[rid]

            if calls_out:
                #TODO：需要把 calls_out参数换掉
                summary = " ".join(summary_parts) or _friendly_tool_name(calls_out[0]["tool_name"])
                yield emit({
                    "type": "tool_step",
                    "step_id": step_id,
                    "summary": summary,
                    "call_count": len(calls_out),
                    "calls": calls_out,
                })
                step_count += 1
            continue

        # ---- 代码执行事件（ADK 内置 code executor）----
        has_code = any(
            getattr(p, "executable_code", None) or getattr(p, "code_execution_result", None)
            for p in event.content.parts
        )
        if has_code:
            for part in event.content.parts:
                ec = getattr(part, "executable_code", None)
                if ec and getattr(ec, "code", None):
                    cid = ec.id or f"code_{step_count}"
                    if cid in emitted_code_ids:
                        continue
                    emitted_code_ids.add(cid)
                    step_id = f"step_{step_count}"
                    yield emit({
                        "type": "tool_step",
                        "step_id": step_id,
                        "summary": "运行代码",
                        "call_count": 1,
                        "calls": [{
                            "id": cid,
                            "tool_name": "execute_code",
                            "display_name": "运行代码",
                            "args_summary": f"Python 代码 ({len(ec.code or '')} 字符)",
                            "status": "running",
                            "result_summary": None,
                        }],
                    })
                    pending_code[cid] = step_id
                    step_count += 1

                cer = getattr(part, "code_execution_result", None)
                if cer is not None:
                    rid = cer.id or ""
                    outcome = str(getattr(cer, "outcome", "") or "").upper()
                    output = getattr(cer, "output", "") or ""
                    status = "error" if ("FAIL" in outcome or "ERROR" in outcome) else "done"
                    step_id = pending_code.pop(rid, None)
                    if step_id is None and pending_code:
                        rid, step_id = pending_code.popitem()
                    if step_id:
                        yield emit({
                            "type": "tool_call",
                            "step_id": step_id,
                            "call_id": rid,
                            "status": status,
                            "result_summary": output[:4000],
                        })
            continue

        # ---- 思考 / 正文 ----
        for part in event.content.parts:
            if hasattr(part, "thought") and part.thought:
                raw_text = part.text or ""
                if raw_text.strip():
                    thought_count += 1
                    yield emit({
                        "type": "thought",
                        "raw": raw_text,
                        "narrated": _explain_thinking(raw_text.strip()),
                    })
                continue
            if hasattr(part, "text") and part.text:
                text_len += len(part.text)
                yield emit({"type": "text", "text": part.text})

        # ---- 解说卡片增量推送 ----
        now = time.time()
        if now - last_card_check >= 0.2:
            current_cards = await _get_current_cards(user_id, session_id)
            last_card_check = now
            while last_card_count < len(current_cards):
                yield emit({
                    "type": "narrator_card",
                    "card": current_cards[last_card_count],
                    "card_index": last_card_count,
                })
                last_card_count += 1

    # ---- 最终卡片 & done ----
    final_cards = await _get_current_cards(user_id, session_id)
    while last_card_count < len(final_cards):
        yield emit({"type": "narrator_card", "card": final_cards[last_card_count], "card_index": last_card_count})
        last_card_count += 1

    yield emit({
        "type": "done",
        "text_len": text_len,
        "thought_count": thought_count,
        "step_count": step_count,
        "card_count": len(final_cards),
    })


# ---------------------------------------------------------------------------
# GET /chat/stream — SSE 流式（协议 v2）
# ---------------------------------------------------------------------------
@app.get("/chat/stream")
async def chat_stream(message: str, user_id: str = "default_user"):
    """
    SSE 事件协议 v2（含响应缓存）：

    | type          | 关键字段                                      | 前端用途                  |
    |---------------|----------------------------------------------|--------------------------|
    | text          | text (str)                                   | 打字机追加正文             |
    | thought       | raw, narrated (str)                          | 可折叠思考卡片             |
    | tool_step     | step_id, summary, calls[]                    | 新增工具步骤卡片           |
    | tool_call     | step_id, call_id, status, result_summary     | 更新子调用状态             |
    | narrator_card | card, card_index                             | 解说卡片（旧兼容）         |
    | done          | text_len, thought_count, step_count          | 标记流结束                 |

    缓存逻辑：对相同 full_message（含文件内容）的请求直接回放已缓存的事件流，跳过 LLM 调用。
    """
    session = await session_service.create_session(
        user_id=user_id, app_name=APP_NAME, state={"_sbkey": user_id}
    )
    full_message = _build_message_with_files(message, user_id)

    # 检查缓存命中 → 快速回放缓存事件，跳过 LLM 调用
    cached_events = _sse_cache.get(full_message)
    if cached_events is not None:
        #缓存命中的情况
        logger.info("SSE cache HIT: %.60s...", message)
        slog = SessionLogger(session.id, user_id, message)
        slog.log_event({"type": "cache_hit", "cached_event_count": len(cached_events)})

        async def replay_generator():
            try:
                for evt in cached_events:
                    slog.log_event(evt)
                    yield _sse(evt)
                    await asyncio.sleep(0.01)  # 小幅延迟，避免瞬间洪泛前端
            except Exception as e:
                slog.log_error(str(e))
            finally:
                slog.close()

        return StreamingResponse(
            replay_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    logger.info("SSE cache MISS: %.60s...", message)
    collected_events: list[dict] = []  # 缓存未命中，收集事件以便结束后写入缓存
    slog = SessionLogger(session.id, user_id, message)

    state: dict = {}

    def emit(evt_data: dict):
        """收集事件到缓存、写入日志并返回 SSE 帧。"""
        collected_events.append(evt_data)
        slog.log_event(evt_data)
        return _sse(evt_data)

    async def event_generator():
        msg = types.Content(role="user", parts=[types.Part.from_text(text=full_message)])

        async for frame in _run_agent_stream(session.id, user_id, msg, emit, state):
            yield frame

        # 触发了 clarify（人在回路）时不写缓存——回放无法续接用户的真实回答。
        if collected_events and not state.get("clarify"):
            _sse_cache.set(full_message, collected_events)
            logger.info("SSE cache SET (%d events): %.60s...", len(collected_events), message)

        # 关闭 session 日志
        slog.close()

    async def safe_event_generator():
        """包装 event_generator，确保异常时也能关闭日志。"""
        try:
            async for frame in event_generator():
                yield frame
        except Exception as e:
            logger.error("Stream error: %s", e, exc_info=True)
            slog.log_error(str(e))
            slog.close()
            raise

    return StreamingResponse(
        safe_event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


class StreamRequest(BaseModel):
    message: str
    user_id: str = "default_user"


@app.post("/chat/stream")
async def chat_stream_post(req: StreamRequest):
    """POST 变体：message 走请求体，避免大内容（如白板完整 JSON）塞进 URL 撑爆请求头触发 431。协议同 GET。"""
    return await chat_stream(req.message, req.user_id)


class AnswerRequest(BaseModel):
    session_id: str
    call_id: str
    answer: str
    user_id: str = "default_user"


# ---------------------------------------------------------------------------
# POST /chat/answer — 续接 clarify（人在回路）
# ---------------------------------------------------------------------------
@app.post("/chat/answer")
async def chat_answer(req: AnswerRequest):
    """用户回答 clarify 提问后续跑同一 session。

    把回答封装为 clarify 工具的 function_response 回灌同一 session_id，
    Agent 据此恢复执行，继续以 SSE 输出后续过程（协议同 /chat/stream）。
    不写缓存：每次澄清回答都是一次性的人在回路交互。
    """
    msg = types.Content(
        role="user",
        parts=[types.Part(function_response=types.FunctionResponse(
            id=req.call_id,
            name="clarify",
            response={"user_response": req.answer},
        ))],
    )

    slog = SessionLogger(req.session_id, req.user_id, f"[clarify answer] {req.answer}")
    state: dict = {}

    def emit(evt_data: dict):
        slog.log_event(evt_data)
        return _sse(evt_data)

    async def event_generator():
        async for frame in _run_agent_stream(req.session_id, req.user_id, msg, emit, state):
            yield frame
        slog.close()

    async def safe_event_generator():
        try:
            async for frame in event_generator():
                yield frame
        except Exception as e:
            logger.error("Answer stream error: %s", e, exc_info=True)
            slog.log_error(str(e))
            slog.close()
            raise

    return StreamingResponse(
        safe_event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8585)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
