---
name: bingsearch
description: Bing 网络搜索技能。⚠️ 注意：Bing 有强反爬机制，直接 curl 或 urllib 抓取必定被拦截、返回空结果。本技能脚本内置了完整反爬方案（Cookie 管理、多浏览器 UA、aiohttp + BeautifulSoup 结构化解析、结果缓存）。当需要联网搜索时时必须 `load_skill("bingsearch")` 加载本技能获取调用指导，然后按指导使用 `terminal` 运行脚本，**不得直接 curl 抓取**。支持关键词搜索、站点限定、多站点组合、排除/文件类型过滤、网页正文抓取。
---

# Bing Search — Bing 网络搜索

## 概述

通过解析 Bing 搜索结果页（https://cn.bing.com/search）进行实时网络检索，免费、无需 token。支持关键词搜索、站点过滤、高级组合搜索，以及抓取网页正文。

支持以下模式：

| 模式 | 命令 | 说明 |
|------|------|------|
| 关键词搜索 | `search` | Bing 关键词检索，可选限定单个站点 |
| 抓取正文 | `fetch` | 抓取指定 URL 的网页主体内容 |
| 高级搜索 | `advanced` | 组合多站点、排除站点、文件类型过滤 |

## 调用方式

通过 `run_skill_script` 工具调用脚本，`args` 参数为字符串列表（位置参数 + 选项参数按顺序排列）。脚本结果直接通过 stdout 返回，无需保存到文件再读取。

### 关键词搜索

```json
{
  "skill_name": "bingsearch",
  "file_path": "scripts/bing_search.py",
  "args": ["search", "特斯拉 最新财报", "--num", "5"]
}
```

### 限定站点搜索

```json
{
  "skill_name": "bingsearch",
  "file_path": "scripts/bing_search.py",
  "args": ["search", "Model Y", "--site", "tesla.cn"]
}
```

### 抓取网页正文

搜索拿到结果后，用结果中的 `link` 抓取该页正文。

```json
{
  "skill_name": "bingsearch",
  "file_path": "scripts/bing_search.py",
  "args": ["fetch", "https://www.tesla.cn/modely"]
}
```

### 高级搜索（多站点 / 排除 / 文件类型）

```json
{
  "skill_name": "bingsearch",
  "file_path": "scripts/bing_search.py",
  "args": ["advanced", "财报", "--site", "tesla.cn", "--exclude", "cn.bing.com", "--filetype", "pdf", "--num", "5"]
}
```

## 参数说明

### search 模式

| 参数 | 必选 | 说明 |
|------|------|------|
| `query` | 是 | 搜索关键词 |
| `--num / -n` | 否 | 返回结果数量，默认 5 |
| `--site / -s` | 否 | 限定单个站点，如 `tesla.cn` |

### fetch 模式

| 参数 | 必选 | 说明 |
|------|------|------|
| `url` | 是 | 要抓取的网页 URL |

### advanced 模式

| 参数 | 必选 | 说明 |
|------|------|------|
| `query` | 是 | 搜索关键词 |
| `--site / -s` | 否 | 限定站点，可多次传入（OR 组合） |
| `--exclude / -x` | 否 | 排除站点，可多次传入 |
| `--filetype / -t` | 否 | 限定文件类型，如 `pdf` |
| `--num / -n` | 否 | 返回结果数量，默认 5 |

## 返回结果格式

### search / advanced 单条结果

```json
{
  "id": "result_1718712345.6_0",
  "title": "网页标题",
  "link": "https://example.com/page",
  "snippet": "摘要片段",
  "site": "tesla.cn"
}
```

`advanced` 模式外层为 `{"query": ..., "filters": {...}, "results": [...]}`。

### fetch 返回

纯文本：网页标题 + 正文（自动清理脚本/导航/广告等噪音，超过 8000 字截断）。

## 依赖

- `aiohttp` — 异步 HTTP 请求
- `beautifulsoup4` + `lxml` — HTML 解析

## 注意事项

1. 结果来自实时解析 Bing 搜索页，页面结构变化可能影响解析；解析失败时会回退返回 Bing 搜索链接
2. 结果直接通过 stdout 返回，无需输出到文件
3. `fetch` 抓取受目标站点反爬/编码影响，正文最多返回 8000 字
