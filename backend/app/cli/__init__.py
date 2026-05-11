"""CrabClaw CLI — terminal interface for the AI Agent.

Usage:
    crabclaw                  Interactive REPL
    crabclaw ask "..."        Single-shot query
    crabclaw ask -s SID "..." Specify session
    crabclaw ingest ./dir/    Index documents for RAG
    echo "..." | crabclaw     Pipe input
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

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


async def _ingest(path: str) -> None:
    agent = _make_agent()
    eidx = agent.workspace._get_embedding_index()
    if eidx is None:
        print("❌ LLM API key 未配置，无法使用 RAG")
        return
    from ..rag import RagIngester
    rag_index_dir = agent.workspace.workspace_path.parent / "rag" / "index"
    ingester = RagIngester(rag_index_dir, eidx)
    target = Path(path).expanduser().resolve()
    if target.is_dir():
        for f in sorted(target.rglob("*")):
            if f.is_file():
                result = ingester.ingest_file(f)
                if "error" in result:
                    print(f"  ⚠ {f.name}: {result['error']}")
                else:
                    print(f"  ✅ {f.name} → {result['doc_id']} ({result['chunks']} 块)")
    else:
        result = ingester.ingest_file(target)
        if "error" in result:
            print(f"❌ {result['error']}")
        else:
            print(f"✅ {target.name} → {result['doc_id']} ({result['chunks']} 块)")


def main():
    parser = argparse.ArgumentParser(description="CrabClaw AI Agent CLI")
    sub = parser.add_subparsers(dest="cmd")

    ask_p = sub.add_parser("ask", help="单次查询")
    ask_p.add_argument("message", nargs="?", default="")
    ask_p.add_argument("-s", "--session", dest="session_id", default=None)
    ask_p.add_argument("--skill", dest="skill_id", default=None)

    sub.add_parser("ingest", help="索引用文档（用于 RAG）")
    sub.add_parser("chat", help="进入交互式 REPL")

    args = parser.parse_args()

    if args.cmd == "ingest":
        # ingest takes a positional path, handled differently
        ingest_parser = argparse.ArgumentParser(add_help=False)
        ingest_parser.add_argument("path")
        ingest_args, _ = ingest_parser.parse_known_args()
        asyncio.run(_ingest(ingest_args.path))
    elif args.cmd == "ask":
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
