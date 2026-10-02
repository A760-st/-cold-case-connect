from collections import defaultdict, deque
from time import monotonic
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from app.config import settings
from app.database.session import get_db
from app.models.web_research import SearchType
from app.services.web_research import WebResearchError, WebResearchService

router = APIRouter(prefix="/api/v1")
_rate_events: dict[str, deque] = defaultdict(deque)


class ManualSearch(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    search_type: SearchType = SearchType.WEB
    @field_validator("query")
    @classmethod
    def clean_query(cls, value):
        value = " ".join(value.split())
        if not value: raise ValueError("query cannot be blank")
        return value


class EvidenceResearch(BaseModel):
    evidence_ids: list[UUID] | None = None


class GeneratedResearch(BaseModel):
    queries: list[ManualSearch] = Field(min_length=1, max_length=20)
    evidence_ids: list[UUID] | None = None


def _rate_limit(request: Request, investigation_id: UUID):
    key = f"{request.client.host if request.client else 'unknown'}:{investigation_id}"
    events = _rate_events[key]
    now = monotonic()
    while events and now - events[0] >= 60: events.popleft()
    if len(events) >= settings.research_rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="RESEARCH_RATE_LIMITED")
    events.append(now)


def _execute(fn):
    try: return {"success": True, "data": fn()}
    except WebResearchError as exc: raise HTTPException(status_code=exc.status_code, detail=exc.code) from None


@router.post("/investigations/{investigation_id}/research/search", status_code=201)
def manual_search(investigation_id: UUID, payload: ManualSearch, request: Request, db: Session = Depends(get_db)):
    _rate_limit(request, investigation_id)
    return _execute(lambda: WebResearchService(db).manual_search(investigation_id, payload.query, payload.search_type))


@router.post("/investigations/{investigation_id}/research/from-evidence", status_code=201)
def evidence_research(investigation_id: UUID, payload: EvidenceResearch, request: Request, db: Session = Depends(get_db)):
    _rate_limit(request, investigation_id)
    return _execute(lambda: WebResearchService(db).from_evidence(investigation_id, payload.evidence_ids))


@router.post("/investigations/{investigation_id}/research/runs", status_code=201)
def generated_research(investigation_id: UUID, payload: GeneratedResearch, request: Request, db: Session = Depends(get_db)):
    _rate_limit(request, investigation_id)
    queries = [{"query": item.query, "search_type": item.search_type} for item in payload.queries]
    return _execute(lambda: WebResearchService(db).run_generated(investigation_id, queries, payload.evidence_ids))


@router.get("/investigations/{investigation_id}/research/runs")
def list_runs(investigation_id: UUID, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return _execute(lambda: WebResearchService(db).list_runs(investigation_id, limit, offset))


@router.get("/investigations/{investigation_id}/research/runs/{run_id}")
def get_run(investigation_id: UUID, run_id: UUID, db: Session = Depends(get_db)):
    return _execute(lambda: WebResearchService(db).get_run(investigation_id, run_id))


@router.get("/investigations/{investigation_id}/sources")
def list_sources(investigation_id: UUID, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), q: str | None = Query(None, max_length=500), db: Session = Depends(get_db)):
    return _execute(lambda: WebResearchService(db).sources(investigation_id, limit, offset, q))


@router.get("/investigations/{investigation_id}/research/usage")
def research_usage(investigation_id: UUID, db: Session = Depends(get_db)):
    return _execute(lambda: WebResearchService(db).usage(investigation_id))
