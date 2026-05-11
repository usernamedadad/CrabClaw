# 🦀CrabClaw

CrabClaw 是一个轻量、实用的 AI Agent 协作助手，前后端分离架构，支持 Web UI、CLI 终端双端交互。

## 🌟项目亮点

- 双端交互：Web UI（Vue3 + Ant Design）+ CLI 终端（交互式 REPL / 单次查询 / 管道输入），共享同一 Agent 引擎
- 流式工具可见：工具调用（搜索、文件读写、命令执行）以实时卡片形式展示，执行状态和耗时一目了然
- 语义记忆检索：BM25 + embedding 向量混合排序，支持模糊语义回想（搜"暗色"命中"dark 模式"）
- RAG 文档检索：支持 20+ 种文本格式摄入，上传即问，检索结果自动注入 Agent 上下文
- 技能化扩展：预置 3 个技能（代码审查/翻译/文档撰写），支持本地 / URL 一键安装
- 多层安全：6 层命令执行安全机制（白名单 + 目录沙箱 + 风险拦截 + 管道阻断 + 超时控制 + 审计日志）

## 🚀核心功能

- 智能对话：SSE 流式回复 + 入职引导（首次对话自动收集偏好），上下文连贯自然
- 会话管理：创建、切换、删除、自定义会话信息，Pinia 统一状态管理
- 记忆系统：规则驱动自动捕获 + 语义向量检索 + 敏感信息脱敏 + 跨日重复自动晋升长期记忆
- RAG 检索：上传文档 → 自动分块向量化 → 对话中语义检索相关片段 → 注入上下文回答
- 技能中心：3 个预置技能开箱即用，支持本地导入 / URL 下载 / 自定义安装
- 工具调用：23 个内置工具（记忆、搜索、文件、命令、RAG、日期、计算器等），流式状态实时可见
- 配置中心：在线修改模型参数、API Key、服务地址，支持 OpenAI 兼容 API
- CLI 终端：`crabclaw` 命令支持交互式对话、单次查询、管道输入、文档索引

## 界面预览

深色模式：

![CrabClaw Dark](data/crabclaw1.jpg)

浅色模式：

![CrabClaw Light](data/crabclaw2.jpg)

## 🧩前端可操作

- 对话页：发送消息、流式回复、工具调用卡片、技能触发、入职引导
- 会话页：创建、切换、删除会话，支持自定义会话 ID
- 技能页：刷新、本地导入、URL 导入、卸载技能（3 个预置技能开箱即用）
- 记忆页：查看、编辑、保存、重置记忆文件，语义搜索
- 工具日志：实时查看工具执行记录
- 配置页：模型参数、API 密钥、服务地址在线配置

## 技术栈

| 层级 | 技术栈 |
| --- | --- |
| 后端 API | FastAPI, SSE-Starlette |
| Agent 引擎 | LangChain, LangChain OpenAI |
| 向量检索 | text-embedding-3-small, numpy 余弦相似度 |
| CLI 终端 | argparse, asyncio |
| 前端应用 | Vue 3, Vite, TypeScript |
| UI 组件 | Ant Design Vue |
| 状态管理 | Pinia |
| 代码质量 | ruff (Python), ESLint + Prettier (TS) |

## 环境要求

- Python 3.10+
- Node.js 18+
- npm 9+
- Windows / macOS / Linux

## 项目框架

```text
crabclaw/
├─ backend/
│  ├─ app/
│  │  ├─ main.py          # FastAPI 入口
│  │  ├─ agent/           # Agent 主流程、同步/流式对话
│  │  ├─ api/             # chat/session/memory/skills/config/rag 接口
│  │  ├─ memory/          # 记忆系统（捕获/语义检索/上下文守卫/embedding）
│  │  ├─ rag/             # RAG 文档检索（ingester/retriever）
│  │  ├─ cli/             # CLI 终端（main/repl/render/stream）
│  │  ├─ skills/          # Skills 注册与安装管理
│  │  ├─ tools/           # 23 个内置工具 + 命令安全策略
│  │  └─ workspace/       # 本地工作区与配置管理
│  ├─ pyproject.toml      # ruff 配置 + CLI 入口点
│  └─ requirements.txt
├─ frontend/
│  ├─ app/
│  │  ├─ pages/           # Chat/Sessions/Skills/Memory/ToolLog/Config 页面
│  │  ├─ components/      # 侧边栏等通用组件
│  │  ├─ stores/          # Pinia 状态管理
│  │  ├─ api/             # 前端 API 封装
│  │  ├─ routes.ts        # 路由入口
│  │  └─ main.ts          # 应用入口
│  ├─ .eslintrc.cjs       # ESLint 配置
│  ├─ .prettierrc         # Prettier 配置
│  └─ package.json
├─ data/                  # README 截图等静态资源
└─ README.md
```

## 快速开始

### 1) 后端

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# 填写 .env 文件中的 LLM_API_KEY 和其他配置项
uvicorn app.main:app --reload --port 8000
```

### 2) 前端

```bash
cd frontend
npm install
npm run dev
```

### 3) CLI（可选）

```bash
cd backend
pip install -e .
crabclaw
```

访问地址：

- 前端：http://localhost:725
- 后端：http://localhost:8000
- 健康检查：http://localhost:8000/health

## ⚙️配置说明

后端配置文件：`backend/.env`

至少需要配置：

```env
LLM_MODEL_ID=gpt-4o-mini
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
```

常用可选项：

```env
LLM_TEMPERATURE=0.4
CORS_ORIGINS=http://localhost:725
WORKSPACE_PATH=~/.crabclaw/workspace
SERPAPI_API=                   # 搜索引擎 API key（可选）
```

## 🔐安全机制

1. 命令白名单：只允许授权命令执行
2. 目录白名单：文件操作仅限工作区目录
3. 风险词拦截：自动拦截 `shutdown`, `rm -rf /` 等高风险命令
4. 管道/重定向拦截：默认禁用 `|` `&&` `>` 等组合操作
5. 超时与输出限制：命令默认 90s 超时，输出 12000 字符截断
6. 执行审计日志：记录 `execution_audit.log` 便于追踪

## API 接口

| 端点 | 方法 | 描述 |
| --- | --- | --- |
| `/health` | GET | 健康检查 |
| `/api/chat` | POST | 发送消息（SSE 流式，含 tool_start/tool_end 事件） |
| `/api/chat/send` | POST | 发送消息（同步） |
| `/api/session/list` | GET | 获取会话列表 |
| `/api/session/create` | POST | 创建会话（支持自定义 session_id） |
| `/api/session/{session_id}/history` | GET | 获取会话历史 |
| `/api/session/{session_id}` | DELETE | 删除会话 |
| `/api/config/agent/info` | GET | 获取 Agent 信息 |
| `/api/config/llm` | GET/PUT | 获取/更新 LLM 配置 |
| `/api/memory/files` | GET | 获取记忆文件列表 |
| `/api/memory/content` | GET/PUT | 获取/更新记忆内容 |
| `/api/skills/list` | GET | 获取技能列表 |
| `/api/skills/install/local` | POST | 本地安装技能 |
| `/api/skills/install/url` | POST | URL 安装技能 |
| `/api/skills/{skill_id}` | DELETE | 卸载技能 |
| `/api/rag/ingest` | POST | 上传文档（RAG） |
| `/api/rag/list` | GET | 已索引文档列表 |
| `/api/rag/{doc_id}` | DELETE | 删除文档索引 |

## 🙏致谢

- [LangChain](https://www.langchain.com/) - Agent 编排框架
- [FastAPI](https://fastapi.tiangolo.com/) - 后端框架
- [Vue.js](https://vuejs.org/) - 前端框架
- [Vite](https://vitejs.dev/) - 前端构建工具
- [Ant Design Vue](https://antdv.com/) - UI 组件库

## License

本项目基于 MIT License 开源，详见 [LICENSE](LICENSE)。
