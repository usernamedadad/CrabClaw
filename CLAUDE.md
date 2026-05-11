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

运行测试：
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

### CLI 工具

```bash
cd backend
pip install -e .               # 安装 crabclaw 命令
crabclaw                       # 交互式 REPL
crabclaw ask "你好"            # 单次查询
crabclaw ingest ./docs/        # 索引文档（RAG）
echo "解释这段代码" | crabclaw  # 管道输入
```

## 架构

### Agent 核心（`backend/app/agent/`）

`CrabClawAgent`（[core_agent.py](backend/app/agent/core_agent.py)）是整个后端的核心，基于 LangChain `create_agent` 构建。关键流程：

- **初始化**：从工作区 `IDENTITY.md` / `PROFILE.md` 读取 Agent 名称，从 `config.json` 读取 LLM 配置
- **对话入口**：`chat()`（同步）和 `astream_chat()`（SSE 流式），后者是前端和 CLI 实际使用的路径
- **入职引导** (`_handle_first_contact_gate`)：首次对话时引导用户提供称呼与长期目标，完成后不再询问
- **系统提示词**：`_build_system_prompt()` 合并 AGENTS.md（工作指南）、IDENTITY、USER、SOUL、MERMORY 五份配置，总量上限 32000 字符
- **工具**：`_build_tools()` 注册 23 个 LangChain tool，涵盖记忆（9个）、搜索（2个）、文件（3个）、命令执行、技能、RAG（3个）、日期、计算器
- **会话持久化**：消息历史以 JSON 存储在 `~/.crabclaw/workspace/sessions/{session_id}.json`
- **流式工具可见**：SSE 流中产出 `tool_start`/`tool_end` 事件，前端和 CLI 可实时展示工具调用状态

### 记忆系统（`backend/app/memory/`）

- **短期记忆**：每日文件 `~/.crabclaw/workspace/memory/YYYY-MM-DD.md`
- **长期记忆**：`MERMORY.md`（刻意拼写），按"偏好/决策/重要事实/用户身份"四个分区组织
- **语义搜索**（`embeddings.py`）：`EmbeddingIndex` 基于 `text-embedding-3-small` 做向量化索引，BM25 + 余弦相似度混合排序。零外部向量库，纯 numpy 内存计算 + JSON 落盘
- **自动捕获**（`signal_capture.py`）：`MemoryCaptureManager` 用规则匹配识别用户消息中的偏好/决定/身份信息，捕获后需用户确认才写入
- **上下文守卫**（`context_guard.py`）：当对话 token 超过阈值时触发静默记忆刷存轮

### RAG 文档检索（`backend/app/rag/`）

- **摄入**（`ingester.py`）：支持 .txt/.md/.py/.csv/.json 等 20+ 种文本格式，按段落分块（512 chars，128 重叠），向量化后落盘到 `~/.crabclaw/rag/index/`
- **检索**（`retriever.py`）：query embedding → 余弦相似度 → top-k 相关块，结果注入 Agent 上下文
- 与语义记忆共享 `EmbeddingIndex` 管线，零新依赖
- API：`POST /api/rag/ingest`（文件上传）、`GET /api/rag/list`、`DELETE /api/rag/{doc_id}`

### CLI 终端（`backend/app/cli/`）

- 复用 `CrabClawAgent` 直调（不走 HTTP），与 Web 共享工作区/会话/记忆/RAG
- `crabclaw` → 交互式 REPL，`crabclaw ask` → 单次查询，管道输入 → 脚本集成
- `argparse` 解析命令，`asyncio` 驱动流式输出

### 工作区配置（`backend/app/workspace/hub.py`）

`WorkspaceManager` 管理 `~/.crabclaw/` 下的所有持久化文件：

| 文件 | 用途 |
|------|------|
| `config.json` | LLM 配置 + 工具配置 + 执行策略 |
| `workspace/AGENTS.md` | Agent 系统提示词（工作指南） |
| `workspace/IDENTITY.md` | Agent 身份（名称、角色、风格） |
| `workspace/USER.md` | 用户偏好（称呼、目标、语言、节奏等） |
| `workspace/SOUL.md` | 人格模板（准则、边界） |
| `workspace/MERMORY.md` | 长期记忆 |
| `workspace/sessions/` | 会话 JSON 文件 |
| `workspace/skills/` | 已安装技能目录（首次初始化时自动安装 3 个预置技能） |

配置别名：`KICKOFF`/`PRINCIPLES` → `AGENTS`，`MEMORY`/`KNOWLEDGE` → `MERMORY`

### 安全策略（`backend/app/tools/builtin/policy.py`）

`LocalToolPolicy` 提供命令执行的 6 层安全机制：命令白名单、目录白名单、风险词拦截、管道/重定向拦截、超时限制（默认 90s/最大 240s）、输出截断（默认 12000 字符）。

### API 路由

| 模块 | 前缀 | 职责 |
|------|------|------|
| `conversation.py` | `/api/chat` | SSE 流式对话 + 同步发送 |
| `history.py` | `/api/session` | 会话 CRUD + 历史查询 |
| `journal.py` | `/api/memory` | 记忆文件读写 |
| `abilities.py` | `/api/skills` | 技能安装/列表/删除 |
| `settings.py` | `/api/config` | LLM 参数 + Agent 信息 |
| `rag.py` | `/api/rag` | 文档上传/列表/删除（RAG） |

### 前端状态管理（`frontend/app/stores/`）

- `session.ts`：Pinia store 管理 `currentSessionId`，自动同步 localStorage。替代了原先三处组件（ChatView/SessionsView/SidebarNav）各自维护的 CustomEvent + localStorage 散落模式

### 技能系统（`backend/app/skills/catalog.py`）

技能以 `SKILL.md` 文件定义，支持 YAML frontmatter + Markdown 正文。安装方式：本地目录、本地 `SKILL.md` 文件、远程 URL。通过 `# 指令` 前缀触发。预置 3 个技能（code-reviewer/translator/doc-writer），首次初始化自动安装。

## 注意事项

- `MERMORY.md` 是刻意拼写（不是 MEMORY），代码中有别名兼容，但文件系统上始终是 MERMORY
- Agent 初始化在 FastAPI lifespan 中完成，通过 `app_state.py` 的模块级单例访问
- 前端 axios 实例超时 120s，baseURL 由 `VITE_API_BASE` 环境变量控制
- 记忆去重用 `rank_bm25` 做 BM25 关键词匹配，叠加 embedding 语义搜索做混合排序
- 后端用 `pyproject.toml`（ruff 配置）+ `requirements.txt`（依赖），前端用 `.eslintrc.cjs` + `.prettierrc`
- 语义搜索和 RAG 的 embedding 依赖 LLM API key（复用 OpenAI 兼容的 `/v1/embeddings` 端点）
