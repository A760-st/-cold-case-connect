from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.models.evidence import Evidence, EvidenceType
from app.models.investigation import Investigation
from app.models.web_research import ResearchSearch, SearchType
from app.services.evidence import EvidenceService
from app.services.historical_image_search import HistoricalImageSearchError, HistoricalImageSearchService
from app.services.historical_search import HistoricalSearchError, HistoricalSearchService
from app.services.web_research import WebResearchService


class AgentToolError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message


class AgentToolRegistry:
    """Only registered service calls are available to the agent executor."""

    def __init__(self, db: Session, investigation_id: UUID, agent_run_id: UUID):
        self.db, self.investigation_id, self.agent_run_id = db, investigation_id, agent_run_id
        self.investigation = None
        self.evidence: list[Evidence] = []

    def get_investigation(self) -> dict:
        item = self.db.get(Investigation, self.investigation_id)
        if item is None:
            raise AgentToolError("INVESTIGATION_NOT_FOUND", "Investigation was not found.")
        self.investigation = item
        return {"id": str(item.id), "title": item.title, "description": item.description, "status": item.status.value}

    def get_evidence(self) -> dict:
        self.evidence = EvidenceService(self.db).list(self.investigation_id)
        return {"items": [{"id": str(item.id), "title": item.title, "type": item.type.value,
                            "description": item.description, "text_content": item.text_content or "",
                            "filename": item.original_filename, "processing_status": item.processing_status.value} for item in self.evidence]}

    def get_research_history(self) -> dict:
        service = WebResearchService(self.db)
        page = service.list_runs(self.investigation_id, 25, 0)
        existing = list(self.db.scalars(select(ResearchSearch).where(ResearchSearch.investigation_id == self.investigation_id)))
        return {"runs": page["items"], "searches": [{"query": row.query, "search_type": row.search_type.value, "status": row.status.value} for row in existing]}

    def search_historical_text(self, evidence_ids: list[UUID], top_k: int) -> dict:
        eligible = [item for item in self.evidence if item.id in evidence_ids and item.text_content and item.text_content.strip()]
        if not eligible:
            return {"results": [], "index_status": "NO_SEARCHABLE_TEXT", "model": settings.sbert_model_name}
        try:
            return HistoricalSearchService(self.db).search_evidence(self.investigation_id, [item.id for item in eligible[:20]], top_k)
        except HistoricalSearchError as exc:
            raise AgentToolError(exc.code, exc.message) from None

    def search_historical_images(self, evidence_ids: list[UUID], top_k: int) -> dict:
        images = [item for item in self.evidence if item.id in evidence_ids and item.type == EvidenceType.IMAGE]
        results, errors = [], []
        remaining = top_k
        for item in images[:settings.agent_max_image_searches]:
            if remaining <= 0:
                break
            try:
                data = HistoricalImageSearchService(self.db).search_evidence(self.investigation_id, item.id, min(remaining, 5))
                results.extend(data.get("results", []))
                remaining = max(0, top_k - len(results))
            except HistoricalImageSearchError as exc:
                errors.append({"evidence_id": str(item.id), "code": exc.code, "message": exc.message})
        return {"results": results[:top_k], "errors": errors, "model": settings.clip_model_name,
                "index_status": "READY" if results else ("FAILED" if errors else "NO_RESULTS")}

    def search_public(self, action_type: str, query: str, evidence_ids: list[UUID], result_limit: int) -> dict:
        kind = {"SEARCH_WEB": SearchType.WEB, "SEARCH_NEWS": SearchType.NEWS, "SEARCH_IMAGES": SearchType.IMAGE}.get(action_type)
        if kind is None:
            raise AgentToolError("INVALID_ACTION", "This research action is not supported.")
        try:
            return WebResearchService(self.db).run_generated(self.investigation_id,
                [{"query": query, "search_type": kind, "reason": f"Agent {kind.value.lower()} action based on documented case information.", "evidence_ids": [str(i) for i in evidence_ids]}],
                evidence_ids=evidence_ids, agent_run_id=self.agent_run_id, result_limit=result_limit)
        except Exception as exc:
            code = getattr(exc, "code", "WEB_RESEARCH_FAILED")
            message = getattr(exc, "message", "The public search could not be completed.")
            raise AgentToolError(code, message) from None
