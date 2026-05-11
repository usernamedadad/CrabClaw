"""RAG API routes."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from ..app_state import get_workspace
from ..rag import RagIngester, RagRetriever

router = APIRouter(prefix="/rag", tags=["rag"])


class DocMeta(BaseModel):
    doc_id: str
    source: str
    chunks: int
    indexed: int
    ingested_at: str


class DocListResponse(BaseModel):
    docs: list[DocMeta]


class DeleteResponse(BaseModel):
    status: str
    doc_id: str


@router.post("/ingest", response_model=DocMeta)
async def ingest_file(file: UploadFile = File(...)):
    ws = get_workspace()
    eidx = ws._get_embedding_index()
    if eidx is None:
        raise HTTPException(status_code=400, detail="LLM API key 未配置，无法使用 embedding")

    rag_dir = ws.workspace_path.parent / "rag"
    rag_index_dir = rag_dir / "index"
    rag_docs_dir = rag_dir / "docs"
    rag_docs_dir.mkdir(parents=True, exist_ok=True)

    # Save uploaded file
    filename = Path(file.filename or "uploaded").name
    dest = rag_docs_dir / filename
    with dest.open("wb") as fh:
        content = await file.read()
        fh.write(content)

    ingester = RagIngester(rag_index_dir, eidx)
    result = ingester.ingest_file(dest)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return DocMeta(**result)


@router.get("/list", response_model=DocListResponse)
async def list_docs():
    ws = get_workspace()
    eidx = ws._get_embedding_index()
    if eidx is None:
        raise HTTPException(status_code=400, detail="LLM API key 未配置")
    rag_index_dir = ws.workspace_path.parent / "rag" / "index"
    ingester = RagIngester(rag_index_dir, eidx)
    return DocListResponse(docs=[DocMeta(**d) for d in ingester.list_docs()])


@router.delete("/{doc_id}", response_model=DeleteResponse)
async def delete_doc(doc_id: str):
    ws = get_workspace()
    rag_index_dir = ws.workspace_path.parent / "rag" / "index"
    eidx = ws._get_embedding_index()
    if eidx is None:
        raise HTTPException(status_code=400, detail="LLM API key 未配置")
    ingester = RagIngester(rag_index_dir, eidx)
    ok = ingester.delete_doc(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return DeleteResponse(status="ok", doc_id=doc_id)
