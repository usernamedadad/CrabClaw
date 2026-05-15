"""CrabClaw CLI — terminal interface for the AI Agent.

Usage:
    crabclaw                  Interactive REPL
    crabclaw ask "..."        Single-shot query
    crabclaw ask -s SID "..." Specify session
    echo "..." | crabclaw     Pipe input
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from .repl import run_repl  # noqa: E402
from .stream import consume_stream  # noqa: E402


def _make_agent():
    from ..workspace.hub import WorkspaceManager
    from ..agent.core_agent import CrabClawAgent
    workspace = WorkspaceManager()
    workspace.ensure_workspace_exists()
    return CrabClawAgent(workspace)


async def _ask(message: str, session_id: str | None = None, skill_id: str | None = None) -> None:
    agent = _make_agent()
    await consume_stream(agent.astream_chat(message, session_id, skill_id))
    print()


def main():
    parser = argparse.ArgumentParser(description="CrabClaw AI Agent CLI")
    sub = parser.add_subparsers(dest="cmd")

    ask_p = sub.add_parser("ask", help="单次查询")
    ask_p.add_argument("message", nargs="?", default="")
    ask_p.add_argument("-s", "--session", dest="session_id", default=None)
    ask_p.add_argument("--skill", dest="skill_id", default=None)

    sub.add_parser("chat", help="进入交互式 REPL")

    args = parser.parse_args()

    if args.cmd == "ask":
        if not args.message:
            if not sys.stdin.isatty():
                args.message = sys.stdin.read().strip()
            else:
                print("请输入要查询的内容，或使用管道输入")
                sys.exit(1)
        asyncio.run(_ask(args.message, args.session_id, args.skill_id))
    else:
        agent = _make_agent()
        asyncio.run(run_repl(agent))


if __name__ == "__main__":
    main()
