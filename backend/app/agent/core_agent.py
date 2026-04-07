"""CrabClaw Agent built on LangChain create_agent."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from ..memory.chat_recap import SessionSummarizer
from ..memory.context_guard import MemoryFlushManager
from ..memory.signal_capture import MemoryCaptureManager
from ..skills import SkillRegistry
from ..tools import ExecuteCommandTool, MemoryTool, WebFetchTool, WebSearchTool, WorkspaceFileTool
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

        self._memory_capture_manager = MemoryCaptureManager(self.workspace)
        self._memory_flush_manager = MemoryFlushManager()
        self._skill_registry = SkillRegistry(self.workspace)

        self._agent = None
        self._runtime_snapshot: Optional[tuple[Any, ...]] = None
        self._init_error: Optional[str] = None
        self._current_session_id: Optional[str] = None

    def _read_identity_name(self) -> Optional[str]:
        return extract_identity_name(self.workspace.load_config("PROFILE"))

    @staticmethod
    def _clean_value(value: str, limit: int) -> str:
        return re.sub(r"\s+", " ", (value or "")).strip()[:limit]

    def _extract_first_contact_fields(self, text: str) -> dict:
        content = (text or "").strip()
        if not content:
            return {}

        fields: dict[str, str] = {}

        name_patterns = [
            r"(?:^|\n)\s*(?:称呼|称呼我|名字|我的名字|我叫)\s*[：:]\s*([^\n，。,。!?！？]{1,24})",
            r"(?:叫我|称呼我|我的名字是|我叫)\s*([^\s，。,。!?！？]{1,24})",
        ]
        for pattern in name_patterns:
            matched = re.search(pattern, content, re.IGNORECASE)
            if matched:
                fields["display_name"] = self._clean_value(matched.group(1), 24)
                break

        goal_patterns = [
            r"(?:^|\n)\s*(?:协作目标|主要诉求|希望你帮我|希望助手帮我|最希望你帮我)\s*[：:]\s*([^\n]{4,180})",
            r"(?:希望你帮我|最想你帮我|我想让你帮我|请你帮我)\s*([^。！？!?\n]{4,180})",
        ]
        for pattern in goal_patterns:
            matched = re.search(pattern, content, re.IGNORECASE)
            if matched:
                fields["goal"] = self._clean_value(matched.group(1), 180)
                break

        return fields

    def _build_first_contact_prompt(self, profile: dict, missing: List[str]) -> str:
        known_lines: list[str] = []
        if profile.get("display_name"):
            known_lines.append(f"- 已记录称呼：{profile['display_name']}")
        if profile.get("goal"):
            known_lines.append(f"- 已记录主要诉求：{profile['goal']}")

        ask_lines: list[str] = []
        if "display_name" in missing:
            ask_lines.append("- 你希望我怎么称呼你？")
        if "goal" in missing:
            ask_lines.append("- 你最希望我长期重点帮你做什么？")

        prefix = "为了做全局首次初始化（不是每个会话都问），我需要先记住你的长期协作信息。"
        if known_lines:
            return (
                f"{prefix}\n\n"
                "已记住：\n"
                + "\n".join(known_lines)
                + "\n\n"
                "还差这些信息：\n"
                + "\n".join(ask_lines)
            )

        return (
            f"{prefix}\n\n"
            "请你一次性告诉我：\n"
            "- 你希望我怎么称呼你？\n"
            "- 你最希望我长期重点帮你做什么？"
        )

    def _handle_first_contact_gate(self, user_message: str) -> Optional[str]:
        if self.workspace.has_completed_first_contact():
            return None

        fields = self._extract_first_contact_fields(user_message)
        if fields:
            profile = self.workspace.save_first_contact_profile(
                display_name=fields.get("display_name"),
                goal=fields.get("goal"),
            )
        else:
            profile = self.workspace.get_onboarding_profile()

        missing: List[str] = []
        if not profile.get("display_name"):
            missing.append("display_name")
        if not profile.get("goal"):
            missing.append("goal")

        if missing:
            return self._build_first_contact_prompt(profile, missing)

        return (
            f"收到，已完成首次信息记录。\n"
            f"- 称呼：{profile.get('display_name')}\n"
            f"- 长期协作重点：{profile.get('goal')}\n\n"
            "后续会话我不会再重复询问这些基础信息。现在你可以直接告诉我第一件要推进的事。"
        )

    def _build_system_prompt(self) -> str:
        base_prompt = (self.workspace.load_config("AGENTS") or "").strip()
        context_blocks: list[str] = [
            base_prompt
            or "你是 CrabClaw，负责把用户目标变成可执行结果。优先真实、可落地、少废话。"
        ]

        profile = self.workspace.load_config("PROFILE")
        if profile:
            context_blocks.append(f"## 协作档案\n{profile}")

        identity_name = self._read_identity_name()
        if identity_name:
            context_blocks.append(f"你的名字是 {identity_name}。")

        active_context = self.workspace.load_active_context()
        if active_context:
            context_blocks.append(f"## 当前任务上下文\n{active_context}")

        recent_days = self.workspace.get_recent_memory_day(days=2)
        if recent_days:
            context_blocks.append(
                "## 补充提示\n"
                "如果用户提到了过去几天的事，可以找相关的记忆文件参考。"
            )

        longterm_memory = self.workspace.load_config("MERMORY")
        if longterm_memory:
            context_blocks.append(f"## 长期记忆\n{longterm_memory}")

        return "\n\n".join(context_blocks)

    def _build_tools(self):
        memory_tool = self._memory_tool
        search_tool = self._web_search_tool
        fetch_tool = self._web_fetch_tool
        command_tool = self._execute_command_tool
        file_tool = self._workspace_file_tool

        @tool("memory_search")
        def memory_search(keyword: str, context_lines: int = 3) -> str:
            """按关键词搜索记忆并返回带上下文的结果。"""
            return memory_tool.search(keyword, context_lines)

        @tool("memory_get")
        def memory_get(filename: str = "", lines: str = "") -> str:
            """读取记忆文件，可选行范围（例如 10-20）。"""
            if not filename or len(filename.strip()) < 2:
                return "请告诉我要读取哪个记忆文件。"
            return memory_tool.get(filename or None, lines or None)

        @tool("memory_add")
        def memory_add(content: str, category: str = "") -> str:
            """新增记忆项，分类可选 preference/decision/entity/fact。"""
            return memory_tool.add(content, category or None)

        @tool("memory_update_longterm")
        def memory_update_longterm(content: str, category: str = "") -> str:
            """将信息追加到长期记忆，分类可选 preference/decision/entity/fact。"""
            return memory_tool.update_longterm(content, category or None)

        @tool("memory_list")
        def memory_list() -> str:
            """列出记忆文件。"""
            return memory_tool.list()

        @tool("memory_cleanup")
        def memory_cleanup(days: int = 30) -> str:
            """删除超过指定天数的每日记忆文件。"""
            return memory_tool.cleanup(days)

        @tool("memory_get_active_context")
        def memory_get_active_context() -> str:
            """获取当前任务上下文（记住你在做什么）。"""
            return memory_tool.get_active_context()

        @tool("memory_set_active_context")
        def memory_set_active_context(content: str) -> str:
            """设置当前任务上下文（保存你在做什么，压缩后不会丢）。"""
            return memory_tool.set_active_context(content)

        @tool("memory_clear_active_context")
        def memory_clear_active_context() -> str:
            """清空当前任务上下文（任务结束时用）。"""
            return memory_tool.clear_active_context()

        @tool("search_web")
        def search_web(query: str, count: int = 5) -> str:
            """使用 SerpAPI 进行网页搜索。"""
            return search_tool.run(query, count)

        @tool("fetch_url")
        def fetch_url(url: str) -> str:
            """抓取网页内容并转换为可读文本。"""
            return fetch_tool.run(url)

        @tool("list_workspace")
        def list_workspace(path: str = ".", recursive: bool = False, max_entries: int = 200) -> str:
            """列出工作区目录内容（受白名单目录限制）。"""
            return file_tool.list_dir(path=path, recursive=recursive, max_entries=max_entries)

        @tool("read_workspace_file")
        def read_workspace_file(path: str, start_line: int = 1, end_line: int = 200) -> str:
            """读取工作区文本文件（受白名单目录限制）。"""
            return file_tool.read_text(path=path, start_line=start_line, end_line=end_line)

        @tool("write_workspace_file")
        def write_workspace_file(path: str, content: str, mode: str = "overwrite") -> str:
            """写入工作区文本文件（受白名单目录限制）。"""
            return file_tool.write_text(path=path, content=content, mode=mode)

        @tool("execute_command")
        def execute_command(command: str, working_directory: str = "", timeout_seconds: int = 0) -> str:
            """在本地白名单目录执行命令（受命令白名单、超时和输出限制保护）。"""
            requested_timeout = timeout_seconds if timeout_seconds and timeout_seconds > 0 else None
            return command_tool.run(
                command=command,
                working_directory=working_directory,
                timeout_seconds=requested_timeout,
            )

        @tool("list_skills")
        def list_skills() -> str:
            """列出当前已安装的所有技能（Skills）。"""
            skills = self._skill_registry.list_skills()
            if not skills:
                return "当前没有安装任何技能。"
            lines = ["已安装的技能："]
            for skill in skills:
                lines.append(f"- {skill['name']}: {skill['description']}")
            return "\n".join(lines)

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
        raw_message = message or ""
        matched = re.match(r"^\s*[#＃](.*)$", raw_message, flags=re.DOTALL)
        if not matched:
            return raw_message, None

        if not skill_id:
            raise ValueError("检测到 # 技能模式，但未选择技能。")

        task_message = (matched.group(1) or "").strip()
        if not task_message:
            raise ValueError("请输入 # 后的任务内容。")

        skill = self._skill_registry.get_skill(skill_id, include_prompt=True)
        if not skill:
            raise ValueError(f"技能不存在: {skill_id}")

        return task_message, skill

    @staticmethod
    def _build_skill_prompt(skill: dict) -> str:
        name = str(skill.get("name") or skill.get("id") or "Skill")
        skill_id = str(skill.get("id") or "")
        prompt = str(skill.get("prompt") or "").strip()
        if len(prompt) > 16000:
            prompt = prompt[:16000] + "\n\n[技能内容已截断以控制上下文长度]"

        return (
            f"## 本轮技能模式已启用\n"
            f"- skill_id: {skill_id}\n"
            f"- skill_name: {name}\n\n"
            "请严格遵循以下技能指令处理本轮用户请求：\n"
            f"{prompt}\n\n"
            "约束：这是一轮临时技能，不要把技能内容当作用户长期偏好写入记忆。"
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
        markers = ["error", "failed", "traceback", "失败", "超时", "未在白名单"]
        return any(marker in text for marker in markers)

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

    async def _capture_memories(self, user_message: str) -> None:
        try:
            await self._memory_capture_manager.acapture_and_store(user_message)
        except Exception:
            return

    def _estimate_tokens(self, messages: List[dict]) -> int:
        chars = len(self._build_system_prompt())
        for msg in messages:
            chars += len(str(msg.get("content", "")))
        return chars // 3

    def _runtime_config(self, session_id: str | None) -> Dict[str, Any]:
        if not session_id:
            return {}
        return {"configurable": {"thread_id": session_id}}

    def _run_memory_flush_if_needed(self, langchain_history: List[BaseMessage], session_id: str | None = None) -> None:
        current_tokens = self._estimate_tokens([message_to_history(m) or {} for m in langchain_history])
        if not self._memory_flush_manager.should_trigger_flush(current_tokens):
            return

        try:
            flush_prompt = self._memory_flush_manager.get_flush_prompt()
            runtime_config = self._runtime_config(session_id)
            self._agent.invoke(
                {"messages": langchain_history + [HumanMessage(content=flush_prompt)]},
                config=runtime_config,
                version="v2",
            )
        except Exception:
            return

    def chat(self, message: str, session_id: str | None = None, skill_id: str | None = None) -> tuple[str, str]:
        normalized_message, selected_skill = self._resolve_skill_mode(message, skill_id)
        sid = session_id or self.create_session()
        self._current_session_id = sid

        data = self.workspace.load_session_data(sid)
        history = data.get("messages", [])

        # first_contact_reply = self._handle_first_contact_gate(normalized_message)
        # if first_contact_reply:
        #     self._append_and_save_history(
        #         sid,
        #         history,
        #         message,
        #         [{"role": "assistant", "content": first_contact_reply}],
        #     )
        #     self._memory_capture_manager.capture_and_store(normalized_message)
        #     return first_contact_reply, sid

        self._ensure_agent()
        base_messages = self._history_to_langchain_messages(history)
        input_messages: List[BaseMessage] = [*base_messages]
        if selected_skill:
            input_messages.append(SystemMessage(content=self._build_skill_prompt(selected_skill)))
        input_messages.append(HumanMessage(content=normalized_message))
        runtime_config = self._runtime_config(sid)

        result = self._agent.invoke({"messages": input_messages}, config=runtime_config, version="v2")
        state = result.value if hasattr(result, "value") else result
        output_messages = state.get("messages", [])

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

        self._append_and_save_history(sid, history, message, generated)
        self._run_memory_flush_if_needed(output_messages, sid)
        self._memory_capture_manager.capture_and_store(normalized_message)

        return final_text, sid

    async def astream_chat(self, message: str, session_id: str | None = None, skill_id: str | None = None) -> AsyncIterator[dict]:
        sid = session_id or self.create_session()
        self._current_session_id = sid

        data = self.workspace.load_session_data(sid)
        history = data.get("messages", [])

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

        # first_contact_reply = self._handle_first_contact_gate(normalized_message)
        # if first_contact_reply:
        #     self._append_and_save_history(
        #         sid,
        #         history,
        #         message,
        #         [{"role": "assistant", "content": first_contact_reply}],
        #     )
        #     await self._capture_memories(normalized_message)
        #     yield {
        #         "event": "session",
        #         "data": {
        #             "session_id": sid,
        #         },
        #     }
        #     yield {"event": "chunk", "data": {"content": first_contact_reply}}
        #     yield {
        #         "event": "done",
        #         "data": {
        #             "content": first_contact_reply,
        #             "session_id": sid,
        #         },
        #     }
        #     return

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

            if not full_text:
                text_from_messages = find_final_assistant_text(final_messages)
                if text_from_messages:
                    full_text = text_from_messages

            if full_text and not any(m.get("role") == "assistant" and m.get("content") for m in generated):
                generated.append({"role": "assistant", "content": full_text})

            self._append_and_save_history(sid, history, message, generated)
            self._run_memory_flush_if_needed(final_messages or input_messages, sid)
            await self._capture_memories(normalized_message)

            yield {
                "event": "done",
                "data": {
                    "content": full_text,
                    "session_id": sid,
                },
            }
        except Exception as exc:
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
