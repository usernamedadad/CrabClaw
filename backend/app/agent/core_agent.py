"""CrabClaw Agent built on LangChain create_agent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import tiktoken
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from ..memory.chat_recap import SessionSummarizer
from ..memory.context_guard import MemoryFlushManager
from ..memory.signal_capture import MemoryCaptureManager
from ..skills import SkillRegistry
from ..tools import CalculatorTool, DateTimeTool, ExecuteCommandTool, MemoryTool, WebFetchTool, WebSearchTool, WorkspaceFileTool
from ..workspace.hub import WorkspaceManager, extract_identity_name
from .stream_bridge import extract_text_chunk, find_final_assistant_text, message_to_history


class CrabClawAgent:
    def __init__(self, workspace_manager: WorkspaceManager):
        self.workspace = workspace_manager
        self.workspace.ensure_workspace_exists()

        self.name = self._read_identity_name() or "CrabClaw"
        self._memory_tool = MemoryTool(self.workspace)
        self._web_search_tool = WebSearchTool(api_key=self.workspace.get_search_api_key())
        self._web_fetch_tool = WebFetchTool()
        self._execute_command_tool = ExecuteCommandTool(self.workspace)
        self._workspace_file_tool = WorkspaceFileTool(self.workspace)
        self._datetime_tool = DateTimeTool()
        self._calculator_tool = CalculatorTool()

        self._memory_capture_manager = MemoryCaptureManager(self.workspace)
        self._memory_flush_manager = MemoryFlushManager()
        self._skill_registry = SkillRegistry(self.workspace)

        self._agent = None
        self._runtime_snapshot: Optional[tuple[Any, ...]] = None
        self._init_error: Optional[str] = None
        self._current_session_id: Optional[str] = None
        self._cached_system_prompt: Optional[str] = None
        self._cached_system_prompt_tokens: Optional[int] = None
        self._last_prompt_config_hash: str = ""
        self._tool_failure_counts: Dict[str, int] = {}

    def _read_identity_name(self) -> Optional[str]:
        return extract_identity_name(self.workspace.load_config("IDENTITY")) or extract_identity_name(
            self.workspace.load_config("PROFILE")
        )

    @staticmethod
    def _clean_value(value: str, limit: int) -> str:
        return re.sub(r"\s+", " ", (value or "")).strip()[:limit]

    def _resolve_output_language(self, text: str) -> str:
        preferred = str(self.workspace.get_user_profile(allow_fallback=True).get("输出语言") or "").strip().lower()
        if preferred in {"english", "en"}:
            return "en"
        if preferred in {"中文", "zh", "cn"}:
            return "zh"
        if preferred == "auto":
            return self._detect_language(text)
        return self._detect_language(text)

    @staticmethod
    def _detect_language(text: str) -> str:
        content = text or ""
        cjk = len(re.findall(r"[\u4e00-\u9fff]", content))
        latin = len(re.findall(r"[A-Za-z]", content))
        total = cjk + latin
        if total == 0:
            return "zh"
        ratio = cjk / total
        if ratio >= 0.6:
            return "zh"
        if ratio <= 0.4:
            return "en"
        return "zh"

    def _extract_onboarding_fields(self, text: str) -> tuple[dict, List[str]]:
        content = (text or "").strip()
        if not content:
            return {}, []

        fields: dict[str, str] = {}
        snippets: List[str] = []

        name_patterns = [
            r"(?:^|\n)\s*(?:称呼|称呼我|名字|我的名字|我叫)\s*[：:]\s*([^\n，。,。!?！？]{1,24})",
            r"(?:叫我|称呼我|我的名字是|我叫)\s*([^\s，。,。!?！？]{1,24})",
        ]
        for pattern in name_patterns:
            matched = re.search(pattern, content, re.IGNORECASE)
            if matched:
                value = self._clean_value(matched.group(1), 24)
                if value:
                    fields["称呼"] = value
                    snippets.append(matched.group(0))
                break

        goal_patterns = [
            r"(?:^|\n)\s*(?:协作目标|长期目标|主要目标|希望你长期帮我)\s*[：:]\s*([^\n]{4,180})",
            r"(?:最希望你长期帮我|长期想让你帮我)\s*([^。！？!\n]{4,180})",
        ]
        for pattern in goal_patterns:
            matched = re.search(pattern, content, re.IGNORECASE)
            if matched:
                value = self._clean_value(matched.group(1), 180)
                if value:
                    fields["长期目标"] = value
                    snippets.append(matched.group(0))
                break

        lang_match = re.search(r"(?:输出语言|用语言|语言偏好)\s*[：:]\s*(中文|English|英文|auto)", content, re.IGNORECASE)
        if lang_match:
            lang = lang_match.group(1).lower()
            fields["输出语言"] = "English" if lang in {"english", "英文"} else "中文" if lang == "中文" else "auto"
            snippets.append(lang_match.group(0))
        elif re.search(r"(用中文回复|中文回答)", content):
            fields["输出语言"] = "中文"
            snippets.append("用中文回复")
        elif re.search(r"(用英文回复|用英语回复|英文回答)", content, re.IGNORECASE):
            fields["输出语言"] = "English"
            snippets.append("用英文回复")

        length_match = re.search(r"(?:回答长度|回复长度)\s*[：:]\s*(短|中|长)", content)
        if length_match:
            fields["回答长度"] = length_match.group(1)
            snippets.append(length_match.group(0))
        elif re.search(r"(简短|短一点)", content):
            fields["回答长度"] = "短"
        elif re.search(r"(详细|长一点|展开点)", content):
            fields["回答长度"] = "长"
        elif re.search(r"(适中|中等|正常长度)", content):
            fields["回答长度"] = "中"

        pace_match = re.search(r"(?:沟通节奏|节奏)\s*[：:]\s*(快|适中|慢)", content)
        if pace_match:
            fields["沟通节奏"] = pace_match.group(1)
            snippets.append(pace_match.group(0))
        elif re.search(r"(快一点|节奏快)", content):
            fields["沟通节奏"] = "快"
        elif re.search(r"(慢一点|节奏慢)", content):
            fields["沟通节奏"] = "慢"
        elif re.search(r"(适中|正常节奏)", content):
            fields["沟通节奏"] = "适中"

        tz_match = re.search(r"(?:时区)\s*[：:]\s*([A-Za-z_/]+|UTC[+-]\d{1,2}:?\d{0,2})", content)
        if tz_match:
            fields["时区"] = tz_match.group(1).strip()
            snippets.append(tz_match.group(0))

        return fields, snippets

    @staticmethod
    def _should_skip_onboarding(text: str) -> bool:
        return bool(re.search(r"(先不填|暂时不填|不想填|不填写|以后再说|先别问)", text or ""))

    @staticmethod
    def _build_onboarding_question(field: str, language: str) -> str:
        if language == "en":
            prompts = {
                "称呼": "How should I address you?",
                "长期目标": "What long-term goal should I focus on for you?",
                "输出语言": "Preferred output language? (中文 / English / auto)",
                "回答长度": "Preferred answer length? (短 / 中 / 长)",
                "沟通节奏": "Preferred pacing? (快 / 适中 / 慢)",
            }
        else:
            prompts = {
                "称呼": "你希望我怎么称呼你？",
                "长期目标": "你最希望我长期重点帮你做什么？",
                "输出语言": "输出语言偏好？可选：中文 / English / auto",
                "回答长度": "回答长度偏好？可选：短 / 中 / 长",
                "沟通节奏": "沟通节奏偏好？可选：快 / 适中 / 慢",
            }
        return prompts.get(field, "你希望我补充哪项长期协作信息？")

    @staticmethod
    def _build_profile_update_prompt(field: str, value: str, language: str) -> str:
        if language == "en":
            return f"Confirm updating {field} to \"{value}\"?"
        return f"确认把{field}更新为“{value}”吗？"

    @staticmethod
    def _split_paragraphs(text: str) -> List[str]:
        blocks: List[str] = []
        current: List[str] = []
        for line in (text or "").splitlines():
            if not line.strip():
                if current:
                    blocks.append("\n".join(current).strip())
                    current = []
                continue
            current.append(line)
        if current:
            blocks.append("\n".join(current).strip())
        return blocks

    @staticmethod
    def _truncate_entries(entries: List[str], limit: int) -> List[str]:
        if limit <= 0:
            return []
        kept: List[str] = []
        total = 0
        for entry in reversed(entries):
            entry_len = len(entry) + (2 if kept else 0)
            if total + entry_len > limit:
                if not kept:
                    kept.append(entry[:limit])
                break
            kept.append(entry)
            total += entry_len
        return list(reversed(kept))

    @staticmethod
    def _build_segment(title: str, entries: List[str], sep: str) -> str:
        body = sep.join(entries).strip()
        if body:
            return f"## {title}\n{body}"
        return f"## {title}"

    @staticmethod
    def _build_field_entries(profile: dict, fields: List[str]) -> List[str]:
        entries: List[str] = []
        for label in fields:
            value = str(profile.get(label) or "").strip()
            if value:
                entries.append(f"- {label}：{value}")
        return entries

    @staticmethod
    def _build_longterm_entries(text: str) -> List[str]:
        entries: List[str] = []
        heading = ""
        for line in (text or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                heading = stripped
                continue
            if stripped.startswith("- "):
                if heading:
                    entries.append(f"{heading}\n{stripped}")
                else:
                    entries.append(stripped)

        if not entries and text.strip():
            entries = [text.strip()]
        return entries

    def _needs_bootstrap(self, session_id: str) -> bool:
        if self.workspace.has_completed_first_contact():
            return False
        session_data = self.workspace.load_session_data(session_id)
        existing_messages = session_data.get("messages", [])
        if existing_messages:
            return False
        return True

    def _build_bootstrap_instruction(self) -> Optional[str]:
        content = (self.workspace.load_config("BOOTSTRAP") or "").strip()
        if not content:
            return None
        return (
            content
            + "\n\n---\n"
            "当前处于首次初始化阶段。请按照上述引导自然地与用户对话，"
            "用正常聊天的方式收集以下 5 项用户信息并写入 USER.md："
            "称呼、长期目标、输出语言、回答长度、沟通节奏。"
            "全部收集完成后，说「已完成初始化，我们开始推进当前任务。」"
        )

    _PROMPT_CONFIG_NAMES = ["AGENTS", "IDENTITY", "PROFILE", "USER", "SOUL", "MERMORY", "BOOTSTRAP", "HEARTBEAT"]
    _FAILURE_MARKERS = ["error", "failed", "traceback", "失败", "超时", "未在白名单"]
    _TOKENIZER_ENCODING = "cl100k_base"

    def _build_system_prompt(self) -> str:
        config_names = self._PROMPT_CONFIG_NAMES
        hash_parts: list[str] = []
        for name in config_names:
            path = self.workspace.get_config_path(name)
            if path.exists():
                try:
                    hash_parts.append(f"{name}:{path.stat().st_mtime}")
                except OSError:
                    hash_parts.append(f"{name}:na")
            else:
                hash_parts.append(f"{name}:missing")
        config_hash = hashlib.md5("".join(hash_parts).encode()).hexdigest()
        if config_hash == self._last_prompt_config_hash and self._cached_system_prompt is not None:
            return self._cached_system_prompt

        base_prompt = (self.workspace.load_config("AGENTS") or "").strip()
        if not base_prompt:
            base_prompt = "你是 CrabClaw，负责把用户目标变成可执行结果。优先真实、可落地、少废话。"

        identity_profile = self.workspace.get_identity_profile(allow_fallback=True)
        user_profile = self.workspace.get_user_profile(allow_fallback=True)
        soul_profile = self.workspace.get_soul_profile(allow_fallback=True)
        longterm_memory = (self.workspace.load_config("MERMORY") or "").strip()
        heartbeat_content = (self.workspace.load_config("HEARTBEAT") or "").strip()

        # 从全局配置加载 personality
        personality = self.workspace.get_personality()
        personality_guide = {
            "steady": "保持稳重、可靠，不急于下结论，步步为营。",
            "creative": "鼓励创造性思维，多提新思路和可能性。",
            "concise": "极度简洁，只说必要的，不啰嗦。",
            "detailed": "详细解释每一步，不省略关键细节。",
        }
        personality_instruction = personality_guide.get(personality, personality_guide["steady"])

        # 将 personality 注入人格模板
        soul_entries = self._build_field_entries(soul_profile, ["核心准则", "边界", "风格"])
        if personality_instruction:
            soul_entries.append(f"当前协作风格：{personality_instruction}")

        heartbeat_entries = self._split_paragraphs(heartbeat_content) if heartbeat_content else []

        segments = [
            {
                "key": "guide",
                "title": "工作指南",
                "entries": self._split_paragraphs(base_prompt) or [base_prompt],
                "sep": "\n\n",
            },
            {
                "key": "identity",
                "title": "身份信息",
                "entries": self._build_field_entries(identity_profile, ["名称", "角色", "风格", "表情符号", "头像"]),
                "sep": "\n",
            },
            {
                "key": "user",
                "title": "用户信息",
                "entries": self._build_field_entries(
                    user_profile, ["称呼", "长期目标", "输出语言", "回答长度", "沟通节奏", "时区"]
                ),
                "sep": "\n",
            },
            {
                "key": "soul",
                "title": "人格模板",
                "entries": soul_entries,
                "sep": "\n",
            },
            {
                "key": "heartbeat",
                "title": "心跳任务",
                "entries": heartbeat_entries,
                "sep": "\n\n",
            },
            {
                "key": "memory",
                "title": "长期记忆",
                "entries": self._build_longterm_entries(longterm_memory) if longterm_memory else [],
                "sep": "\n\n",
            },
        ]

        per_limit = 8000
        total_limit = 32000
        for segment in segments:
            segment["entries"] = self._truncate_entries(segment["entries"], per_limit)

        def build_blocks() -> List[str]:
            return [self._build_segment(seg["title"], seg["entries"], seg["sep"]) for seg in segments]

        total_len = len("\n\n".join(build_blocks()))
        trim_order = ["heartbeat", "memory", "soul", "identity", "user", "guide"]
        while total_len > total_limit:
            trimmed = False
            for key in trim_order:
                target = next((seg for seg in segments if seg["key"] == key), None)
                if target and target["entries"]:
                    target["entries"].pop(0)
                    trimmed = True
                    break
            if not trimmed:
                break
            total_len = len("\n\n".join(build_blocks()))

        result = "\n\n".join(build_blocks()).strip()
        self._last_prompt_config_hash = config_hash
        self._cached_system_prompt = result
        self._cached_system_prompt_tokens = None  # invalidated, lazy-recompute
        return result

    def _build_tools(self):
        memory_tool = self._memory_tool
        search_tool = self._web_search_tool
        fetch_tool = self._web_fetch_tool
        command_tool = self._execute_command_tool
        file_tool = self._workspace_file_tool

        @tool("memory_search")
        def memory_search(keyword: str, context_lines: int = 3) -> str:
            """按关键词搜索记忆，返回带上下文的结果。"""
            return memory_tool.search(keyword, context_lines)

        @tool("memory_get")
        def memory_get(filename: str = "", lines: str = "") -> str:
            """读取记忆文件，支持行范围（如 10-20）。"""
            if not filename or len(filename.strip()) < 2:
                return "请告诉我要读取哪个记忆文件。"
            return memory_tool.get(filename or None, lines or None)

        @tool("memory_add")
        def memory_add(content: str, category: str = "") -> str:
            """新增记忆项，分类: preference/decision/entity/fact。"""
            return memory_tool.add(content, category or None)

        @tool("memory_update_longterm")
        def memory_update_longterm(content: str, category: str = "") -> str:
            """追加到长期记忆，分类: preference/decision/entity/fact。"""
            return memory_tool.update_longterm(content, category or None)

        @tool("memory_list")
        def memory_list() -> str:
            """列出记忆文件。"""
            return memory_tool.list()

        @tool("memory_cleanup")
        def memory_cleanup(days: int = 30) -> str:
            """清理超过 N 天的每日记忆文件。"""
            return memory_tool.cleanup(days)

        @tool("memory_get_active_context")
        def memory_get_active_context() -> str:
            """获取当前任务上下文。"""
            return memory_tool.get_active_context()

        @tool("memory_set_active_context")
        def memory_set_active_context(content: str) -> str:
            """设置当前任务上下文，压缩后不丢失。"""
            return memory_tool.set_active_context(content)

        @tool("memory_clear_active_context")
        def memory_clear_active_context() -> str:
            """清空当前任务上下文（任务结束时使用）。"""
            return memory_tool.clear_active_context()

        @tool("search_web")
        def search_web(query: str, count: int = 5) -> str:
            """网页搜索。"""
            return search_tool.run(query, count)

        @tool("fetch_url")
        def fetch_url(url: str) -> str:
            """抓取网页内容转为可读文本。"""
            return fetch_tool.run(url)

        @tool("list_workspace")
        def list_workspace(path: str = ".", recursive: bool = False, max_entries: int = 200) -> str:
            """列出工作区目录内容。"""
            return file_tool.list_dir(path=path, recursive=recursive, max_entries=max_entries)

        @tool("read_workspace_file")
        def read_workspace_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
            """读取工作区文件，支持行范围。"""
            return file_tool.read_text(path=path, start_line=start_line, end_line=end_line)

        @tool("write_workspace_file")
        def write_workspace_file(path: str, content: str, mode: str = "overwrite") -> str:
            """写入工作区文件（overwrite/append/create）。"""
            result = file_tool.write_text(path=path, content=content, mode=mode)
            if not result.startswith("写入成功"):
                return result
            # 写入后校验：读回前 3 行确认内容已落地
            verify_result = file_tool.read_text(path=path, start_line=1, end_line=3)
            if "文件不存在" in verify_result or "读取失败" in verify_result:
                # 重试一次，保留原始 mode 避免 append 时覆盖已有内容
                result = file_tool.write_text(path=path, content=content, mode=mode)
                if not result.startswith("写入成功"):
                    return f"写入校验失败，重试也失败: {result}"
                return f"写入成功（已重试并校验通过）: {path}"
            return result

        @tool("execute_command")
        def execute_command(command: str, working_directory: str = "", timeout_seconds: int = 0) -> str:
            """执行本地命令（受白名单和策略保护）。"""
            requested_timeout = timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
            return command_tool.run(
                command=command,
                working_directory=working_directory,
                timeout_seconds=requested_timeout,
            )

        @tool("list_skills")
        def list_skills() -> str:
            """列出已安装技能，返回名称和简介。"""
            skills = self._skill_registry.list_skills()
            if not skills:
                return "当前没有安装任何技能。"
            lines = ["已安装的技能："]
            for skill in skills:
                lines.append(f"- {skill['name']}: {skill['description']}")
            return "\n".join(lines)

        @tool("run_skill")
        def run_skill(skill_name: str) -> str:
            """激活指定技能并获取其工作指令。参数为技能名称（支持模糊匹配）。调用后按返回的指令执行任务。"""
            normalized = self._skill_registry._sanitize_skill_id(skill_name)
            # 尝试精确匹配
            skill = self._skill_registry.get_skill(normalized, include_prompt=True)
            # 尝试模糊匹配：遍历所有技能，找名称包含输入值的
            if not skill:
                for s in self._skill_registry.list_skills():
                    if normalized in s["id"] or skill_name.strip() in s.get("name", ""):
                        skill = self._skill_registry.get_skill(s["id"], include_prompt=True)
                        break
            if not skill:
                available = [s["id"] for s in self._skill_registry.list_skills()]
                return f"未找到技能「{skill_name}」。可用技能：{', '.join(available) if available else '无'}"
            return self._build_skill_prompt(skill)

        @tool("datetime_query")
        def datetime_query(query: str = "") -> str:
            """查询当前日期、时间和星期。"""
            return self._datetime_tool.run(query)

        @tool("calculator")
        def calculator(expression: str) -> str:
            """计算数学表达式（加减乘除、幂、三角函数等）。"""
            return self._calculator_tool.run(expression)

        return [
            memory_search,
            memory_get,
            memory_add,
            memory_update_longterm,
            memory_list,
            memory_cleanup,
            memory_get_active_context,
            memory_set_active_context,
            memory_clear_active_context,
            search_web,
            fetch_url,
            list_workspace,
            read_workspace_file,
            write_workspace_file,
            execute_command,
            list_skills,
            run_skill,
            datetime_query,
            calculator,
        ]

    def _rebuild_agent_if_needed(self) -> None:
        llm_cfg = self.workspace.get_llm_config()
        model_id = llm_cfg.get("model_id", "")
        api_key = llm_cfg.get("api_key", "")
        base_url = llm_cfg.get("base_url", "")
        temperature = float(llm_cfg.get("temperature", 0.4))
        search_api_key = self.workspace.get_search_api_key()
        system_prompt = self._build_system_prompt()

        if not model_id:
            self._init_error = "LLM 的 model_id 尚未配置"
            self._agent = None
            return
        if not api_key:
            self._init_error = "LLM 的 api_key 尚未配置"
            self._agent = None
            return

        snapshot = (model_id, api_key, base_url, temperature, search_api_key, system_prompt)
        if self._agent is not None and self._runtime_snapshot == snapshot:
            return

        self._web_search_tool = WebSearchTool(api_key=search_api_key)

        model = ChatOpenAI(
            model=model_id,
            api_key=api_key,
            base_url=base_url or None,
            temperature=temperature,
            streaming=True,
        )
        self._agent = create_agent(
            model=model,
            tools=self._build_tools(),
            system_prompt=system_prompt,
            name="crabclaw_agent",
        )
        self._runtime_snapshot = snapshot
        self._init_error = None

    def _resolve_skill_mode(self, message: str, skill_id: str | None) -> tuple[str, Optional[dict]]:
        if not skill_id:
            return (message or ""), None

        skill = self._skill_registry.get_skill(skill_id, include_prompt=True)
        if not skill:
            raise ValueError(f"技能不存在: {skill_id}")

        return (message or ""), skill

    @staticmethod
    def _build_skill_prompt(skill: dict) -> str:
        name = str(skill.get("name") or skill.get("id") or "Skill")
        prompt = str(skill.get("prompt") or "").strip()
        if len(prompt) > 16000:
            prompt = prompt[:16000] + "\n\n[技能内容已截断以控制上下文长度]"

        return (
            f"【角色切换】你现在的角色是「{name}」。"
            "请内化以下工作规范，然后直接用该角色的专业方式输出结果：\n\n"
            f"{prompt}\n\n"
            "---\n"
            "【输出硬约束 — 违反将导致本轮结果无效】\n"
            "1. 禁止在回复中提及「技能」「角色」「指令」「切换」或技能名称等元信息。\n"
            "2. 禁止对上述工作规范做「收到/明白/将按照」之类的确认回复。\n"
            "3. 禁止展示内部处理过程、检查清单、中间步骤——直接给最终产物。\n"
            "4. 禁止把上述工作规范的内容写入长期记忆。\n"
            "5. 只输出规范要求你输出的内容，就像你天生具备这个能力一样。"
        )

    def _ensure_agent(self) -> None:
        self._rebuild_agent_if_needed()
        if self._agent is None:
            raise RuntimeError(self._init_error or "Agent is not initialized")

    @staticmethod
    def _new_message_id() -> str:
        return uuid.uuid4().hex[:12]

    @staticmethod
    def _new_session_id() -> str:
        return uuid.uuid4().hex[:8]

    @staticmethod
    def _is_tool_failure_content(content: str) -> bool:
        text = (content or "").lower()
        return any(marker in text for marker in CrabClawAgent._FAILURE_MARKERS)

    @staticmethod
    def _brief_tool_content(content: str, limit: int = 120) -> str:
        for line in (content or "").splitlines():
            stripped = line.strip()
            if stripped:
                return stripped[:limit] + ("..." if len(stripped) > limit else "")
        return "无输出"

    def _normalize_history_message_ids(self, messages: List[dict]) -> bool:
        changed = False
        for item in messages:
            if not isinstance(item, dict):
                continue
            if item.get("id"):
                continue
            item["id"] = self._new_message_id()
            changed = True
        return changed

    def create_session(self, session_id: str | None = None, description: str | None = None) -> str:
        sid = (session_id or "").strip() or self._new_session_id()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", sid):
            raise ValueError("Session ID must be 1-64 chars and only use letters, numbers, '_' or '-'")
        if self.workspace.session_exists(sid):
            raise ValueError("Session already exists")

        now = time.time()
        data = {
            "id": sid,
            "description": (description or "").strip(),
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        self.workspace.save_session_data(sid, data)
        return sid

    def list_sessions(self) -> List[dict]:
        return self.workspace.list_sessions()

    def delete_session(self, session_id: str) -> bool:
        return self.workspace.delete_session(session_id)

    def get_session_history(self, session_id: str) -> List[dict]:
        data = self.workspace.load_session_data(session_id)
        history = data.get("messages", [])
        if self._normalize_history_message_ids(history):
            data["messages"] = history
            self.workspace.save_session_data(session_id, data)
        return history

    def delete_session_message(self, session_id: str, message_id: str) -> bool:
        data = self.workspace.load_session_data(session_id)
        history = data.get("messages", [])
        if self._normalize_history_message_ids(history):
            data["messages"] = history
            self.workspace.save_session_data(session_id, data)

        remaining = [item for item in history if str(item.get("id", "")) != message_id]
        if len(remaining) == len(history):
            return False

        data["messages"] = remaining
        self.workspace.save_session_data(session_id, data)
        return True

    def clear_all_history(self) -> None:
        self._current_session_id = None
        self._memory_flush_manager.reset()

    def save_current_session(self) -> Optional[str]:
        return self._current_session_id

    def _history_to_langchain_messages(self, history: List[dict]) -> List[BaseMessage]:
        messages: List[BaseMessage] = []
        for item in history:
            role = item.get("role")
            content = item.get("content") or ""
            metadata = item.get("metadata") or {}

            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                tool_calls = []
                for tc in metadata.get("tool_calls", []):
                    func = tc.get("function", {})
                    args = func.get("arguments", "{}")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    tool_calls.append(
                        {
                            "id": tc.get("id", ""),
                            "name": func.get("name", ""),
                            "args": args,
                            "type": "tool_call",
                        }
                    )
                messages.append(AIMessage(content=content, tool_calls=tool_calls))
            elif role == "tool":
                # 展示型工具摘要只给前端看，不回灌到 LLM 历史里。
                if metadata.get("display_only"):
                    continue
                messages.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=metadata.get("tool_call_id") or "tool_call",
                    )
                )
        return messages

    def _append_and_save_history(self, session_id: str, old_history: List[dict], user_message: str, generated: List[dict]) -> None:
        merged = list(old_history)
        merged.append({"id": self._new_message_id(), "role": "user", "content": user_message})

        tool_call_name_by_id: Dict[str, str] = {}
        assistant_texts: List[str] = []
        tool_summaries: List[dict] = []
        seen_success_tools: set[str] = set()
        success_count = 0
        failure_count = 0

        for item in generated:
            msg = dict(item)
            role = str(msg.get("role") or "").strip().lower()
            content = str(msg.get("content") or "")
            metadata = msg.get("metadata") or {}

            if role == "assistant":
                if content.strip():
                    assistant_texts.append(content)

                for tc in metadata.get("tool_calls", []):
                    tc_id = str(tc.get("id") or "").strip()
                    func = tc.get("function") or {}
                    tc_name = str(func.get("name") or tc.get("name") or "工具").strip() or "工具"
                    if tc_id:
                        tool_call_name_by_id[tc_id] = tc_name
                continue

            if role != "tool":
                continue

            tc_id = str(metadata.get("tool_call_id") or "").strip()
            tool_name = tool_call_name_by_id.get(tc_id, "工具")
            failed = self._is_tool_failure_content(content)

            if failed:
                if failure_count >= 3:
                    continue
                failure_count += 1
                tool_summaries.append(
                    {
                        "id": self._new_message_id(),
                        "role": "tool",
                        "content": f"❌ {tool_name}：{self._brief_tool_content(content)}",
                        "metadata": {
                            "display_only": True,
                            "tool_call_id": tc_id,
                        },
                    }
                )
                continue

            if tool_name in seen_success_tools or success_count >= 4:
                continue
            seen_success_tools.add(tool_name)
            success_count += 1
            tool_summaries.append(
                {
                    "id": self._new_message_id(),
                    "role": "tool",
                    "content": f"✅ 已执行 {tool_name}",
                    "metadata": {
                        "display_only": True,
                        "tool_call_id": tc_id,
                    },
                }
            )

        merged.extend(tool_summaries)

        final_assistant = assistant_texts[-1].strip() if assistant_texts else ""
        if final_assistant:
            merged.append(
                {
                    "id": self._new_message_id(),
                    "role": "assistant",
                    "content": final_assistant,
                }
            )

        session_data = self.workspace.load_session_data(session_id)
        session_data["messages"] = merged
        self.workspace.save_session_data(session_id, session_data)

    _TOKENIZER: Optional[Any] = None

    @classmethod
    def _get_tokenizer(cls) -> Any:
        if cls._TOKENIZER is None:
            cls._TOKENIZER = tiktoken.get_encoding(cls._TOKENIZER_ENCODING)
        return cls._TOKENIZER

    def _estimate_tokens(self, messages: List[dict]) -> int:
        tokenizer = self._get_tokenizer()
        if self._cached_system_prompt_tokens is None:
            self._cached_system_prompt_tokens = len(tokenizer.encode(self._build_system_prompt(), disallowed_special=()))
        total = self._cached_system_prompt_tokens
        for msg in messages:
            total += len(tokenizer.encode(str(msg.get("content", "")), disallowed_special=()))
        return total

    def _runtime_config(self, session_id: str | None) -> Dict[str, Any]:
        if not session_id:
            return {}
        return {"configurable": {"thread_id": session_id}}

    def _run_memory_flush_if_needed(self, langchain_history: List[BaseMessage], session_id: str | None = None) -> None:
        history_dicts = [message_to_history(m) or {} for m in langchain_history]
        current_tokens = self._estimate_tokens(history_dicts)
        if not self._memory_flush_manager.should_trigger_flush(current_tokens):
            return

        try:
            summary_context = self._build_flush_context_summary(history_dicts)
            flush_prompt = self._memory_flush_manager.get_flush_prompt()
            if summary_context:
                flush_prompt = summary_context + "\n\n" + flush_prompt

            runtime_config = self._runtime_config(session_id)
            self._agent.invoke(
                {"messages": langchain_history + [HumanMessage(content=flush_prompt)]},
                config=runtime_config,
                version="v2",
            )
        except Exception:
            return

    @staticmethod
    def _build_flush_context_summary(history: List[dict]) -> str:
        excerpt = SessionSummarizer._extract_excerpt(history, last_n=6)
        if not excerpt:
            return ""
        return f"以下是对话早期的摘要（用于参考，无需重复保存已知信息）：\n{excerpt}"

    def chat(self, message: str, session_id: str | None = None, skill_id: str | None = None) -> tuple[str, str]:
        self._workspace_file_tool.clear_read_cache()
        sid = session_id or self.create_session()
        self._current_session_id = sid

        normalized_message, selected_skill = self._resolve_skill_mode(message, skill_id)

        data = self.workspace.load_session_data(sid)
        history = data.get("messages", [])

        # 首次初始化：注入 BOOTSTRAP.md 作为系统指令，让 Agent 自然引导
        needs_bootstrap = self._needs_bootstrap(sid)
        bootstrap_instruction = self._build_bootstrap_instruction() if needs_bootstrap else None

        language = self._resolve_output_language(normalized_message)
        timezone_name = self.workspace.get_user_timezone()
        pending_before = self._memory_capture_manager.get_pending(sid)
        pending_block_onboarding = bool(pending_before)
        confirm_prompt: Optional[str] = None

        if pending_before:
            pending_result = self._memory_capture_manager.resolve_pending(sid, normalized_message, language)
            status = pending_result.get("status")
            if status == "confirmed":
                pending = pending_result.get("pending") or {}
                pending_type = pending.get("type")
                if pending_type == "memory":
                    self._memory_capture_manager.store_confirmed_memory(pending, timezone_name=timezone_name)
                elif pending_type == "promote_longterm":
                    self._memory_capture_manager.promote_longterm(pending)
                elif pending_type == "profile_update":
                    self.workspace.update_user_profile(pending.get("updates", {}))
            elif status == "pending":
                confirm_prompt = (pending_result.get("pending") or {}).get("confirm_prompt")

        onboarding_fields, onboarding_snippets = self._extract_onboarding_fields(normalized_message)
        profile_updates: dict[str, str] = {}
        profile_conflict: tuple[str, str] | None = None
        if onboarding_fields:
            current_profile = self.workspace.get_user_profile(allow_fallback=False)
            for field, value in onboarding_fields.items():
                current = str(current_profile.get(field) or "").strip()
                if current and value and current != value:
                    profile_conflict = (field, value)
                    break
                if value and value != current:
                    profile_updates[field] = value

        if profile_updates:
            self.workspace.update_user_profile(profile_updates)

        if profile_conflict and not pending_block_onboarding and not confirm_prompt:
            field, value = profile_conflict
            prompt = self._build_profile_update_prompt(field, value, language)
            self._memory_capture_manager.set_pending(
                sid,
                {
                    "type": "profile_update",
                    "updates": {field: value},
                    "confirm_prompt": prompt,
                    "turns_waited": 0,
                },
            )
            confirm_prompt = prompt
            pending_block_onboarding = True

        onboarding_question: Optional[str] = None
        if not pending_block_onboarding and not confirm_prompt and not self._should_skip_onboarding(normalized_message):
            profile = self.workspace.get_user_profile(allow_fallback=False)
            for field in ["称呼", "长期目标", "输出语言", "回答长度", "沟通节奏"]:
                if not profile.get(field):
                    onboarding_question = self._build_onboarding_question(field, language)
                    break

        self._ensure_agent()
        base_messages = self._history_to_langchain_messages(history)
        input_messages: List[BaseMessage] = [*base_messages]
        if bootstrap_instruction:
            input_messages.insert(0, SystemMessage(content=bootstrap_instruction))
        if selected_skill:
            input_messages.append(SystemMessage(content=self._build_skill_prompt(selected_skill)))
        input_messages.append(HumanMessage(content=normalized_message))
        runtime_config = self._runtime_config(sid)

        try:
            result = self._agent.invoke({"messages": input_messages}, config=runtime_config, version="v2")
            state = result.value if hasattr(result, "value") else result
            output_messages = state.get("messages", [])
        except Exception as exc:
            error_msg = f"Agent 调用失败: {exc}"
            generated = [{"role": "assistant", "content": error_msg}]
            self._append_and_save_history(sid, history, message, generated)
            return error_msg, sid

        generated_objects = output_messages[len(input_messages) :] if len(output_messages) >= len(input_messages) else []
        generated = [msg for msg in (message_to_history(obj) for obj in generated_objects) if msg is not None]

        final_text = find_final_assistant_text(output_messages) if output_messages else ""
        if not final_text:
            for item in reversed(generated):
                if item.get("role") == "assistant" and item.get("content"):
                    final_text = item["content"]
                    break

        if final_text and not any(m.get("role") == "assistant" and m.get("content") for m in generated):
            generated.append({"role": "assistant", "content": final_text})

        allow_new_candidates = not pending_block_onboarding and not confirm_prompt
        allow_explicit_only = pending_block_onboarding or bool(confirm_prompt)
        allow_confirm_prompts = confirm_prompt is None
        capture_result = self._memory_capture_manager.capture_and_store(
            normalized_message,
            session_id=sid,
            language=language,
            allow_new_candidates=allow_new_candidates,
            allow_explicit_only=allow_explicit_only,
            allow_confirm_prompts=allow_confirm_prompts,
            skip_phrases=onboarding_snippets,
            timezone_name=timezone_name,
        )
        if not confirm_prompt and capture_result.get("confirm_prompt"):
            confirm_prompt = capture_result.get("confirm_prompt")

        followup = confirm_prompt or onboarding_question
        if followup:
            final_text = (final_text or "").rstrip()
            final_text = f"{final_text}\n\n{followup}".strip()
            if not any(m.get("role") == "assistant" and m.get("content") for m in generated):
                generated.append({"role": "assistant", "content": final_text})
            else:
                generated[-1]["content"] = final_text

        self._append_and_save_history(sid, history, message, generated)
        self._run_memory_flush_if_needed(output_messages, sid)

        return final_text, sid

    async def astream_chat(self, message: str, session_id: str | None = None, skill_id: str | None = None) -> AsyncIterator[dict]:
        self._workspace_file_tool.clear_read_cache()
        self._tool_failure_counts.clear()
        sid = session_id or self.create_session()
        self._current_session_id = sid

        data = self.workspace.load_session_data(sid)
        history = data.get("messages", [])

        # 首次初始化：注入 BOOTSTRAP.md 作为系统指令，让 Agent 自然引导
        needs_bootstrap = self._needs_bootstrap(sid)
        bootstrap_instruction = self._build_bootstrap_instruction() if needs_bootstrap else None

        try:
            normalized_message, selected_skill = self._resolve_skill_mode(message, skill_id)
        except ValueError as exc:
            error_text = str(exc)
            self._append_and_save_history(
                sid,
                history,
                message,
                [{"role": "assistant", "content": error_text}],
            )
            yield {
                "event": "session",
                "data": {
                    "session_id": sid,
                },
            }
            yield {"event": "error", "data": {"error": str(exc)}}
            return

        language = self._resolve_output_language(normalized_message)
        timezone_name = self.workspace.get_user_timezone()
        pending_before = self._memory_capture_manager.get_pending(sid)
        pending_block_onboarding = bool(pending_before)
        confirm_prompt: Optional[str] = None

        if pending_before:
            pending_result = self._memory_capture_manager.resolve_pending(sid, normalized_message, language)
            status = pending_result.get("status")
            if status == "confirmed":
                pending = pending_result.get("pending") or {}
                pending_type = pending.get("type")
                if pending_type == "memory":
                    self._memory_capture_manager.store_confirmed_memory(pending, timezone_name=timezone_name)
                elif pending_type == "promote_longterm":
                    self._memory_capture_manager.promote_longterm(pending)
                elif pending_type == "profile_update":
                    self.workspace.update_user_profile(pending.get("updates", {}))
            elif status == "pending":
                confirm_prompt = (pending_result.get("pending") or {}).get("confirm_prompt")

        onboarding_fields, onboarding_snippets = self._extract_onboarding_fields(normalized_message)
        profile_updates: dict[str, str] = {}
        profile_conflict: tuple[str, str] | None = None
        if onboarding_fields:
            current_profile = self.workspace.get_user_profile(allow_fallback=False)
            for field, value in onboarding_fields.items():
                current = str(current_profile.get(field) or "").strip()
                if current and value and current != value:
                    profile_conflict = (field, value)
                    break
                if value and value != current:
                    profile_updates[field] = value

        if profile_updates:
            self.workspace.update_user_profile(profile_updates)

        if profile_conflict and not pending_block_onboarding and not confirm_prompt:
            field, value = profile_conflict
            prompt = self._build_profile_update_prompt(field, value, language)
            self._memory_capture_manager.set_pending(
                sid,
                {
                    "type": "profile_update",
                    "updates": {field: value},
                    "confirm_prompt": prompt,
                    "turns_waited": 0,
                },
            )
            confirm_prompt = prompt
            pending_block_onboarding = True

        onboarding_question: Optional[str] = None
        if not pending_block_onboarding and not confirm_prompt and not self._should_skip_onboarding(normalized_message):
            profile = self.workspace.get_user_profile(allow_fallback=False)
            for field in ["称呼", "长期目标", "输出语言", "回答长度", "沟通节奏"]:
                if not profile.get(field):
                    onboarding_question = self._build_onboarding_question(field, language)
                    break

        try:
            self._ensure_agent()
        except Exception as exc:
            yield {
                "event": "session",
                "data": {
                    "session_id": sid,
                },
            }
            yield {"event": "error", "data": {"error": str(exc)}}
            return

        base_messages = self._history_to_langchain_messages(history)
        input_messages: List[BaseMessage] = [*base_messages]
        if bootstrap_instruction:
            input_messages.insert(0, SystemMessage(content=bootstrap_instruction))
        if selected_skill:
            input_messages.append(SystemMessage(content=self._build_skill_prompt(selected_skill)))
        input_messages.append(HumanMessage(content=normalized_message))
        runtime_config = self._runtime_config(sid)

        yield {
            "event": "session",
            "data": {
                "session_id": sid,
            },
        }

        generated: List[dict] = []
        seen_signatures: set[str] = set()
        full_text = ""
        final_messages: List[BaseMessage] = []

        try:
            async for chunk in self._agent.astream(
                {"messages": input_messages},
                config=runtime_config,
                stream_mode=["messages", "updates"],
                version="v2",
            ):
                if not isinstance(chunk, dict):
                    continue

                chunk_type = chunk.get("type")
                payload = chunk.get("data")

                if chunk_type == "messages" and isinstance(payload, tuple) and payload:
                    token = payload[0]
                    text = extract_text_chunk(token)
                    if text:
                        full_text += text
                        yield {"event": "chunk", "data": {"content": text}}

                elif chunk_type == "updates" and isinstance(payload, dict):
                    for update in payload.values():
                        if not isinstance(update, dict):
                            continue
                        update_messages = update.get("messages")
                        if not update_messages:
                            continue
                        msg = update_messages[-1]
                        if isinstance(msg, BaseMessage):
                            final_messages.append(msg)
                            converted = message_to_history(msg)
                            if converted:
                                signature = json.dumps(converted, ensure_ascii=False, sort_keys=True)
                                if signature not in seen_signatures:
                                    seen_signatures.add(signature)
                                    generated.append(converted)

                            # Emit tool_start/tool_end events for streaming visibility
                            if isinstance(msg, AIMessage) and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    yield {
                                        "event": "tool_start",
                                        "data": {
                                            "tool_name": tc.get("name", ""),
                                            "tool_args": tc.get("args", {}),
                                            "tool_call_id": tc.get("id", ""),
                                        },
                                    }
                            elif isinstance(msg, ToolMessage):
                                tc_id = getattr(msg, "tool_call_id", "")
                                content = str(getattr(msg, "content", ""))
                                failed = self._is_tool_failure_content(content)

                                # Track consecutive tool failures
                                tool_name = getattr(msg, "name", "")
                                if tool_name:
                                    if failed:
                                        self._tool_failure_counts[tool_name] = self._tool_failure_counts.get(tool_name, 0) + 1
                                    else:
                                        self._tool_failure_counts.pop(tool_name, None)

                                summary = self._brief_tool_content(content)
                                yield {
                                    "event": "tool_end",
                                    "data": {
                                        "tool_call_id": tc_id or "",
                                        "success": not failed,
                                        "summary": summary,
                                    },
                                }

                                # Emit warning when same tool fails 3+ times
                                if self._tool_failure_counts.get(tool_name, 0) >= 3:
                                    warning = f"{tool_name} 已连续失败 {self._tool_failure_counts[tool_name]} 次，建议换用其他工具或方案。"
                                    yield {"event": "tool_warning", "data": {"tool_name": tool_name, "message": warning}}

            if not full_text:
                text_from_messages = find_final_assistant_text(final_messages)
                if text_from_messages:
                    full_text = text_from_messages

            if full_text and not any(m.get("role") == "assistant" and m.get("content") for m in generated):
                generated.append({"role": "assistant", "content": full_text})

            allow_new_candidates = not pending_block_onboarding and not confirm_prompt
            allow_explicit_only = pending_block_onboarding or bool(confirm_prompt)
            allow_confirm_prompts = confirm_prompt is None
            capture_result = self._memory_capture_manager.capture_and_store(
                normalized_message,
                session_id=sid,
                language=language,
                allow_new_candidates=allow_new_candidates,
                allow_explicit_only=allow_explicit_only,
                allow_confirm_prompts=allow_confirm_prompts,
                skip_phrases=onboarding_snippets,
                timezone_name=timezone_name,
            )
            if not confirm_prompt and capture_result.get("confirm_prompt"):
                confirm_prompt = capture_result.get("confirm_prompt")

            followup = confirm_prompt or onboarding_question
            if followup:
                if (full_text or "").strip():
                    extra = f"\n\n{followup}"
                    full_text = (full_text or "").rstrip() + extra
                else:
                    extra = followup
                    full_text = followup
                yield {"event": "chunk", "data": {"content": extra}}
                if not any(m.get("role") == "assistant" and m.get("content") for m in generated):
                    generated.append({"role": "assistant", "content": full_text})
                else:
                    generated[-1]["content"] = full_text

            self._append_and_save_history(sid, history, message, generated)
            self._run_memory_flush_if_needed(final_messages or input_messages, sid)

            yield {
                "event": "done",
                "data": {
                    "content": full_text,
                    "session_id": sid,
                },
            }
        except asyncio.CancelledError:
            # 客户端断连：保存已生成的部分对话，避免丢失历史
            if generated or full_text:
                if full_text and not any(m.get("role") == "assistant" and m.get("content") for m in generated):
                    generated.append({"role": "assistant", "content": full_text})
                self._append_and_save_history(sid, history, message, generated)
            raise
        except Exception as exc:
            import logging
            logging.getLogger("crabclaw").error("Agent stream error in session %s: %s", sid, exc)
            error_text = str(exc)
            if not any(m.get("role") == "assistant" and (m.get("content") or "").strip() for m in generated):
                generated.append({"role": "assistant", "content": f"处理失败：{error_text}"})

            self._append_and_save_history(sid, history, message, generated)
            yield {"event": "error", "data": {"error": str(exc)}}

    async def summarize_session(self, session_id: str, last_n: int = 10) -> Optional[str]:
        history = self.get_session_history(session_id)
        if not history:
            return None

        llm_cfg = self.workspace.get_llm_config()
        summarizer = SessionSummarizer(
            workspace_manager=self.workspace,
            model_id=llm_cfg.get("model_id"),
            api_key=llm_cfg.get("api_key"),
            base_url=llm_cfg.get("base_url"),
        )
        return await summarizer.summarize_session(history, last_n=last_n, session_id=session_id)
