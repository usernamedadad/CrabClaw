"""Shared async stream consumer for CLI commands."""

from __future__ import annotations

import sys
import time
from typing import AsyncIterator

from .render import tool_start, tool_end


async def consume_stream(
    events: AsyncIterator[dict],
    *,
    track_session: bool = False,
) -> tuple[str | None, bool]:
    """Consume an astream_chat event stream, printing to stdout.

    Returns (session_id, had_error).
    """
    first_chunk = True
    tool_starts: dict[str, float] = {}
    session_id: str | None = None
    had_error = False

    try:
        async for event in events:
            etype = event.get("event", "")
            data = event.get("data", {})

            if etype == "session" and track_session:
                session_id = data.get("session_id")
            elif etype == "tool_start":
                tid = data.get("tool_call_id", "")
                tool_starts[tid] = time.time()
                print(tool_start(data.get("tool_name", ""), data.get("tool_args")))
            elif etype == "tool_end":
                tid = data.get("tool_call_id", "")
                started = tool_starts.pop(tid, time.time())
                dur = (time.time() - started) * 1000
                print(tool_end(data.get("success", True), data.get("summary", ""), dur))
            elif etype == "chunk":
                content = data.get("content", "")
                if first_chunk and content.strip():
                    print("\n🦀 CrabClaw: ", end="", flush=True)
                    first_chunk = False
                sys.stdout.write(content)
                sys.stdout.flush()
            elif etype == "error":
                had_error = True
                print(f"\n  ❌ {data.get('error', '未知错误')}")
    except Exception as exc:
        had_error = True
        print(f"\n  ❌ {exc}")

    return session_id, had_error
