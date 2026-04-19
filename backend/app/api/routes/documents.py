"""Document list / detail / desensitize / upload-to-dify endpoints."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import file_manager
from app.core.desensitizer import desensitize_file
from app.core.dify_uploader import upload_with_metadata
from app.core.index_generator import generate_index
from app.database import get_db
from app.models.document import Document

router = APIRouter()


class PaginationResponse(BaseModel):
    """Generic paginated response wrapper."""
    total: int
    page: int
    size: int
    items: list

    class Config:
        from_attributes = True


class DocumentOut(BaseModel):
    id: int
    filename: str
    department: str
    section: str
    uploaded_by: str
    status: str
    file_hash: str
    raw_path: str
    redacted_path: str
    index_path: str
    knowledge_base_id: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class DocumentContent(BaseModel):
    filename: str
    content: str
    version: str  # "raw" | "redacted"


def _sync_raw_files(db: Session) -> None:
    """Ensure every .md in raw/ has a row in the documents table."""
    raw_files = file_manager.list_raw_files()
    existing = {d.filename for d in db.query(Document.filename).all()}
    for f in raw_files:
        if f.name not in existing:
            h = file_manager.file_hash(f)
            doc = Document(
                filename=f.name,
                directory=str(f.parent),
                file_hash=h,
                raw_path=str(f),
                status="raw",
            )
            db.add(doc)
    db.commit()


@router.get("")
def list_documents(
    department: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    _sync_raw_files(db)
    q = db.query(Document)
    if department:
        q = q.filter(Document.department == department)
    if status:
        q = q.filter(Document.status == status)
    if keyword:
        q = q.filter(Document.filename.contains(keyword))
    
    total = q.count()
    docs = q.order_by(Document.updated_at.desc()).offset((page - 1) * size).limit(size).all()
    
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            DocumentOut(
                id=d.id,
                filename=d.filename,
                department=d.department,
                section=getattr(d, "section", ""),
                uploaded_by=getattr(d, "uploaded_by", ""),
                status=d.status,
                file_hash=d.file_hash,
                raw_path=d.raw_path,
                redacted_path=d.redacted_path,
                index_path=d.index_path,
                knowledge_base_id=getattr(d, "knowledge_base_id", ""),
                created_at=str(d.created_at or ""),
                updated_at=str(d.updated_at or ""),
            )
            for d in docs
        ]
    }


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    department: str = Query(""),
    knowledge_base_id: str = Query(""),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=400, detail="只允许上传 .md 文件")

    content = await file.read()
    filename = file.filename
    dept = department or user["department"]
    sect = user.get("section", "")

    existing = db.query(Document).filter(Document.filename == filename).first()
    saved_path = file_manager.save_raw(filename, content)
    h = file_manager.file_hash(saved_path)

    if existing:
        existing.file_hash = h
        existing.department = dept
        existing.section = sect
        existing.uploaded_by = user["username"]
        existing.status = "raw"
        existing.raw_path = str(saved_path)
        existing.redacted_path = ""
        existing.index_path = ""
        existing.error_message = ""
        existing.knowledge_base_id = knowledge_base_id
        db.commit()
        db.refresh(existing)
        doc_id = existing.id
    else:
        doc = Document(
            filename=filename,
            directory=str(saved_path.parent),
            department=dept,
            section=sect,
            uploaded_by=user["username"],
            file_hash=h,
            raw_path=str(saved_path),
            status="raw",
            knowledge_base_id=knowledge_base_id,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        doc_id = doc.id

    return {
        "status": "ok",
        "id": doc_id,
        "filename": filename,
        "department": dept,
        "section": sect,
        "uploaded_by": user["username"],
    }


@router.get("/{doc_id}", response_model=DocumentContent)
def get_document(doc_id: int, db: Session = Depends(get_db), _user: dict = Depends(get_current_user)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    content = file_manager.read_file(Path(doc.raw_path))
    return DocumentContent(filename=doc.filename, content=content, version="raw")


@router.get("/{doc_id}/redacted", response_model=DocumentContent)
def get_redacted(doc_id: int, db: Session = Depends(get_db), _user: dict = Depends(get_current_user)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    content = file_manager.read_redacted(doc.filename)
    if content is None:
        raise HTTPException(status_code=404, detail="脱敏版本尚未生成")
    return DocumentContent(filename=doc.filename, content=content, version="redacted")


@router.get("/{doc_id}/index")
def get_index(doc_id: int, db: Session = Depends(get_db), _user: dict = Depends(get_current_user)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    raw = file_manager.read_index(Path(doc.filename).stem)
    if raw is None:
        raise HTTPException(status_code=404, detail="索引尚未生成")
    return json.loads(raw)


@router.post("/{doc_id}/desensitize")
async def trigger_desensitize(
    doc_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    try:
        department = doc.department or user["department"]
        section = getattr(doc, "section", "") or user.get("section", "")
        result = await desensitize_file(doc.raw_path, department, db, section=section)
        doc.redacted_path = result["redacted_path"]
        doc.status = "desensitized"
        doc.error_message = ""
        db.commit()
        return {"status": "ok", "report": result["report"]}
    except Exception as e:
        doc.status = "error"
        doc.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{doc_id}/generate-index")
async def trigger_index(
    doc_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    try:
        department = doc.department or user["department"]
        section = getattr(doc, "section", "") or user.get("section", "")
        creator = getattr(doc, "uploaded_by", "") or user.get("username", "")
        index_doc = await generate_index(
            doc.raw_path,
            department,
            db,
            section=section,
            creator=creator,
        )
        stem = Path(doc.filename).stem
        doc.index_path = str(file_manager._index_dir() / f"{stem}.json")
        doc.status = "indexed"
        doc.error_message = ""

        rerank_vec = index_doc.get("_index_embedding") or []
        if rerank_vec:
            from app.core.embedding_service import pack_vector
            doc.index_embedding = pack_vector(rerank_vec)
            doc.index_embedding_dim = len(rerank_vec)

        db.commit()

        graph_block = index_doc.get("knowledge_graph")
        if graph_block:
            try:
                from app.services.kg_service import save_graph
                await save_graph(db, doc.id, graph_block)
            except Exception as exc:
                import logging as _l
                _l.getLogger(__name__).warning(
                    "KG persistence failed for doc_id=%s: %s", doc.id, exc,
                )

        return index_doc
    except Exception as e:
        doc.status = "error"
        doc.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{doc_id}/upload-to-dify")
async def trigger_upload_to_dify(
    doc_id: int,
    knowledge_base_id: str = Query(""),
    db: Session = Depends(get_db),
    _user: dict = Depends(get_current_user),
):
    """Upload both full and redacted versions to Dify knowledge base with metadata.

    Filenames in Dify are differentiated by suffix:
      - full:     "报告.md"
      - redacted: "报告_redacted.md"

    If knowledge_base_id is provided, upload to that specific KB.
    Otherwise, use the KB associated with the document, or the default KB.
    """
    from app.services.settings_service import get_dify_config

    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    stem = Path(doc.filename).stem
    ext = Path(doc.filename).suffix
    index_raw = file_manager.read_index(stem)
    if index_raw is None:
        raise HTTPException(status_code=400, detail="请先生成索引后再上传到 Dify")
    index_data = json.loads(index_raw)

    dify_meta_section = index_data.get("dify_metadata", {})
    if "full" not in dify_meta_section:
        raise HTTPException(status_code=400, detail="索引中不存在 full 版本的 metadata")

    # Resolve dataset_id: explicit param > doc's KB > default KB
    if knowledge_base_id:
        kb_config = get_dify_config(db, knowledge_base_id)
    elif doc.knowledge_base_id:
        kb_config = get_dify_config(db, doc.knowledge_base_id)
    else:
        kb_config = get_dify_config(db)

    dataset_id = kb_config["dataset_id"] if kb_config else None

    results: list[dict] = []

    try:
        full_result = await upload_with_metadata(
            file_path=doc.raw_path,
            index_meta=dify_meta_section["full"],
            dataset_id=dataset_id,
            upload_name=doc.filename,
        )
        results.append({"version": "full", **full_result})

        has_redacted = (
            doc.redacted_path
            and Path(doc.redacted_path).exists()
            and "redacted" in dify_meta_section
        )
        if has_redacted:
            redacted_name = f"{stem}_redacted{ext}"
            redacted_result = await upload_with_metadata(
                file_path=doc.redacted_path,
                index_meta=dify_meta_section["redacted"],
                upload_name=redacted_name,
            )
            results.append({"version": "redacted", **redacted_result})

        doc.status = "uploaded"
        doc.error_message = ""
        db.commit()
        return {
            "status": "ok",
            "uploaded": [
                {
                    "version": r["version"],
                    "dify_document_id": r["document_id"],
                    "dify_name": r["name"],
                }
                for r in results
            ],
        }
    except Exception as e:
        doc.status = "error"
        doc.error_message = f"Dify upload failed: {str(e)}"
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{doc_id}")
def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Delete a document and its associated files (raw, redacted, index)."""
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    try:
        import os
        from pathlib import Path

        files_to_delete = [doc.raw_path, doc.redacted_path, doc.index_path]
        for file_path in files_to_delete:
            if file_path and Path(file_path).exists():
                os.remove(file_path)

        from app.models.knowledge_graph import DocumentEntity, DocumentRelation
        db.query(DocumentEntity).filter(
            DocumentEntity.document_id == doc_id
        ).delete(synchronize_session=False)
        db.query(DocumentRelation).filter(
            (DocumentRelation.src_doc_id == doc_id)
            | (DocumentRelation.dst_doc_id == doc_id)
        ).delete(synchronize_session=False)

        db.delete(doc)
        db.commit()
        return {"status": "deleted", "id": doc_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败：{str(e)}")
