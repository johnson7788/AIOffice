---
name: arxiv-paper-search
description: arXiv 学术论文检索技能，通过 arXiv 官方公开 API 进行关键词检索，支持按相关性/最新提交并行检索、按分类（cs.CL、cs.LG 等）检索、按作者检索，以及自由检索表达式。支持字段标签和排序方式。适合查找特定主题的论文、追踪某方向最新进展、定位某作者工作，或使用高级检索表达式时触发此技能。
---

# arXiv Paper Search — arXiv 学术论文检索

## 概述

通过 arXiv 官方公开 API（http://export.arxiv.org/api/query）检索学术论文，免费、无需 token。支持多维度并行检索和高级检索表达式。

支持以下检索模式：

| 模式 | 命令 | 说明 |
|------|------|------|
| 并行检索 | `all` | 同时按「相关性」和「最新提交」两个维度检索并返回 |
| 关键词检索 | `search` | 按相关性检索（可配 `--sort recent` 改排序） |
| 最新论文 | `recent` | 按提交时间倒序，追踪某方向最新进展 |
| 分类检索 | `category` | 限定 arXiv 分类（如 cs.CL、cs.LG） |
| 作者检索 | `author` | 按作者姓名检索 |
| 自由检索 | `free` | 直接传入 arXiv 检索表达式 |

## 调用方式

### 步骤 1：从用户问题中提取检索关键词

分析用户的研究问题，提取核心英文关键词（通常 2-5 个），覆盖方法、任务、模型等核心概念。

> **重要**：关键词必须为英文。

### 步骤 2：调用检索脚本

通过 `run_skill_script` 工具调用脚本，`args` 参数为字符串列表（位置参数 + 选项参数按顺序排列）。

> **重要参数规则**：
> - 列表元素顺序：`[检索模式, 关键词1, 关键词2, ...]`，选项参数跟在后面如 `["recent", "diffusion model", "--max", "10"]`
> - 脚本结果直接通过 stdout 返回，无需保存到文件再读取

#### 并行检索（最常用，同时拿到「最相关」和「最新」论文）

```json
{
  "skill_name": "arxiv-paper-search",
  "file_path": "scripts/arxiv_search.py",
  "args": ["all", "transformer", "long context"]
}
```

#### 关键词检索

```json
{
  "skill_name": "arxiv-paper-search",
  "file_path": "scripts/arxiv_search.py",
  "args": ["search", "retrieval augmented generation"]
}
```

#### 追踪最新进展

```json
{
  "skill_name": "arxiv-paper-search",
  "file_path": "scripts/arxiv_search.py",
  "args": ["recent", "mixture of experts", "--max", "10"]
}
```

#### 按分类检索

```json
{
  "skill_name": "arxiv-paper-search",
  "file_path": "scripts/arxiv_search.py",
  "args": ["category", "speculative decoding", "--category", "cs.CL"]
}
```

#### 按作者检索

```json
{
  "skill_name": "arxiv-paper-search",
  "file_path": "scripts/arxiv_search.py",
  "args": ["author", "Yann LeCun"]
}
```

#### 自由检索（高级用户，带排序）

```json
{
  "skill_name": "arxiv-paper-search",
  "file_path": "scripts/arxiv_search.py",
  "args": ["free", "--query", "ti:\"diffusion\" AND cat:cs.CV", "--sort", "recent"]
}
```

### 步骤 3：分析 stdout 返回的 JSON 结果

脚本执行后，检索结果以 JSON 格式直接返回在 `stdout` 字段中，可直接解析使用。

## 参数说明

| 参数 | 必选 | 说明 |
|------|------|------|
| `mode` | 是 | 检索模式：all / search / recent / category / author / free |
| `keywords` | 视模式 | 一个或多个英文关键词，空格分隔（free 模式用 `--query`） |
| `--category / -c` | category 模式必选 | arXiv 分类标识，如 cs.CL、cs.LG、cs.CV、stat.ML |
| `--query / -q` | free 模式必选 | arXiv 检索表达式 |
| `--sort / -s` | 否 | 排序：`relevant`（默认）/ `recent`（最新提交）/ `updated`（最近更新） |
| `--max / -m` | 否 | 最大返回数量，默认 20 |

## 检索表达式语法（free 模式）

```
field:"关键词" AND/OR/ANDNOT field:"关键词"
```

**可用字段前缀：**
- `ti` 标题、`abs` 摘要、`all` 全字段
- `au` 作者、`cat` 分类、`jr` 期刊引用

**示例：**
```
ti:"diffusion model" AND cat:cs.CV ANDNOT ti:"survey"
```

## 常用 arXiv 分类

| 分类 | 含义 |
|------|------|
| `cs.CL` | 计算语言学 / NLP |
| `cs.LG` | 机器学习 |
| `cs.CV` | 计算机视觉 |
| `cs.AI` | 人工智能 |
| `stat.ML` | 统计机器学习 |

## 返回结果格式

### 单条论文

```json
{
  "id": "2401.01234v1",
  "title": "论文标题",
  "abstract": "摘要",
  "authors": "作者1, 作者2",
  "primary_category": "cs.CL",
  "categories": ["cs.CL", "cs.LG"],
  "published": "2024-01-15T00:00:00Z",
  "updated": "2024-02-01T00:00:00Z",
  "comment": "Accepted to NeurIPS 2024",
  "journal_ref": "期刊引用（如有）",
  "doi": "DOI（如有）",
  "link": "https://arxiv.org/abs/2401.01234v1",
  "pdf": "https://arxiv.org/pdf/2401.01234v1"
}
```

### all 模式返回结构

```json
{
  "by_relevance": [...],
  "by_recent": [...]
}
```

## 依赖

- `aiohttp` — 异步 HTTP 请求（用于 all 模式并行检索）

## 示例场景

### 场景 1：检索 RAG 相关工作

```json
{
  "skill_name": "arxiv-paper-search",
  "file_path": "scripts/arxiv_search.py",
  "args": ["all", "retrieval augmented generation", "large language model"]
}
```

### 场景 2：追踪长文本建模最新进展

```json
{
  "skill_name": "arxiv-paper-search",
  "file_path": "scripts/arxiv_search.py",
  "args": ["recent", "long context", "attention"]
}
```

### 场景 3：CV 方向自由检索 + 最新排序

```json
{
  "skill_name": "arxiv-paper-search",
  "file_path": "scripts/arxiv_search.py",
  "args": ["free", "--query", "ti:\"diffusion\" AND cat:cs.CV", "--sort", "recent"]
}
```

## 注意事项

1. 检索关键词**必须为英文**，中文需转译
2. 结果直接通过 stdout 返回，无需输出到文件
3. 每次检索默认最多返回 20 条结果（可用 `--max` 调整）
