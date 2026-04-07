"""Memory API routes."""

from __future__ import annotations

import re
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..app_state import get_workspace

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryFileItem(BaseModel):
    name: str
    type: str
    size: int
    updated_at: float


class MemoryFilesResponse(BaseModel):
    files: List[MemoryFileItem]


class MemoryContentUpdateRequest(BaseModel):
    filename: str
    content: str


class MemoryResetRequest(BaseModel):
    filename: str


class MemoryStatsResponse(BaseModel):
    total_files: int
    daily_files: int
    total_size: int
    categories: dict[str, int]


class MemoryCaptureRequest(BaseModel):
    content: str
    category: str = "fact"


class MemoryCaptureResponse(BaseModel):
    status: str
    message: str
    category: str


class MemoryCleanupResponse(BaseModel):
    status: str
    deleted: List[str]
    message: str


@router.get("/files", response_model=MemoryFilesResponse)
async def list_memory_files():
    ws = get_workspace()
    files = [MemoryFileItem(**item) for item in ws.list_memory_files()]
    return MemoryFilesResponse(files=files)


@router.get("/content")
async def get_memory_content(filename: str = Query(..., description="memory filename")):
    ws = get_workspace()
    content = ws.load_memory_file(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Memory file not found")
    return {"filename": filename, "content": content}


@router.put("/content")
async def update_memory_content(request: MemoryContentUpdateRequest):
    ws = get_workspace()
    if not ws.save_memory_file(request.filename, request.content):
        raise HTTPException(status_code=400, detail="Unsupported memory filename")
    return {"filename": request.filename, "content": request.content, "status": "updated"}


@router.post("/reset")
async def reset_memory_content(request: MemoryResetRequest):
    ws = get_workspace()
    content = ws.reset_memory_file(request.filename)
    if content is None:
        raise HTTPException(status_code=400, detail="Unsupported memory filename")
    return {"filename": request.filename, "content": content, "status": "reset"}


@router.get("/stats", response_model=MemoryStatsResponse)
async def get_memory_stats():
    ws = get_workspace()
    files = ws.list_memory_files()

    categories = {
        "preference": 0,
        "decision": 0,
        "entity": 0,
        "fact": 0,
    }

    total_size = 0
    daily_files = 0
    for item in files:
        total_size += int(item.get("size", 0))
        if item.get("type") != "daily":
            continue

        daily_files += 1
        content = ws.load_memory_file(item.get("name", "")) or ""
        for category in categories:
            pattern = rf"\[{re.escape(category)}\]"
            categories[category] += len(re.findall(pattern, content, re.IGNORECASE))

    return MemoryStatsResponse(
        total_files=len(files),
        daily_files=daily_files,
        total_size=total_size,
        categories=categories,
    )


@router.post("/capture", response_model=MemoryCaptureResponse)
async def capture_memory(request: MemoryCaptureRequest):
    ws = get_workspace()

    category = (request.category or "fact").strip().lower()
    valid_categories = {"preference", "decision", "entity", "fact"}
    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category: {category}. Valid values: {sorted(valid_categories)}",
        )

    content = (request.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Memory content cannot be empty")

    if ws.check_duplicate_memory(content, threshold=0.7):
        return MemoryCaptureResponse(status="skipped", message="Memory already exists", category=category)

    ws.append_classified_memory(content, category)
    return MemoryCaptureResponse(status="ok", message=f"Captured [{category}] memory", category=category)


@router.post("/cleanup", response_model=MemoryCleanupResponse)
async def cleanup_memory(days: int = Query(30, ge=1, description="keep daily memories in recent N days")):
    ws = get_workspace()
    deleted = ws.cleanup_old_memories(days)
    return MemoryCleanupResponse(
        status="ok",
        deleted=deleted,
        message=f"Cleaned {len(deleted)} daily memory files",
    )


@router.get("/list")
async def list_memories_compat():
    ws = get_workspace()
    memories = []
    for item in ws.list_memory_files():
        if item["type"] != "daily":
            continue
        content = ws.load_memory_file(item["name"]) or ""
        preview = ""
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                preview = line[:100]
                break
        memories.append(
            {
                "date": item["name"].replace(".md", ""),
                "filename": item["name"],
                "content": content,
                "preview": preview or "(empty)",
            }
        )
    return {"memories": memories, "total": len(memories)}


@router.get("/{filename}")
async def get_memory_compat(filename: str):
    ws = get_workspace()
    if not filename.endswith(".md"):
        filename += ".md"
    content = ws.load_memory_file(filename)
    if content is None:
        raise HTTPException(status_code=404, detail="Memory file not found")
    return {"filename": filename, "date": filename.replace(".md", ""), "content": content}
