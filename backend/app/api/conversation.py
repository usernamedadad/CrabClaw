"""Chat API routes."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..app_state import get_agent

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    skill_id: Optional[str] = None


class ChatResponse(BaseModel):
    content: str
    session_id: Optional[str] = None


async def _stream_response(request: ChatRequest) -> EventSourceResponse:
    async def event_generator():
        try:
            agent = get_agent()
            async for event in agent.astream_chat(request.message, request.session_id, request.skill_id):
                yield {
                    "event": event.get("event", "error"),
                    "data": json.dumps(event.get("data", {}), ensure_ascii=False),
                }
        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


@router.post("", summary="Send message (SSE)")
async def chat_stream(request: ChatRequest):
    return await _stream_response(request)


@router.post("/send/stream", summary="Send message stream (compat)")
async def chat_stream_compat(request: ChatRequest):
    return await _stream_response(request)


@router.post("/send/sync", response_model=ChatResponse)
async def chat_sync(request: ChatRequest):
    agent = get_agent()
    try:
        content, session_id = agent.chat(request.message, request.session_id, request.skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChatResponse(content=content, session_id=session_id)


@router.post("/send", response_model=ChatResponse)
async def chat_send(request: ChatRequest):
    agent = get_agent()
    try:
        content, session_id = agent.chat(request.message, request.session_id, request.skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChatResponse(content=content, session_id=session_id)
