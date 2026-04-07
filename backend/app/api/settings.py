"""Config API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..app_state import get_workspace
from ..workspace.hub import extract_identity_name

router = APIRouter(prefix="/config", tags=["config"])


class AgentInfo(BaseModel):
    name: str


class LLMConfig(BaseModel):
    model_id: str = Field(default="")
    api_key: str = Field(default="")
    base_url: str = Field(default="")
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    search_api_key: str = Field(default="")


class LLMConfigUpdateRequest(BaseModel):
    llm: LLMConfig


@router.get("/agent/info", response_model=AgentInfo)
async def get_agent_info():
    ws = get_workspace()
    name = extract_identity_name(ws.load_config("PROFILE")) or "CrabClaw"
    return AgentInfo(name=name)


@router.get("/llm", response_model=LLMConfig)
async def get_llm_config():
    ws = get_workspace()
    cfg = ws.get_llm_config()
    return LLMConfig(
        model_id=cfg.get("model_id", ""),
        api_key=cfg.get("api_key", ""),
        base_url=cfg.get("base_url", ""),
        temperature=cfg.get("temperature", 0.4),
        search_api_key=ws.get_search_api_key(),
    )


@router.put("/llm", response_model=LLMConfig)
async def update_llm_config(request: LLMConfigUpdateRequest):
    ws = get_workspace()
    data = ws.load_global_config()
    if not isinstance(data, dict):
        data = {}

    data["llm"] = {
        "model_id": request.llm.model_id,
        "api_key": request.llm.api_key,
        "base_url": request.llm.base_url,
        "temperature": request.llm.temperature,
    }

    tools = data.get("tools")
    if not isinstance(tools, dict):
        tools = {}
    tools["serpapi_api"] = request.llm.search_api_key
    data["tools"] = tools

    ws.save_global_config(data)
    return LLMConfig(
        model_id=request.llm.model_id,
        api_key=request.llm.api_key,
        base_url=request.llm.base_url,
        temperature=request.llm.temperature,
        search_api_key=request.llm.search_api_key,
    )


@router.get("/list")
async def list_configs():
    ws = get_workspace()
    return {"configs": ["CONFIG", *ws.list_configs()]}


@router.get("/{name}")
async def get_config(name: str):
    ws = get_workspace()
    if name == "CONFIG":
        return {
            "name": "CONFIG",
            "content": ws.global_config_path.read_text(encoding="utf-8") if ws.global_config_path.exists() else "{}",
        }

    content = ws.load_config(name)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Config {name} not found")
    return {"name": name, "content": content}


class ConfigUpdateRequest(BaseModel):
    content: str


@router.put("/{name}")
async def update_config(name: str, request: ConfigUpdateRequest):
    ws = get_workspace()
    if name == "CONFIG":
        try:
            import json

            data = json.loads(request.content)
            if not isinstance(data, dict):
                raise ValueError("config must be a JSON object")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

        ws.save_global_config(data)
        return {"name": name, "status": "updated"}

    if name not in ws.list_configs():
        raise HTTPException(status_code=404, detail=f"Config {name} not found")

    ws.save_config(name, request.content)
    return {"name": name, "status": "updated"}
