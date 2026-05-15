# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

CrabClaw 是一个 AI Agent 协作助手，前后端分离架构。后端用 FastAPI + LangChain 构建 Agent 引擎，前端用 Vue 3 + Vite + Ant Design Vue 构建。同时提供 CLI 终端工具（`crabclaw` 命令）。

## 常用命令

### 后端

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env          # 编辑 .env 填入 LLM_API_KEY 等
uvicorn app.main:app --reload --port 8000
```

代码检查：
```bash
cd backend
ruff check .
ruff format --check .
```

测试（pytest + pytest-asyncio 已配置，测试文件待补充）：
```bash
cd backend
pytest
pytest -k "test_name"         # 运行单个测试
```

### 前端

```bash
cd frontend
npm install
npm run dev                    # 开发服务器，默认 http://localhost:725
npm run build                  # 生产构建（含 vue-tsc 类型检查）
npx eslint app/               # 代码检查
```

前端 baseURL 由 `VITE_API_BASE` 环境变量控制，Vite 开发代理将 `/api` 转发到后端 8000 端口。

### CLI 工具

```bash
cd backend
pip install -e .               # 安装 crabclaw 命令
crabclaw                       # 交互式 REPL（等同于 crabclaw chat）
crabclaw ask "你好"            # 单次查询
crabclaw ask -s SID "..."      # 指定会话的单次查询
crabclaw ask --skill SKILL "..."  # 指定技能的单次查询
echo "解释这段代码" | crabclaw  # 管道输入
```

## 架构

### Agent 核心（`backend/app/agent/`）

`CrabClawAgent`（[core_agent.py](backend/app/agent/core_agent.py)）是整个后端的核心，基于 LangChain `create_agent` 构建。关键流程：

- **初始化**：从工作区 `IDENTITY.md` / `PROFILE.md` 读取 Agent 名称，从 `config.json` 读取 LLM 配置
- **对话入口**：`chat()`（同步）和 `astream_chat()`（SSE 流式），后者是前端和 CLI 实际使用的路径
- **入职引导** (`_handle_first_contact_gate`)：首次对话时引导用户提供称呼与长期目标，完成后不再询问
- **系统提示词**：`_build_system_prompt()` 合并 AGENTS（工作指南）、IDENTITY、PROFILE、USER、SOUL、MERMORY 六份配置，总量上限 32000 字符。PROFILE 是 IDENTITY 的备选回退源。提示词按文件 mtime 做 hash 缓存，仅在配置文件变更时重建
- **Token 估算**：使用 `tiktoken`（`cl100k_base` 编码）精确计 token
- **工具**：`_build_tools()` 注册 19 个 LangChain tool 函数（记忆 9 个、搜索 2 个、文件 3 个、命令执行 1 个、技能 2 个、日期 1 个、计算器 1 个）。底层为 7 个 tool 类实例，每个 tool 函数是对类方法的薄封装
- **会话持久化**：消息历史以 JSON 存储在 `~/.crabclaw/workspace/sessions/{session_id}.json`
- **流式工具可见**：SSE 流中产出 `tool_start`/`tool_end` 事件，前端和 CLI 可实时展示工具调用状态
- **消息桥接**（[stream_bridge.py](backend/app/agent/stream_bridge.py)）：LangChain 消息与历史 JSON 之间的格式转换
- **工具可靠性**：文件写入后自动读回校验，失败则重试；同工具连续失败 3 次触发 `tool_warning` SSE 事件；文件读取按 (path, start, end) 缓存，每次对话开始前清空

### 记忆系统（`backend/app/memory/`）

- **短期记忆**：每日文件 `~/.crabclaw/workspace/memory/YYYY-MM-DD.md`
- **长期记忆**：`MERMORY.md`（刻意拼写），按"偏好/决策/重要事实/用户身份"四个分区组织
- **语义搜索**（[embeddings.py](backend/app/memory/embeddings.py)）：`EmbeddingIndex` 基于 `text-embedding-3-small` 做向量化索引，BM25 + 余弦相似度混合排序。零外部向量库，纯 numpy 内存计算 + JSON 落盘。embedding 结果按 sha256 hash 缓存避免重复调用
- **自动捕获**（[signal_capture.py](backend/app/memory/signal_capture.py)）：`MemoryCaptureManager` 用规则匹配识别用户消息中的偏好/决定/身份信息，捕获后需用户确认才写入
- **上下文守卫**（[context_guard.py](backend/app/memory/context_guard.py)）：当对话 token 超过阈值（默认 context_window 的 80%）时触发静默记忆刷存轮，刷存前自动从近 6 轮对话中提取摘要注入提示词
- **会话摘要**（[chat_recap.py](backend/app/memory/chat_recap.py)）：`SessionSummarizer` 将会话历史总结为归档笔记

### CLI 终端（`backend/app/cli/`）

- 复用 `CrabClawAgent` 直调（不走 HTTP），与 Web 共享工作区/会话/记忆
- `crabclaw` / `crabclaw chat` → 交互式 REPL，`crabclaw ask` → 单次查询，管道输入 → 脚本集成
- `argparse` 解析命令，`asyncio` 驱动流式输出
- 支持 `-s` 指定会话 ID，`--skill` 指定技能 ID

### 工作区配置（`backend/app/workspace/hub.py`）

`WorkspaceManager` 管理 `~/.crabclaw/` 下的所有持久化文件，模板位于 `workspace/prompt/`（`BOOTSTRAP.md`、`HEARTBEAT.md`、`PROFILE.md`）。内置配置 mtime 缓存（`_config_cache`）和会话 JSON 缓存（`_session_cache`），写入时自动失效：

| 文件 | 用途 |
|------|------|
| `config.json` | LLM 配置 + 工具配置 + 执行策略 |
| `defaults.json` | 默认 LLM 参数（temperature/max_tokens 等回退值） |
| `workspace/AGENTS.md` | Agent 系统提示词（工作指南） |
| `workspace/IDENTITY.md` | Agent 身份（名称、角色、风格） |
| `workspace/USER.md` | 用户偏好（称呼、目标、语言、节奏等） |
| `workspace/SOUL.md` | 人格模板（准则、边界） |
| `workspace/MERMORY.md` | 长期记忆 |
| `workspace/sessions/` | 会话 JSON 文件 |
| `workspace/skills/` | 已安装技能目录（首次初始化时自动安装 3 个预置技能） |

配置别名：`KICKOFF`/`PRINCIPLES` → `AGENTS`，`MEMORY`/`KNOWLEDGE` → `MERMORY`。CLI 入口点定义在 [pyproject.toml](backend/pyproject.toml) 的 `[project.scripts]` 中：`crabclaw = "app.cli:main"`。

Agent 和 Workspace 的初始化在 FastAPI lifespan 中完成，通过 [app_state.py](backend/app/app_state.py) 的模块级单例（`get_agent()`/`get_workspace()`）访问。

### 安全策略（`backend/app/tools/builtin/policy.py`）

`LocalToolPolicy` 提供命令执行的 6 层安全机制：命令白名单、目录白名单、风险词拦截、管道/重定向拦截、超时限制（默认 90s/最大 240s）、输出截断（默认 12000 字符）。

### API 路由

路由注册在 [main.py](backend/app/main.py) 中通过 `include_router(prefix="/api")` + 各模块自带子前缀组合：

| 模块 | 子前缀 | 完整路径示例 | 职责 |
|------|------|------|------|
| `conversation.py` | `/chat` | `/api/chat` | SSE 流式对话 + 同步发送 |
| `history.py` | `/session` | `/api/session/list` | 会话 CRUD + 历史查询 |
| `journal.py` | `/memory` | `/api/memory/files` | 记忆文件读写 |
| `abilities.py` | `/skills` | `/api/skills/list` | 技能安装/列表/删除 |
| `settings.py` | `/config` | `/api/config/llm` | LLM 参数 + Agent 信息 |

### 前端架构（`frontend/app/`）

- **页面**（[pages/](frontend/app/pages/)）：ChatView（对话）、SessionsView（会话列表）、SkillsView（技能管理）、MemoryView（记忆浏览）、ToolLogView（工具调用日志）、ConfigView（配置）
- **状态管理**（[stores/session.ts](frontend/app/stores/session.ts)）：Pinia store 管理 `currentSessionId`，自动同步 localStorage
- **API 层**（[api/](frontend/app/api/)）：按模块拆分为 chat/session/memory/skills/config，统一通过 axios 实例（超时 120s）调用后端
- **路由**：Vue Router，在 [routes.ts](frontend/app/routes.ts) 中定义页面映射
- **Markdown 渲染**：使用 `markdown-it` 渲染 Agent 回复中的 Markdown，`dompurify` 做 XSS 防护
- **UI 组件**：Ant Design Vue 4.x + `@ant-design/icons-vue`

### 技能系统（`backend/app/skills/catalog.py`）

技能以 `SKILL.md` 文件定义，支持 YAML frontmatter + Markdown 正文。安装方式：本地目录、本地 `SKILL.md` 文件、远程 URL。Agent 通过 `run_skill` 工具按对话上下文自主判断并激活技能，也可通过 CLI `--skill` 参数或 API `skill_id` 显式指定。预置 3 个技能（code-reviewer/translator/doc-writer），首次初始化自动安装。

## 注意事项

- `MERMORY.md` 是刻意拼写（不是 MEMORY），代码中有别名兼容，但文件系统上始终是 MERMORY
- 前端 axios 实例超时 120s，baseURL 由 `VITE_API_BASE` 环境变量控制
- 记忆去重用 `rank_bm25` 做 BM25 关键词匹配，叠加 embedding 语义搜索做混合排序
- 后端用 `pyproject.toml`（ruff 配置）+ `requirements.txt`（依赖），前端用 `.eslintrc.cjs` + `.prettierrc`
- 语义搜索的 embedding 依赖 LLM API key（复用 OpenAI 兼容的 `/v1/embeddings` 端点）
- `SERPAPI_API` 是可选配置，仅 web_search 工具需要；不配则搜索结果返回空
- CLI 和 Web 共享同一套工作区/会话/记忆，CLI 直调不走 HTTP
