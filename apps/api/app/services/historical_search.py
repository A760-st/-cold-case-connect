import logging
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.ai.embeddings import get_embedding_service
from app.config import settings
from app.models.evidence import Evidence
from app.models.historical_case import HistoricalCase
from app.models.vector_index import VectorIndexState
from app.models.investigation import Investigation
from app.schemas.historical import HistoricalSearchRequest
from app.services.historical_index import HistoricalIndexError, HistoricalIndexService

logger = logging.getLogger("coldsync.historical_search")


class HistoricalSearchError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 503):
        self.code, self.message, self.status_code = code, message, status_code


class HistoricalSearchService:
    def __init__(self, db: Session):
        self.db = db

    def search(self, request: HistoricalSearchRequest, evidence_sources: list[dict] | None = None) -> dict:
        index_service = HistoricalIndexService(self.db)
        status = index_service.status()
        if status["historical_case_count"] == 0:
            return {"results": [], "query_source": evidence_sources or [], "retrieval": "Historical case semantic search", "model": settings.sbert_model_name, "index_status": status["status"]}
        if status["status"] != "READY":
            code = "INDEX_OUT_OF_SYNC" if status["status"] == "INDEX_OUT_OF_SYNC" else "HISTORICAL_INDEX_UNAVAILABLE"
            raise HistoricalSearchError(code, "Historical case retrieval is currently unavailable.")
        state = self.db.get(VectorIndexState, 1)
        if not state:
            raise HistoricalSearchError("HISTORICAL_INDEX_UNAVAILABLE", "Historical case retrieval is not initialized.")
        try:
            embedding = get_embedding_service(settings.sbert_model_name, settings.sbert_device).embed_text(request.query)
            where = self._where(request)
            collection = index_service._client().get_collection(state.collection_name)
            if collection.count() == 0:
                return {"results": [], "query_source": evidence_sources or [], "retrieval": "Historical case semantic search", "model": settings.sbert_model_name, "index_status": "READY"}
            result = collection.query(query_embeddings=[embedding], n_results=min(request.top_k, collection.count()), where=where)
        except HistoricalSearchError:
            raise
        except Exception as exc:
            logger.exception("Historical semantic search failed")
            raise HistoricalSearchError("HISTORICAL_INDEX_UNAVAILABLE", "Historical case retrieval is currently unavailable.") from exc
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        parsed_ids = []
        for value in ids:
            try:
                parsed_ids.append(UUID(value))
            except (ValueError, TypeError):
                logger.warning("Chroma returned an invalid historical case ID")
        records = {str(row.id): row for row in self.db.scalars(select(HistoricalCase).where(HistoricalCase.id.in_(parsed_ids))) } if parsed_ids else {}
        results = []
        for case_id, distance in zip(ids, distances):
            record = records.get(case_id)
            if not record:
                continue
            similarity = max(0.0, min(1.0, 1.0 - float(distance)))
            results.append({"historical_case_id": case_id, "title": record.title, "summary": record.summary, "description": record.description, "date": record.case_date.isoformat() if record.case_date else None, "location": record.location, "case_type": record.case_type, "status": record.status, "similarity_score": round(similarity, 6), "source": {"name": record.source_name, "url": record.source_url}, "requires_verification": True})
        return {"results": results, "query_source": evidence_sources or [{"type": "investigator_query"}], "retrieval": "Historical case semantic search", "model": settings.sbert_model_name, "index_status": status["status"]}

    def search_evidence(self, investigation_id: UUID, evidence_ids: list[UUID], top_k: int) -> dict:
        if self.db.get(Investigation, investigation_id) is None:
            raise HistoricalSearchError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        evidence_rows = list(self.db.scalars(select(Evidence).where(Evidence.id.in_(set(evidence_ids)))))
        by_id = {row.id: row for row in evidence_rows}
        if len(by_id) != len(set(evidence_ids)):
            raise HistoricalSearchError("EVIDENCE_NOT_FOUND", "One or more selected evidence items were not found.", 404)
        if any(row.investigation_id != investigation_id for row in evidence_rows):
            raise HistoricalSearchError("EVIDENCE_INVESTIGATION_MISMATCH", "Selected evidence must belong to this investigation.", 403)
        if any(row.text_content is None or not row.text_content.strip() for row in evidence_rows):
            raise HistoricalSearchError("EVIDENCE_TEXT_UNAVAILABLE", "Selected evidence has no searchable text. Image and document analysis is not available yet.", 422)
        ordered = [by_id[record_id] for record_id in evidence_ids]
        query = "\n\n".join(f"Evidence: {row.title}\n{row.text_content}" for row in ordered)
        if len(query) > 50000:
            raise HistoricalSearchError("QUERY_TOO_LARGE", "Selected evidence exceeds the 50,000 character search limit. Select fewer items.", 413)
        request = HistoricalSearchRequest(query=query, top_k=top_k)
        trace = [{"evidence_id": str(row.id), "title": row.title, "type": row.type.value} for row in ordered]
        return self.search(request, evidence_sources=trace)

    @staticmethod
    def _where(request: HistoricalSearchRequest) -> dict | None:
        conditions: list[dict] = []
        if request.location:
            conditions.append({"location": {"$eq": request.location}})
        if request.case_type:
            conditions.append({"case_type": {"$eq": request.case_type}})
        if request.status:
            conditions.append({"status": {"$eq": request.status}})
        if request.date_from:
            conditions.append({"date_ordinal": {"$gte": request.date_from.toordinal()}})
        if request.date_to:
            conditions.append({"date_ordinal": {"$lte": request.date_to.toordinal()}})
        if not conditions:
            return None
        return conditions[0] if len(conditions) == 1 else {"$and": conditions}
