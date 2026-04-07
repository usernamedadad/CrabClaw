"""Skills API routes."""

from __future__ import annotations

import zipfile
from typing import List, Optional

from fastapi import APIRouter, HTTPException
import httpx
from pydantic import BaseModel, Field

from ..app_state import get_workspace
from ..skills import SkillRegistry

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillItem(BaseModel):
    id: str
    name: str
    description: str = ""
    path: str
    entry: str
    updated_at: float


class SkillListResponse(BaseModel):
    skills: List[SkillItem]


class SkillDetailResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    prompt: str = ""
    path: str
    entry: str
    updated_at: float


class SkillInstallLocalRequest(BaseModel):
    path: str = Field(default="", description="Local folder path or SKILL.md path")


class SkillInstallUrlRequest(BaseModel):
    url: str = Field(default="", description="Skill source URL, supports markdown or zip")


class SkillInstallResponse(BaseModel):
    status: str
    installed: List[SkillItem]
    message: str


class SkillDeleteResponse(BaseModel):
    status: str
    skill_id: str
    message: str


@router.get("/list", response_model=SkillListResponse)
async def list_skills():
    ws = get_workspace()
    registry = SkillRegistry(ws)
    items = [SkillItem(**item) for item in registry.list_skills()]
    return SkillListResponse(skills=items)


@router.get("/{skill_id}", response_model=SkillDetailResponse)
async def get_skill(skill_id: str):
    ws = get_workspace()
    registry = SkillRegistry(ws)
    item = registry.get_skill(skill_id, include_prompt=True)
    if not item:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillDetailResponse(**item)


@router.post("/install/local", response_model=SkillInstallResponse)
async def install_local_skill(request: SkillInstallLocalRequest):
    ws = get_workspace()
    registry = SkillRegistry(ws)

    path = (request.path or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="Local path is required")

    try:
        installed = registry.install_from_local(path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Install failed: {exc}") from exc

    if not installed:
        raise HTTPException(status_code=400, detail="No valid skill found in the provided path")

    items = [SkillItem(**item) for item in installed if item]
    return SkillInstallResponse(
        status="ok",
        installed=items,
        message=f"Installed {len(items)} skill(s) from local path",
    )


@router.post("/install/url", response_model=SkillInstallResponse)
async def install_url_skill(request: SkillInstallUrlRequest):
    ws = get_workspace()
    registry = SkillRegistry(ws)

    url = (request.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    try:
        installed = registry.install_from_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        raise HTTPException(status_code=status_code, detail=f"Download failed with status {status_code}") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Unable to fetch URL: {exc}") from exc
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Downloaded ZIP is invalid or corrupted") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Install failed: {exc}") from exc

    if not installed:
        raise HTTPException(status_code=400, detail="No valid skill found from URL")

    items = [SkillItem(**item) for item in installed if item]
    return SkillInstallResponse(
        status="ok",
        installed=items,
        message=f"Installed {len(items)} skill(s) from URL",
    )


@router.delete("/{skill_id}", response_model=SkillDeleteResponse)
async def delete_skill(skill_id: str):
    ws = get_workspace()
    registry = SkillRegistry(ws)
    ok = registry.delete_skill(skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillDeleteResponse(status="ok", skill_id=skill_id, message="Skill deleted")
