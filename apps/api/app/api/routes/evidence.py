from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.config import settings
from app.database.session import get_db
from app.models.evidence import EvidenceType, ProcessingStatus
from app.schemas.evidence import EvidenceRead, EvidenceUpdate, TextEvidenceCreate
from app.services.evidence import EvidenceError, EvidenceService, MAX_BYTES

router = APIRouter(prefix="/api/v1")


def _serialize(item):
    return EvidenceRead.model_validate(item).model_dump(mode="json")


@router.post("/investigations/{investigation_id}/evidence", status_code=201)
def create_text_evidence(investigation_id: UUID, payload: TextEvidenceCreate, db: Session = Depends(get_db)):
    return {"success": True, "data": _serialize(EvidenceService(db).create_text(investigation_id, payload))}


@router.post("/investigations/{investigation_id}/evidence/upload", status_code=201)
async def upload_evidence(investigation_id: UUID, file: UploadFile = File(...), title: str | None = Form(default=None), description: str = Form(default=""), db: Session = Depends(get_db)):
    chunks = []
    size = 0
    while True:
        chunk = await file.read(min(64 * 1024, MAX_BYTES + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(status_code=413, detail="FILE_TOO_LARGE")
    item = EvidenceService(db).upload(investigation_id, file.filename or "", file.content_type or "", b"".join(chunks), title, description)
    return {"success": True, "data": _serialize(item)}


@router.get("/investigations/{investigation_id}/evidence")
def list_evidence(investigation_id: UUID, evidence_type: EvidenceType | None = Query(default=None, alias="type"), processing_status: ProcessingStatus | None = None, db: Session = Depends(get_db)):
    items = EvidenceService(db).list(investigation_id, evidence_type, processing_status)
    return {"success": True, "data": [_serialize(item) for item in items]}


@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: UUID, db: Session = Depends(get_db)):
    item = EvidenceService(db).get(evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    return {"success": True, "data": _serialize(item)}


@router.patch("/evidence/{evidence_id}")
def update_evidence(evidence_id: UUID, payload: EvidenceUpdate, db: Session = Depends(get_db)):
    item = EvidenceService(db).update(evidence_id, payload)
    if item is None:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    return {"success": True, "data": _serialize(item)}


@router.delete("/evidence/{evidence_id}", status_code=204)
def delete_evidence(evidence_id: UUID, db: Session = Depends(get_db)):
    if not EvidenceService(db).delete(evidence_id):
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")


@router.get("/evidence/{evidence_id}/content")
def evidence_content(evidence_id: UUID, db: Session = Depends(get_db)):
    service = EvidenceService(db)
    item = service.get(evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    if item.type == EvidenceType.TEXT:
        return {"success": True, "data": {"text_content": item.text_content}}
    path = service.content_path(item)
    if path is None:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    disposition = "inline" if item.type == EvidenceType.IMAGE else "attachment"
    filename = Path(item.original_filename or "evidence").name.replace('"', "")
    return FileResponse(path, media_type=item.mime_type or "application/octet-stream", filename=filename, content_disposition_type=disposition, headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})
