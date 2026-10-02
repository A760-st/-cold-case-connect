import hashlib
import io
import logging
import re
from pathlib import PurePath
from uuid import UUID, uuid4
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.models.evidence import Evidence, EvidenceType, ProcessingStatus
from app.models.investigation import Investigation
from app.schemas.evidence import EvidenceUpdate, TextEvidenceCreate
from app.storage import LocalEvidenceStorage

storage = LocalEvidenceStorage(settings.evidence_storage_dir)
logger = logging.getLogger("coldsync.evidence")
MAX_BYTES = settings.max_evidence_file_size_mb * 1024 * 1024
ALLOWED = {
    ".jpg": ("image/jpeg", EvidenceType.IMAGE), ".jpeg": ("image/jpeg", EvidenceType.IMAGE),
    ".png": ("image/png", EvidenceType.IMAGE), ".webp": ("image/webp", EvidenceType.IMAGE),
    ".pdf": ("application/pdf", EvidenceType.DOCUMENT), ".txt": ("text/plain", EvidenceType.DOCUMENT),
}


class EvidenceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code, self.message, self.status_code = code, message, status_code


def _safe_filename(value: str) -> str:
    basename = PurePath(value.replace("\\", "/")).name
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", basename).strip("._")[:180]
    if not safe:
        raise EvidenceError("INVALID_FILE_TYPE", "The uploaded filename is invalid.")
    return safe


def _validate_content(filename: str, mime_type: str, content: bytes) -> tuple[EvidenceType, dict]:
    expected = ALLOWED.get(PurePath(filename).suffix.lower())
    if not expected or mime_type.lower().split(";")[0].strip() != expected[0]:
        raise EvidenceError("INVALID_FILE_TYPE", "Supported files are JPEG, PNG, WebP, PDF, and plain text.")
    declared_mime, evidence_type = expected
    if evidence_type == EvidenceType.IMAGE:
        try:
            image = Image.open(io.BytesIO(content))
            image.verify()
            image = Image.open(io.BytesIO(content))
            width, height = image.size
            if width < 1 or height < 1 or width * height > 40_000_000:
                raise EvidenceError("INVALID_FILE_TYPE", "Image dimensions exceed the supported limit.")
            expected_format = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[mime_type.lower().split(";")[0].strip()]
            if image.format != expected_format:
                raise EvidenceError("INVALID_FILE_TYPE", "The image content does not match a supported image format.")
            return evidence_type, {"source": "investigator_upload", "width": width, "height": height, "format": image.format}
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise EvidenceError("INVALID_FILE_TYPE", "The uploaded image is invalid or unsupported.") from None
    if declared_mime == "application/pdf" and not content.startswith(b"%PDF-"):
        raise EvidenceError("INVALID_FILE_TYPE", "The uploaded file is not a valid PDF.")
    if declared_mime == "text/plain":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise EvidenceError("INVALID_FILE_TYPE", "Text files must use UTF-8 encoding.") from None
    return evidence_type, {"source": "investigator_upload"}


class EvidenceService:
    def __init__(self, db: Session):
        self.db = db

    def create_text(self, investigation_id: UUID, payload: TextEvidenceCreate) -> Evidence:
        self._require_investigation(investigation_id)
        if payload.type == EvidenceType.TEXT and payload.text_content is None:
            raise EvidenceError("INVALID_EVIDENCE_TYPE", "Text evidence must include text content.")
        normalized = payload.text_content.replace("\r\n", "\n").replace("\r", "\n") if payload.text_content is not None else None
        content = normalized.encode("utf-8") if normalized is not None else None
        item = Evidence(investigation_id=investigation_id, type=payload.type, title=payload.title.strip(), description=payload.description.strip(), text_content=normalized, metadata_json={**payload.metadata, "source": "investigator_entered"}, checksum=hashlib.sha256(content).hexdigest() if content else None, file_size=len(content) if content else None, processing_status=ProcessingStatus.READY)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def upload(self, investigation_id: UUID, filename: str, mime_type: str, content: bytes, title: str | None, description: str) -> Evidence:
        self._require_investigation(investigation_id)
        if not content:
            raise EvidenceError("INVALID_FILE_TYPE", "Choose a non-empty file to upload.")
        if len(content) > MAX_BYTES:
            raise EvidenceError("FILE_TOO_LARGE", f"Files must be {settings.max_evidence_file_size_mb} MB or smaller.", 413)
        safe_name = _safe_filename(filename)
        evidence_type, metadata = _validate_content(safe_name, mime_type, content)
        evidence_id = uuid4()
        storage_key = None
        try:
            storage_key = storage.save(investigation_id, evidence_id, safe_name, content)
            clean_title = (title or "").strip() or PurePath(safe_name).stem
            item = Evidence(id=evidence_id, investigation_id=investigation_id, type=evidence_type, title=clean_title[:240], description=description.strip(), original_filename=safe_name, storage_path=storage_key, mime_type=mime_type.lower().split(";")[0].strip(), file_size=len(content), checksum=hashlib.sha256(content).hexdigest(), metadata_json=metadata, processing_status=ProcessingStatus.READY)
            self.db.add(item)
            self.db.commit()
            self.db.refresh(item)
            return item
        except EvidenceError:
            self.db.rollback()
            storage.delete(storage_key)
            raise
        except OSError:
            self.db.rollback()
            try:
                storage.delete(storage_key)
            except OSError:
                logger.exception("Failed to clean up incomplete evidence upload")
            raise EvidenceError("UPLOAD_FAILED", "Evidence could not be stored. Please retry.", 500) from None
        except Exception:
            self.db.rollback()
            try:
                storage.delete(storage_key)
            except OSError:
                logger.exception("Failed to clean up evidence after database error")
            logger.exception("Evidence upload failed")
            raise EvidenceError("UPLOAD_FAILED", "Evidence could not be saved. Please retry.", 500) from None

    def list(self, investigation_id: UUID, evidence_type: EvidenceType | None = None, status: ProcessingStatus | None = None) -> list[Evidence]:
        self._require_investigation(investigation_id)
        query = select(Evidence).where(Evidence.investigation_id == investigation_id).order_by(Evidence.created_at.desc())
        if evidence_type:
            query = query.where(Evidence.type == evidence_type)
        if status:
            query = query.where(Evidence.processing_status == status)
        return list(self.db.scalars(query))

    def get(self, evidence_id: UUID) -> Evidence | None:
        return self.db.get(Evidence, evidence_id)

    def update(self, evidence_id: UUID, payload: EvidenceUpdate) -> Evidence | None:
        item = self.get(evidence_id)
        if item is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(item, "metadata_json" if key == "metadata" else key, value.strip() if isinstance(value, str) else value)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete(self, evidence_id: UUID) -> bool:
        item = self.get(evidence_id)
        if item is None:
            return False
        staged = None
        try:
            staged = storage.stage_delete(item.storage_path)
            self.db.delete(item)
            self.db.commit()
        except Exception:
            self.db.rollback()
            storage.restore_delete(staged)
            logger.exception("Evidence deletion failed")
            raise EvidenceError("STORAGE_ERROR", "Evidence could not be deleted safely.", 500) from None
        try:
            storage.finish_delete(staged)
        except OSError:
            logger.exception("Evidence record deleted but staged file cleanup failed")
        return True

    def content_path(self, item: Evidence):
        if not item.storage_path:
            return None
        try:
            path = storage.resolve(item.storage_path)
        except ValueError:
            raise EvidenceError("STORAGE_ERROR", "Evidence storage reference is invalid.", 500) from None
        if not path.is_file():
            raise EvidenceError("STORAGE_ERROR", "Evidence content is unavailable.", 404)
        return path

    def _require_investigation(self, investigation_id: UUID) -> None:
        if self.db.get(Investigation, investigation_id) is None:
            raise EvidenceError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
