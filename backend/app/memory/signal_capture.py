"""Rule-based memory capture manager (accuracy-first)."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - fallback for older Python
    ZoneInfo = None


EXPLICIT_MEMORY_PATTERNS = re.compile(r"(请记住|记住一下|记住|长期记住|一直记住|以后都这样)", re.IGNORECASE)
PREFERENCE_PATTERNS = re.compile(r"(prefer|like|love|hate|我喜欢|我偏好|我不喜欢|讨厌)", re.IGNORECASE)
DECISION_PATTERNS = re.compile(r"(decide|decision|决定了|决定|选定|确定用|就用)", re.IGNORECASE)
IDENTITY_PATTERNS = re.compile(r"(my name is|i am|我的名字|我叫|称呼我|叫我)", re.IGNORECASE)

SENSITIVE_KEYWORDS = re.compile(r"(银行卡|身份证|地址|住址|账号|密码|支付|信用卡|卡号|邮箱|邮件|手机号|电话)")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PATTERN = re.compile(r"(\+?\d[\d\- ]{7,}\d)")
ID_PATTERN = re.compile(r"\b\d{15}\b|\b\d{17}[0-9Xx]\b")

CONFIRM_POSITIVE = ["是", "对", "好的", "可以", "yes", "ok"]
CONFIRM_NEGATIVE = ["不是", "不对", "不用", "别", "不要", "no"]


class MemoryCaptureManager:
    def __init__(self, workspace_manager):
        self.workspace = workspace_manager
        self._pending_by_session: dict[str, dict] = {}

    def get_pending(self, session_id: str) -> Optional[dict]:
        return self._pending_by_session.get(session_id)

    def clear_pending(self, session_id: str) -> None:
        self._pending_by_session.pop(session_id, None)

    def set_pending(self, session_id: str, payload: dict) -> None:
        if not session_id or not payload:
            return
        self._pending_by_session[session_id] = payload

    def reset(self) -> None:
        self._pending_by_session.clear()

    def resolve_pending(self, session_id: str, user_text: str, language: str) -> dict:
        pending = self._pending_by_session.get(session_id)
        if not pending:
            return {"status": "none"}

        if not self._is_effective_user_message(user_text):
            return {"status": "pending", "pending": pending, "counted": False}

        verdict = self._match_confirmation(user_text, language)
        if verdict == "deny":
            self._pending_by_session.pop(session_id, None)
            return {"status": "denied", "pending": pending, "counted": True}

        if verdict == "confirm":
            self._pending_by_session.pop(session_id, None)
            return {"status": "confirmed", "pending": pending, "counted": True}

        pending["turns_waited"] = int(pending.get("turns_waited", 0)) + 1
        if pending["turns_waited"] >= 2:
            self._pending_by_session.pop(session_id, None)
            return {"status": "expired", "pending": pending, "counted": True}

        return {"status": "pending", "pending": pending, "counted": True}

    def capture_and_store(
        self,
        text: str,
        session_id: str,
        language: str,
        allow_new_candidates: bool = True,
        allow_explicit_only: bool = False,
        allow_confirm_prompts: bool = True,
        skip_phrases: Optional[List[str]] = None,
        date: datetime | None = None,
        timezone_name: str | None = None,
    ) -> dict:
        cleaned_text = self._strip_phrases(text, skip_phrases or [])

        explicit_candidate = self._extract_explicit_candidate(cleaned_text)
        if explicit_candidate:
            return self._store_explicit_candidate(
                explicit_candidate,
                date,
                timezone_name,
                session_id,
                language,
                allow_confirm_prompts=allow_confirm_prompts,
            )

        if not allow_new_candidates or allow_explicit_only:
            return {"status": "skipped"}

        if not allow_confirm_prompts:
            return {"status": "skipped"}

        candidate = self._extract_candidate(cleaned_text)
        if not candidate:
            return {"status": "skipped"}

        if self.workspace.check_duplicate_memory(candidate["content"], threshold=0.7):
            return {"status": "duplicate"}

        prompt = self._build_confirm_prompt(candidate["content"], language)
        self._pending_by_session[session_id] = {
            "type": "memory",
            "content": candidate["content"],
            "category": candidate["category"],
            "explicit": False,
            "sensitive": candidate.get("sensitive", False),
            "raw_requested": candidate.get("raw_requested", False),
            "longterm": candidate.get("longterm", False),
            "confirm_prompt": prompt,
            "turns_waited": 0,
        }
        return {"status": "pending", "confirm_prompt": prompt}

    def store_confirmed_memory(
        self,
        pending: dict,
        date: datetime | None = None,
        timezone_name: str | None = None,
    ) -> None:
        if pending.get("type") != "memory":
            return

        pending["confirmed"] = True

        content = self._prepare_storage_content(
            pending.get("content", ""),
            pending.get("sensitive", False),
            pending.get("raw_requested", False),
        )
        if not content:
            return

        tags = ["confirmed"]
        if pending.get("explicit"):
            tags.append("explicit")
        if pending.get("sensitive"):
            tags.append("sensitive")

        self.workspace.append_classified_memory(
            content=content,
            category=pending.get("category", "fact"),
            date=date,
            tags=tags,
        )

        self._maybe_promote_longterm(
            content,
            pending.get("category", "fact"),
            pending,
            timezone_name,
        )

    def promote_longterm(self, pending: dict) -> None:
        if pending.get("type") != "promote_longterm":
            return
        content = pending.get("content") or ""
        if not content:
            return
        self.workspace.append_to_longterm_memory(content, pending.get("category", "fact"))

    def analyze_conversation(self, messages: List[dict]) -> List[dict]:
        all_memories: List[dict] = []
        for msg in messages:
            if msg.get("role") == "user" and msg.get("content"):
                candidate = self._extract_candidate(str(msg["content"]))
                if candidate:
                    all_memories.append(candidate)
        return all_memories

    @staticmethod
    def _strip_phrases(text: str, phrases: List[str]) -> str:
        cleaned = text or ""
        for phrase in phrases:
            if phrase:
                cleaned = cleaned.replace(phrase, " ")
        return cleaned

    @staticmethod
    def _is_effective_user_message(text: str) -> bool:
        return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", text or ""))

    @staticmethod
    def _match_confirmation(text: str, language: str) -> str:
        normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", (text or "").lower())

        def contains_word(word: str) -> bool:
            return re.search(rf"\b{re.escape(word)}\b", normalized) is not None

        for token in CONFIRM_NEGATIVE:
            if token.isascii():
                if contains_word(token):
                    return "deny"
            elif token in normalized:
                return "deny"

        for token in CONFIRM_POSITIVE:
            if token.isascii():
                if contains_word(token):
                    return "confirm"
            elif token in normalized:
                return "confirm"

        return "none"

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        return [s.strip() for s in re.split(r"[。！？；.!?;]\s*|\n+", text or "") if s.strip()]

    @staticmethod
    def _merge_short_sentences(sentences: List[str]) -> List[str]:
        connectors = ("并且", "另外", "同时", "而且")
        merged: List[str] = []
        idx = 0
        while idx < len(sentences):
            current = sentences[idx]
            if idx + 1 < len(sentences):
                nxt = sentences[idx + 1]
                if (
                    len(current) <= 40
                    and len(nxt) <= 40
                    and len(current) + len(nxt) <= 80
                    and (nxt.startswith(connectors) or any(connector in nxt[:4] for connector in connectors))
                ):
                    current = f"{current}，{nxt}"
                    idx += 1
            merged.append(current)
            idx += 1
        return merged

    def _extract_explicit_candidate(self, text: str) -> Optional[dict]:
        if not EXPLICIT_MEMORY_PATTERNS.search(text or ""):
            return None

        match = re.search(r"(?:请记住|记住一下|记住)\s*(?:：|:)?\s*(.+)$", text or "")
        content = (match.group(1) if match else "").strip()
        if not content:
            return None

        candidate = {
            "content": content,
            "category": self._infer_category(content),
            "explicit": True,
            "longterm": bool(re.search(r"长期|一直|以后都", text or "")),
        }
        sensitive, raw_requested = self._detect_sensitive(content, text or "")
        candidate["sensitive"] = sensitive
        candidate["raw_requested"] = raw_requested
        return candidate

    def _extract_candidate(self, text: str) -> Optional[dict]:
        sentences = self._merge_short_sentences(self._split_sentences(text))
        best: Optional[dict] = None
        best_priority = 99

        for sentence in sentences:
            if len(sentence) < 5:
                continue
            if self._should_exclude(sentence):
                continue

            category = self._infer_category(sentence)
            priority = 2
            if category in {"preference", "decision", "entity"}:
                priority = 1

            if priority < best_priority:
                sensitive, raw_requested = self._detect_sensitive(sentence, sentence)
                best = {
                    "content": sentence.strip(),
                    "category": category,
                    "explicit": False,
                    "sensitive": sensitive,
                    "raw_requested": raw_requested,
                    "longterm": False,
                }
                best_priority = priority

        if not best:
            return None

        if best_priority == 2 and not re.search(r"[\u4e00-\u9fffA-Za-z]", best["content"]):
            return None

        return best

    @staticmethod
    def _infer_category(text: str) -> str:
        if PREFERENCE_PATTERNS.search(text or ""):
            return "preference"
        if DECISION_PATTERNS.search(text or ""):
            return "decision"
        if IDENTITY_PATTERNS.search(text or ""):
            return "entity"
        return "fact"

    @staticmethod
    def _should_exclude(sentence: str) -> bool:
        if re.search(r"(可能|也许|猜测|推测)", sentence):
            return True
        if re.search(r"(今天|明天|刚刚|现在|临时|这次|一次)", sentence) and len(sentence) < 20:
            return True
        if re.search(r"(心情|难受|郁闷|生气|烦|崩溃|开心)", sentence):
            return True
        if "```" in sentence:
            return True
        return False

    @staticmethod
    def _detect_sensitive(content: str, raw_text: str) -> tuple[bool, bool]:
        sensitive = False
        if EMAIL_PATTERN.search(content) or PHONE_PATTERN.search(content) or ID_PATTERN.search(content):
            sensitive = True
        if SENSITIVE_KEYWORDS.search(content):
            sensitive = True
        if SENSITIVE_KEYWORDS.search(raw_text):
            sensitive = True

        raw_requested = bool(re.search(r"(原文保存|原样保存|不要脱敏|不脱敏)", raw_text))
        return sensitive, raw_requested

    def _prepare_storage_content(self, content: str, sensitive: bool, raw_requested: bool) -> str:
        text = (content or "").strip()
        if not text:
            return ""
        if not sensitive or raw_requested:
            return text

        masked = text
        masked = EMAIL_PATTERN.sub(self._mask_email, masked)
        masked = PHONE_PATTERN.sub(self._mask_phone, masked)
        masked = ID_PATTERN.sub(self._mask_id, masked)
        if SENSITIVE_KEYWORDS.search(masked):
            masked = self._mask_address(masked)
        if len(masked) < 6:
            return masked[-2:]
        return masked

    @staticmethod
    def _mask_email(match: re.Match) -> str:
        email = match.group(0)
        local, _, domain = email.partition("@")
        prefix = local[:2]
        return f"{prefix}***@{domain}"

    @staticmethod
    def _mask_phone(match: re.Match) -> str:
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) <= 4:
            return "*" * len(digits)
        return f"***{digits[-4:]}"

    @staticmethod
    def _mask_id(match: re.Match) -> str:
        raw = match.group(0)
        if len(raw) <= 4:
            return "*" * len(raw)
        return f"***{raw[-4:]}"

    @staticmethod
    def _mask_address(text: str) -> str:
        if len(text) <= 6:
            return text[-2:]
        markers = [text.rfind("市"), text.rfind("区"), text.rfind("县")]
        idx = max(markers)
        prefix = text[: idx + 1] if idx >= 0 else ""
        suffix = text[-6:]
        if prefix:
            return f"{prefix}…{suffix}"
        return f"…{suffix}"

    @staticmethod
    def _summarize(text: str, limit: int = 60) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        return cleaned[:limit] + ("..." if len(cleaned) > limit else "")

    def _build_confirm_prompt(self, content: str, language: str) -> str:
        snippet = self._summarize(content)
        if language == "en":
            return f"Please confirm if I should remember this: \"{snippet}\""
        return f"请确认要记住这条信息吗？“{snippet}”"

    def _store_explicit_candidate(
        self,
        candidate: dict,
        date: datetime | None,
        timezone_name: str | None,
        session_id: str,
        language: str,
        allow_confirm_prompts: bool = True,
    ) -> dict:
        if candidate.get("sensitive") and self._needs_sensitive_content(candidate.get("content", "")):
            prompt = self._build_sensitive_content_prompt(language)
            return {"status": "need_content", "confirm_prompt": prompt}
        content = self._prepare_storage_content(
            candidate.get("content", ""),
            candidate.get("sensitive", False),
            candidate.get("raw_requested", False),
        )
        if not content:
            return {"status": "skipped"}

        if self.workspace.check_duplicate_memory(content, threshold=0.7):
            return {"status": "duplicate"}

        tags = ["explicit"]
        if candidate.get("sensitive"):
            tags.append("sensitive")

        self.workspace.append_classified_memory(
            content=content,
            category=candidate.get("category", "fact"),
            date=date,
            tags=tags,
        )

        if candidate.get("sensitive") and candidate.get("longterm") and allow_confirm_prompts:
            prompt = self._build_sensitive_longterm_prompt(content, language)
            self._pending_by_session[session_id] = {
                "type": "promote_longterm",
                "content": content,
                "category": candidate.get("category", "fact"),
                "confirm_prompt": prompt,
                "turns_waited": 0,
            }
            return {"status": "pending", "confirm_prompt": prompt}

        if candidate.get("sensitive") and candidate.get("longterm") and not allow_confirm_prompts:
            return {"status": "stored", "promoted": False}

        if candidate.get("longterm"):
            self.workspace.append_to_longterm_memory(content, candidate.get("category", "fact"))
            return {"status": "stored", "promoted": True}

        self._maybe_promote_longterm(content, candidate.get("category", "fact"), candidate, timezone_name)
        return {"status": "stored", "promoted": False}

    def _maybe_promote_longterm(self, content: str, category: str, meta: dict, timezone_name: str | None) -> None:
        if meta.get("sensitive"):
            return
        if not meta.get("explicit") and not meta.get("confirmed"):
            return

        today = self._resolve_today(timezone_name)
        if self.workspace.has_cross_day_repeat(content, threshold=0.7, days=7, today_date=today):
            self.workspace.append_to_longterm_memory(content, category)

    @staticmethod
    def _needs_sensitive_content(text: str) -> bool:
        if EMAIL_PATTERN.search(text) or PHONE_PATTERN.search(text) or ID_PATTERN.search(text):
            return False
        if re.search(r"\d{4,}", text):
            return False
        return bool(SENSITIVE_KEYWORDS.search(text))

    def _resolve_today(self, timezone_name: str | None) -> datetime:
        if not timezone_name or not ZoneInfo:
            return datetime.now()
        tz_name = timezone_name.strip()
        if not tz_name:
            return datetime.now()

        if tz_name.upper().startswith("UTC"):
            sign = "+" if "+" in tz_name else "-"
            parts = re.split(r"[+-]", tz_name, maxsplit=1)
            if len(parts) == 2 and parts[1]:
                offset = parts[1]
                if ":" in offset:
                    hours, minutes = offset.split(":", 1)
                else:
                    hours, minutes = offset, "0"
                try:
                    delta = int(hours) * 60 + int(minutes)
                    if sign == "-":
                        delta = -delta
                    return datetime.utcnow() + timedelta(minutes=delta)
                except Exception:
                    return datetime.now()

        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            return datetime.now()

    @staticmethod
    def _build_sensitive_longterm_prompt(content: str, language: str) -> str:
        snippet = MemoryCaptureManager._summarize(content)
        if language == "en":
            return f"This is sensitive info. Confirm long-term storage? \"{snippet}\""
        return f"这是敏感信息，确认要长期记住吗？“{snippet}”"

    @staticmethod
    def _build_sensitive_content_prompt(language: str) -> str:
        if language == "en":
            return "Please provide the exact sensitive content to remember."
        return "请提供要记住的具体敏感内容。"