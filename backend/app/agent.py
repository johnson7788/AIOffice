"""
学术论文研究智能体 — 基于技能 + 旁路解说者架构

该智能体提供学术论文检索、研究综述、方向追踪等能力，并以旁路解说的
方式实时向用户展示工作过程。

架构：
- MAIN agent: 运行论文检索和分析技能（多步骤、深度思考）
- NARRATOR layer (callbacks): 拦截工具调用、思考过程和结果，
  翻译为普通用户可理解的解说卡片
- 解说卡片存储在 session state 中，可随主输出一起展示

技能：
  1. arxiv-paper-search — arXiv 学术论文检索
     支持按相关性/最新提交并行检索、按分类/作者检索、
     自由检索表达式
  2. bingsearch — 互联网通用搜索（Bing 搜索）
     支持通用、新闻、图片、视频搜索，可指定语言和搜索引擎
"""

from __future__ import annotations

import base64
import os
import pathlib

from dotenv import load_dotenv
from google.adk import Agent
from google.adk.code_executors import UnsafeLocalCodeExecutor
from google.adk.code_executors.base_code_executor import BaseCodeExecutor
from google.adk.code_executors.code_execution_utils import (
    CodeExecutionInput,
    CodeExecutionResult,
)
from google.adk.skills import load_skill_from_dir
from google.adk.tools import FunctionTool
from google.adk.tools.skill_toolset import SkillToolset

from app import sandbox as sbx
from app.create_model import create_model
from app.narrator import (
    after_model_callback,
    after_tool_callback,
    before_tool_callback,
)
from app.tools import (
    clarify_tool,
    enqueue_office_op,
    ensure_sandbox_skills,
    generate_ppt,
    save_to_workspace,
    sync_sandbox_to_workspace,
    sync_upload_to_sandbox,
    terminal,
    todo,
    upload_to_sandbox,
    vision_analyze,
)

load_dotenv()

# ---------------------------------------------------------------------------
# 目录常量
# ---------------------------------------------------------------------------
SKILLS_DIR = pathlib.Path(__file__).parent / "skills"
UPLOADS_DIR = pathlib.Path(__file__).parent.parent / "uploads"

# ---------------------------------------------------------------------------
# Instruction — 从 instruction.md 加载
# ---------------------------------------------------------------------------
_INSTRUCTION = (pathlib.Path(__file__).parent / "instruction.md").read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Skills — 学术论文检索 + 互联网搜索
# ---------------------------------------------------------------------------

# Skill 1: arXiv 学术论文检索 — arXiv 公开 API
arxiv_paper_search_skill = load_skill_from_dir(
    SKILLS_DIR / "arxiv-paper-search"
)

# Skill 2: 网页搜索 — Bing 搜索
bing_search_skill = load_skill_from_dir(
    SKILLS_DIR / "bingsearch"
)

# Skill 3: 图片型 PPT 生成 — qwen-image 逐页出图 + 组装 .pptx
ppt_deck_skill = load_skill_from_dir(
    SKILLS_DIR / "ppt-deck"
)

# Skill 4: 可编辑型 PPT 生成 — HTML 模板编排 + 可编辑 PPTX/PDF 导出
dashi_ppt_skill = load_skill_from_dir(
    SKILLS_DIR / "dashi-ppt"
)

# Skill 5: 思维导图 / 架构图 — 授权原生 .excalidraw JSON，落进工作台白板可编辑
excalidraw_diagram_skill = load_skill_from_dir(
    SKILLS_DIR / "excalidraw-diagram"
)

# ---------------------------------------------------------------------------
# SkillToolset — 自动生成 list_skills, load_skill, load_skill_resource, run_skill_script
# ---------------------------------------------------------------------------
skill_toolset = SkillToolset(
    skills=[
        arxiv_paper_search_skill,
        bing_search_skill,
        ppt_deck_skill,
        dashi_ppt_skill,
        excalidraw_diagram_skill,
    ]
)

# ---------------------------------------------------------------------------
# 模型 — 从 .env 读取 MODEL_PROVIDER 与 MODEL_NAME
# ---------------------------------------------------------------------------
MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER", "deepseek")
MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-v4-pro")

# ---------------------------------------------------------------------------
# 代码执行器 — 启用沙箱时，模型生成的 Python 也在租户沙箱里跑（否则本地执行）
# ---------------------------------------------------------------------------
class SandboxCodeExecutor(BaseCodeExecutor):
    """把模型生成的 Python 代码路由进租户独占沙箱执行。"""

    def execute_code(
        self,
        invocation_context,
        code_execution_input: CodeExecutionInput,
    ) -> CodeExecutionResult:
        state = getattr(invocation_context.session, "state", None) or {}
        key = str(state.get("_sbkey") or invocation_context.user_id or "default")
        # base64 传递源码，避开 shell 转义问题。ponytail: 依赖镜像里有 base64+python3
        # （python:3.x 官方镜像默认满足）；换精简镜像时改为写文件再执行。
        b64 = base64.b64encode(code_execution_input.code.encode()).decode()
        command = f"echo {b64} | base64 -d | python3"
        try:
            r = sbx.run_sync(key, command, self.timeout_seconds or 60)
        except Exception as e:  # noqa: BLE001 — 执行边界，回报给模型
            return CodeExecutionResult(stdout="", stderr=f"沙箱执行失败: {e}", output_files=[])
        return CodeExecutionResult(
            stdout=r.get("stdout", ""), stderr=r.get("stderr", ""), output_files=[]
        )


_code_executor = SandboxCodeExecutor() if sbx.enabled() else UnsafeLocalCodeExecutor()

# ---------------------------------------------------------------------------
# 学术论文研究智能体
# ---------------------------------------------------------------------------
root_agent = Agent(
    model=create_model(model=MODEL_NAME, provider=MODEL_PROVIDER),
    name="arxiv_research_agent",
    code_executor=_code_executor,
    description=(
        "学术论文研究智能体 — 提供 arXiv 论文检索、研究综述、"
        "方向追踪等服务，同时以旁路解说的方式"
        "实时向用户展示工作过程。"
    ),
    instruction=_INSTRUCTION,
    tools=[
        skill_toolset,
        FunctionTool(todo),
        FunctionTool(terminal),
        FunctionTool(vision_analyze),
        FunctionTool(generate_ppt),
        FunctionTool(save_to_workspace),
        FunctionTool(enqueue_office_op),
        FunctionTool(upload_to_sandbox),
        FunctionTool(sync_upload_to_sandbox),
        FunctionTool(sync_sandbox_to_workspace),
        # FunctionTool(ensure_sandbox_skills),
        clarify_tool,
    ],
    before_tool_callback=before_tool_callback,
    after_tool_callback=after_tool_callback,
    after_model_callback=after_model_callback,
)
