"""Application-level state container for singleton services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .workspace.hub import WorkspaceManager

if TYPE_CHECKING:  # pragma: no cover
    from .agent.core_agent import CrabClawAgent

_workspace: Optional[WorkspaceManager] = None
_agent: Optional["CrabClawAgent"] = None


def set_workspace(workspace: WorkspaceManager) -> None:
    global _workspace
    _workspace = workspace


def get_workspace() -> WorkspaceManager:
    if _workspace is None:
        raise RuntimeError("Workspace is not initialized")
    return _workspace


def set_agent(agent: "CrabClawAgent") -> None:
    global _agent
    _agent = agent


def get_agent() -> "CrabClawAgent":
    if _agent is None:
        raise RuntimeError("Agent is not initialized")
    return _agent
