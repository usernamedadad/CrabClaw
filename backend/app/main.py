"""FastAPI entrypoint for CrabClaw backend."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .agent import CrabClawAgent
from .api import abilities, conversation, history, journal, settings
from .app_state import set_agent, set_workspace
from .workspace.hub import WorkspaceManager

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    workspace_path = os.getenv("WORKSPACE_PATH", "~/.crabclaw/workspace")
    workspace = WorkspaceManager(workspace_path)
    workspace.ensure_workspace_exists()
    set_workspace(workspace)

    agent = CrabClawAgent(workspace)
    set_agent(agent)

    yield


app = FastAPI(
    title="CrabClaw API",
    description="Personalized AI Agent backend powered by LangChain",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:725").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "crabclaw-backend"}


app.include_router(conversation.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(journal.router, prefix="/api")
app.include_router(abilities.router, prefix="/api")


@app.get("/api")
async def api_root():
    return {"message": "CrabClaw API v0.1.0"}
