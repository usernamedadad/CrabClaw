"""Session API routes."""

from __future__ import annotations

import re
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..app_state import get_agent, get_workspace

router = APIRouter(prefix="/session", tags=["session"])


class SessionInfo(BaseModel):
    id: str
    created_at: float
    updated_at: float
    description: str = ""


class SessionListResponse(BaseModel):
    sessions: List[SessionInfo]


class SessionCreateRequest(BaseModel):
    summarize_old: bool = False
    old_session_id: Optional[str] = None
    session_id: Optional[str] = None
    description: Optional[str] = None


class SessionCreateResponse(BaseModel):
    session_id: str
    message: str = "Session created successfully"
    summary_file: Optional[str] = None


class ToolCallFunction(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: ToolCallFunction


class ChatMessage(BaseModel):
    id: Optional[str] = None
    role: Literal["user", "assistant", "tool"]
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None


class SessionHistoryResponse(BaseModel):
    session_id: str
    messages: List[ChatMessage]


@router.get("/list", response_model=SessionListResponse)
async def list_sessions():
    agent = get_agent()
    sessions = [SessionInfo(**item) for item in agent.list_sessions()]
    return SessionListResponse(sessions=sessions)


@router.post("/create", response_model=SessionCreateResponse)
async def create_session(request: Optional[SessionCreateRequest] = None):
    req = request or SessionCreateRequest()
    agent = get_agent()

    custom_session_id = (req.session_id or "").strip() or None
    if custom_session_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", custom_session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id. Use 1-64 chars: letters, numbers, '_' or '-'.")

    summary_file = None
    if req.summarize_old:
        old_id = req.old_session_id
        if not old_id:
            sessions = agent.list_sessions()
            if sessions:
                old_id = sessions[0]["id"]
        if old_id:
            summary_file = await agent.summarize_session(old_id)

    try:
        session_id = agent.create_session(session_id=custom_session_id, description=req.description)
    except ValueError as exc:
        message = str(exc)
        if "already exists" in message.lower():
            raise HTTPException(status_code=409, detail=message)
        raise HTTPException(status_code=400, detail=message)

    return SessionCreateResponse(session_id=session_id, summary_file=summary_file)


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    agent = get_agent()
    for session in agent.list_sessions():
        if session["id"] == session_id:
            return SessionInfo(**session)
    raise HTTPException(status_code=404, detail="Session not found")


@router.get("/{session_id}/history", response_model=SessionHistoryResponse)
async def get_history(session_id: str):
    agent = get_agent()
    history = agent.get_session_history(session_id)

    messages: List[ChatMessage] = []
    for item in history:
        role = item.get("role")
        content = item.get("content")
        metadata = item.get("metadata", {})

        if role == "assistant" and metadata.get("tool_calls"):
            tool_calls = [
                ToolCall(
                    id=tc.get("id", ""),
                    type="function",
                    function=ToolCallFunction(
                        name=tc.get("function", {}).get("name", ""),
                        arguments=tc.get("function", {}).get("arguments", "{}"),
                    ),
                )
                for tc in metadata.get("tool_calls", [])
            ]
            messages.append(ChatMessage(id=item.get("id"), role="assistant", content=content, tool_calls=tool_calls))
        elif role == "tool":
            messages.append(
                ChatMessage(
                    id=item.get("id"),
                    role="tool",
                    content=content,
                    tool_call_id=metadata.get("tool_call_id"),
                )
            )
        elif role in {"user", "assistant"}:
            messages.append(ChatMessage(id=item.get("id"), role=role, content=content))

    return SessionHistoryResponse(session_id=session_id, messages=messages)


@router.delete("/{session_id}/messages/{message_id}")
async def delete_session_message(session_id: str, message_id: str):
    agent = get_agent()
    ok = agent.delete_session_message(session_id, message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")
    return {"message": "Session message deleted successfully", "session_id": session_id, "message_id": message_id}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    agent = get_agent()
    ok = agent.delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "Session deleted successfully", "session_id": session_id}





@router.get("/summaries/list")
async def list_summaries():
    ws = get_workspace()
    return {"summaries": ws.list_session_summaries()}


@router.get("/summaries/{filename}")
async def get_summary(filename: str):
    ws = get_workspace()
    content = ws.load_session_summary(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"filename": filename, "content": content}
