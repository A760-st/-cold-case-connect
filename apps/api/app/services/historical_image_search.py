import logging
import hashlib
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.ai.clip_embeddings import get_clip_embedding_service, load_valid_image
from app.config import settings
from app.models.evidence import Evidence, EvidenceType
from app.models.historical_case import HistoricalCase
from app.models.historical_case_image import HistoricalCaseImage
from app.models.image_index import ImageIndexState
from app.models.investigation import Investigation
from app.services.historical_image_index import HistoricalImageIndexService

logger = logging.getLogger("coldsync.historical_image_search")


class HistoricalImageSearchError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 503):
        self.code, self.message, self.status_code = code, message, status_code


class HistoricalImageSearchService:
    def __init__(self, db: Session):
        self.db = db

    def search_bytes(self, image_bytes: bytes, top_k: int = 10, trace: dict | None = None) -> dict:
        if not 1 <= top_k <= 20:
            raise HistoricalImageSearchError("INVALID_TOP_K", "top_k must be between 1 and 20.", 422)
        try:
            load_valid_image(image_bytes)
        except ValueError:
            raise HistoricalImageSearchError("INVALID_IMAGE", "The image is corrupted or unsupported. Use JPEG, PNG, or WebP.", 422) from None
        trace = trace or {"type": "uploaded_image"}
        empty = self._empty_corpus(trace)
        if empty is not None:
            return empty
        try:
            embedding = get_clip_embedding_service(settings.clip_model_name, settings.clip_device).embed_image(image_bytes)
        except Exception as exc:
            logger.exception("CLIP processing failed for uploaded image")
            raise HistoricalImageSearchError("IMAGE_PROCESSING_FAILED", "Image processing failed. Confirm CLIP is available.", 422) from exc
        return self._search_embedding(embedding, top_k, trace)

    def search_evidence(self, investigation_id: UUID, evidence_id: UUID, top_k: int = 10) -> dict:
        investigation = self.db.get(Investigation, investigation_id)
        if investigation is None:
            raise HistoricalImageSearchError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        evidence = self.db.get(Evidence, evidence_id)
        if evidence is None:
            raise HistoricalImageSearchError("EVIDENCE_NOT_FOUND", "Evidence was not found.", 404)
        if evidence.investigation_id != investigation_id:
            raise HistoricalImageSearchError("EVIDENCE_INVESTIGATION_MISMATCH", "Selected evidence must belong to this investigation.", 403)
        if evidence.type != EvidenceType.IMAGE:
            raise HistoricalImageSearchError("EVIDENCE_NOT_IMAGE", "Selected evidence must be an image.", 422)
        if not evidence.storage_path:
            raise HistoricalImageSearchError("EVIDENCE_IMAGE_UNAVAILABLE", "Stored image content is unavailable.", 404)
        if not 1 <= top_k <= 20:
            raise HistoricalImageSearchError("INVALID_TOP_K", "top_k must be between 1 and 20.", 422)
        from app.services.evidence import EvidenceService
        trace = {"evidence_id": str(evidence.id), "title": evidence.title, "filename": evidence.original_filename}
        empty = self._empty_corpus(trace)
        if empty is not None:
            return empty
        try:
            path = EvidenceService(self.db).content_path(evidence)
            image_checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if evidence.checksum and image_checksum != evidence.checksum:
                raise HistoricalImageSearchError("EVIDENCE_IMAGE_UNAVAILABLE", "Stored image integrity validation failed.", 422)
            metadata = dict(evidence.metadata_json or {})
            metadata["clip_processing_status"] = "PROCESSING"
            evidence.metadata_json = metadata
            self.db.commit()
            if evidence.clip_embedding and evidence.clip_embedding_model == settings.clip_model_name and evidence.clip_embedding_checksum == image_checksum:
                vector = evidence.clip_embedding
            else:
                service = get_clip_embedding_service(settings.clip_model_name, settings.clip_device)
                vector = service.embed_image(path)
                evidence.clip_embedding = vector
                evidence.clip_embedding_model = settings.clip_model_name
                evidence.clip_embedding_version = settings.clip_model_name[:64]
                evidence.clip_embedding_checksum = image_checksum
                from datetime import datetime, timezone
                evidence.clip_embedding_created_at = datetime.now(timezone.utc)
            metadata = dict(evidence.metadata_json or {})
            metadata["clip_processing_status"] = "READY"
            evidence.metadata_json = metadata
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            failed = self.db.get(Evidence, evidence_id)
            if failed is not None:
                metadata = dict(failed.metadata_json or {})
                metadata["clip_processing_status"] = "FAILED"
                failed.metadata_json = metadata
                self.db.commit()
            logger.exception("CLIP processing failed for stored evidence %s", evidence.id)
            if getattr(exc, "code", None) == "STORAGE_ERROR":
                raise HistoricalImageSearchError("EVIDENCE_IMAGE_UNAVAILABLE", "Stored image content is unavailable.", 404) from None
            if getattr(exc, "code", None) == "EVIDENCE_IMAGE_UNAVAILABLE":
                raise exc
            raise HistoricalImageSearchError("IMAGE_PROCESSING_FAILED", "Image processing failed. Confirm the image is valid and CLIP is available.", 422) from None
        return self._search_embedding(vector, top_k, trace)

    def _empty_corpus(self, trace: dict) -> dict | None:
        status = HistoricalImageIndexService(self.db).status()
        if status["status"] == "NO_CORPUS":
            return {"results": [], "query_source": trace, "retrieval": "Historical image similarity search", "model": settings.clip_model_name, "index_status": "NO_CORPUS"}
        if status["status"] != "READY":
            raise HistoricalImageSearchError("HISTORICAL_IMAGE_INDEX_UNAVAILABLE", "Historical image retrieval is not ready.")
        return None

    def _search_embedding(self, embedding: list[float], top_k: int, trace: dict | None) -> dict:
        index = HistoricalImageIndexService(self.db)
        status = index.status()
        empty = self._empty_corpus(trace or {"type": "uploaded_image"})
        if empty is not None:
            return empty
        state = self.db.get(ImageIndexState, 1)
        try:
            collection = index._client().get_collection(state.collection_name)
            result = collection.query(query_embeddings=[embedding], n_results=min(top_k, collection.count()))
        except Exception as exc:
            logger.exception("Historical image retrieval failed")
            raise HistoricalImageSearchError("HISTORICAL_IMAGE_INDEX_UNAVAILABLE", "Historical image retrieval is currently unavailable.") from exc
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        image_ids = []
        for value in ids:
            try:
                image_ids.append(UUID(value))
            except (ValueError, TypeError):
                logger.warning("Chroma returned an invalid historical image ID")
        records = {}
        if image_ids:
            rows = self.db.execute(select(HistoricalCaseImage, HistoricalCase).join(HistoricalCase, HistoricalCase.id == HistoricalCaseImage.historical_case_id).where(HistoricalCaseImage.id.in_(image_ids))).all()
            records = {str(image.id): (image, case) for image, case in rows}
        output = []
        for image_id, distance in zip(ids, distances):
            pair = records.get(image_id)
            if not pair:
                continue
            image, case = pair
            output.append({"historical_case_id": str(case.id), "image_id": str(image.id), "image_content_url": f"/api/v1/historical/images/{image.id}/content" if image.storage_path else None, "image_url": image.image_url, "title": case.title, "location": case.location, "date": case.case_date.isoformat() if case.case_date else None, "case_type": case.case_type, "visual_similarity": round(max(0.0, min(1.0, 1.0 - float(distance))), 6), "source": {"name": image.source_name or case.source_name, "url": image.source_url or case.source_url, "image_url": image.image_url}, "requires_verification": True})
        return {"results": output, "query_source": trace or {"type": "uploaded_image"}, "retrieval": "Historical image similarity search", "model": settings.clip_model_name, "index_status": status["status"]}
