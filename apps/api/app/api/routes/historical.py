from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.models.historical_case import HistoricalCase
from app.schemas.historical import HistoricalSearchRequest, InvestigationHistoricalSearchRequest, InvestigationHistoricalImageSearchRequest
from app.services.historical_index import HistoricalIndexService
from app.services.historical_image_index import HistoricalImageIndexService
from app.services.historical_image_search import HistoricalImageSearchService
from app.config import settings
from app.models.historical_case_image import HistoricalCaseImage
from app.storage.historical_images import resolve_historical_image
from PIL import Image, UnidentifiedImageError
from io import BytesIO
from app.services.historical_search import HistoricalSearchService

router = APIRouter(prefix="/api/v1")


@router.post("/historical/search")
def search_historical_cases(payload: HistoricalSearchRequest, db: Session = Depends(get_db)):
    return {"success": True, "data": HistoricalSearchService(db).search(payload)}


@router.post("/investigations/{investigation_id}/historical-search")
def search_from_evidence(investigation_id: UUID, payload: InvestigationHistoricalSearchRequest, db: Session = Depends(get_db)):
    return {"success": True, "data": HistoricalSearchService(db).search_evidence(investigation_id, payload.evidence_ids, payload.top_k)}


@router.get("/historical/index-status")
def historical_index_status(db: Session = Depends(get_db)):
    return {"success": True, "data": {**HistoricalIndexService(db).status(), "historical_image_index": HistoricalImageIndexService(db).status(), "clip_model": settings.clip_model_name}}


@router.get("/historical/{case_id}")
def get_historical_case(case_id: UUID, db: Session = Depends(get_db)):
    record = db.get(HistoricalCase, case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="HISTORICAL_CASE_NOT_FOUND")
    return {"success": True, "data": _case(record)}


@router.post("/historical/image-search")
async def search_historical_images(image: UploadFile = File(...), top_k: int = Form(default=10), db: Session = Depends(get_db)):
    mime = (image.content_type or "").split(";", 1)[0].strip().lower()
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="INVALID_IMAGE_TYPE")
    chunks = []
    size = 0
    max_bytes = settings.max_evidence_file_size_mb * 1024 * 1024
    while True:
        chunk = await image.read(min(64 * 1024, max_bytes + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="FILE_TOO_LARGE")
    content = b"".join(chunks)
    try:
        with Image.open(BytesIO(content)) as decoded:
            actual_mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(decoded.format)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        actual_mime = None
    if actual_mime != mime:
        raise HTTPException(status_code=422, detail="INVALID_IMAGE_TYPE")
    return {"success": True, "data": HistoricalImageSearchService(db).search_bytes(content, top_k, {"type": "uploaded_image", "filename": Path(image.filename or "image").name})}


@router.post("/investigations/{investigation_id}/historical-image-search")
def search_investigation_images(investigation_id: UUID, payload: InvestigationHistoricalImageSearchRequest, db: Session = Depends(get_db)):
    return {"success": True, "data": HistoricalImageSearchService(db).search_evidence(investigation_id, payload.evidence_id, payload.top_k)}


@router.get("/historical/images/{image_id}/content")
def historical_image_content(image_id: UUID, db: Session = Depends(get_db)):
    image = db.get(HistoricalCaseImage, image_id)
    if image is None or not image.storage_path:
        raise HTTPException(status_code=404, detail="HISTORICAL_IMAGE_NOT_FOUND")
    try:
        path = resolve_historical_image(image.storage_path)
    except ValueError:
        raise HTTPException(status_code=404, detail="HISTORICAL_IMAGE_NOT_FOUND") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="HISTORICAL_IMAGE_NOT_FOUND")
    return FileResponse(path, media_type=image.mime_type or "application/octet-stream", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


def _case(record: HistoricalCase) -> dict:
    return {"historical_case_id": str(record.id), "external_id": record.external_id, "title": record.title, "summary": record.summary, "description": record.description, "date": record.case_date.isoformat() if record.case_date else None, "location": record.location, "case_type": record.case_type, "status": record.status, "source": {"name": record.source_name, "url": record.source_url}}
