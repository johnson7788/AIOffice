"""
Narrator rules: tool labels, thinking patterns, and constants.

Extracted from narrator.py so that rule definitions are separate from
callback logic and formatting helpers.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Session state key for storing narrator cards
# ---------------------------------------------------------------------------
NARRATOR_STATE_KEY = "_narrator_cards"

# ---------------------------------------------------------------------------
# Tool name → user-friendly label mapping
# ---------------------------------------------------------------------------
TOOL_LABELS: dict[str, dict[str, str]] = {
    # Skill 管理工具
    "list_skills": {
        "label": "查看研究技能",
        "icon": "📋",
        "detail": "查看可用的论文检索和分析技能",
    },
    "load_skill": {
        "label": "加载技能指导",
        "icon": "📖",
        "detail": "读取论文检索技能的详细分步指导",
    },
    "load_skill_resource": {
        "label": "加载参考资料",
        "icon": "📚",
        "detail": "查阅参考文档，确保检索策略和论文评估质量",
    },
    # Shell 执行工具
    "run_shell": {
        "label": "执行检索脚本",
        "icon": "🖥️",
        "detail": "运行论文检索脚本，获取检索结果",
    },
    "list_uploaded_files": {
        "label": "查看上传文件",
        "icon": "📁",
        "detail": "查看用户已上传的文件列表",
    },
    "read_file": {
        "label": "读取文件内容",
        "icon": "📄",
        "detail": "读取用户上传的文件，提取文本内容进行分析",
    },
    # 论文检索工具
    "arxiv_search": {
        "label": "检索学术论文",
        "icon": "🔬",
        "detail": "通过 arXiv API 检索相关方向的学术论文",
    },
    # 通用搜索工具
    "search": {
        "label": "互联网搜索",
        "icon": "🌐",
        "detail": "通过搜索引擎查找博客解读、代码仓库、技术新闻等非论文信息",
    },
    # 任务规划与执行工具
    "todo": {
        "label": "规划任务清单",
        "icon": "🗂️",
        "detail": "拆解并跟踪本次研究任务的执行步骤",
    },
    "terminal": {
        "label": "执行终端命令",
        "icon": "⌨️",
        "detail": "在服务器上运行命令并读取输出",
    },
    "execute_code": {
        "label": "运行代码",
        "icon": "🐍",
        "detail": "编写并执行 Python 代码处理数据或计算",
    },
    "vision_analyze": {
        "label": "分析图片",
        "icon": "🖼️",
        "detail": "识别图片内容或提取图中文字（OCR）",
    },
    "clarify": {
        "label": "请求澄清",
        "icon": "❓",
        "detail": "向你确认关键信息，以便给出更准确的结果",
    },
    # 技能执行工具
    "run_skill_script": {
        "label": "执行技能脚本",
        "icon": "🖥️",
        "detail": "执行论文检索或网页搜索的技能脚本",
    },
    # 通用 fallback 模式
    "_search": {
        "label": "搜索信息",
        "icon": "🔍",
        "detail": "查找相关资料和信息",
    },
    "_load": {
        "label": "加载数据",
        "icon": "📂",
        "detail": "获取所需的数据和资源",
    },
    "_generate": {
        "label": "生成报告",
        "icon": "📝",
        "detail": "基于分析结果生成结构化研究综述",
    },
    "_validate": {
        "label": "验证结果",
        "icon": "✅",
        "detail": "检查论文质量和分析结论的可靠性",
    },
    "_save": {
        "label": "保存结果",
        "icon": "💾",
        "detail": "保存检索和分析结果",
    },
    "_analyze": {
        "label": "分析数据",
        "icon": "📊",
        "detail": "分析论文数据，提取研究关键信息",
    },
}

# ---------------------------------------------------------------------------
# Thinking → explanation mapping (pattern-based)
# ---------------------------------------------------------------------------
THINKING_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)step\s*\d|第\s*\d+\s*步", "按照研究分析方法论，逐步推进分析"),
    (r"(?i)need to (check|verify|confirm)|需要(检查|验证|确认)", "核对论文信息，确保后续分析的准确性"),
    (r"(?i)let me (think|consider|analyze)|让我(想想|考虑|分析)", "仔细分析论文内容，确保结论严谨"),
    (r"(?i)first.{0,20}(load|read|fetch|get|search)|首先(加载|读取|获取|搜索)", "先检索相关论文，收集必要的研究证据"),
    (r"(?i)summarize|synthesize|combine|总结|归纳|整合", "整合多篇论文的观点，形成综合结论"),
    (r"(?i)edge case|corner case|boundary|边缘|极端|边界", "考虑特殊情况和边界条件，确保结论的适用性"),
    (r"(?i)confident|confidence|unsure|verify|置信|确定|验证", "评估证据质量和结论可信度"),
    (r"(?i)compare|cross.reference|validate against|对比|交叉验证", "交叉对比不同论文的方法与结果，确保准确性"),
    (r"(?i)conclusion|finally|in summary|overall|结论|总结|最终", "基于检索到的研究得出最终结论"),
    (r"(?i)search|检索|搜索", "根据研究问题制定检索策略"),
    (r"(?i)baseline|benchmark|基线|基准", "梳理基线方法与评测基准"),
    (r"(?i)result|metric|performance|结果|指标|性能", "分析主要实验结果与评测指标"),
]
