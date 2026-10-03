from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai.gemini.synthesis_service import InvestigationSynthesisService
from app.database.session import get_db
from app.models.investigation import Investigation

router = APIRouter(prefix="/api/v1")


class SynthesisReviewRequest(BaseModel):
    section: str = Field(..., min_length=1, max_length=120)
    item_reference: str = Field(..., min_length=1, max_length=120)
    review_status: str = Field(..., pattern=r"^(ACCEPTED|NEEDS_VERIFICATION|DISMISSED)$")
    note: str | None = None


@router.post("/investigations/{investigation_id}/synthesis")
def generate_investigation_synthesis(investigation_id: UUID, db: Session = Depends(get_db)):
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="INVESTIGATION_NOT_FOUND")
    synthesis = InvestigationSynthesisService(db).generate(investigation_id)
    return {"success": True, "data": _serialize_synthesis(synthesis)}


@router.get("/investigations/{investigation_id}/syntheses")
def list_investigation_syntheses(investigation_id: UUID, db: Session = Depends(get_db)):
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="INVESTIGATION_NOT_FOUND")
    syntheses = InvestigationSynthesisService(db).list_versions(investigation_id)
    return {"success": True, "data": [_serialize_synthesis(item) for item in syntheses]}


@router.get("/syntheses/{synthesis_id}")
def get_synthesis(synthesis_id: UUID, db: Session = Depends(get_db)):
    synthesis = InvestigationSynthesisService(db).get_by_id(synthesis_id)
    if synthesis is None:
        raise HTTPException(status_code=404, detail="SYNTHESIS_NOT_FOUND")
    return {"success": True, "data": _serialize_synthesis(synthesis)}


@router.get("/investigations/{investigation_id}/synthesis/current")
def get_current_synthesis(investigation_id: UUID, db: Session = Depends(get_db)):
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="INVESTIGATION_NOT_FOUND")
    synthesis = InvestigationSynthesisService(db).get_current(investigation_id)
    if synthesis is None:
        raise HTTPException(status_code=404, detail="SYNTHESIS_NOT_FOUND")
    return {"success": True, "data": _serialize_synthesis(synthesis)}


@router.post("/syntheses/{synthesis_id}/regenerate")
def regenerate_synthesis(synthesis_id: UUID, db: Session = Depends(get_db)):
    synthesis = InvestigationSynthesisService(db).get_by_id(synthesis_id)
    if synthesis is None:
        raise HTTPException(status_code=404, detail="SYNTHESIS_NOT_FOUND")
    regenerated = InvestigationSynthesisService(db).regenerate(synthesis_id, force=True)
    return {"success": True, "data": _serialize_synthesis(regenerated)}


@router.post("/syntheses/{synthesis_id}/reviews")
def review_synthesis(synthesis_id: UUID, payload: SynthesisReviewRequest, db: Session = Depends(get_db)):
    synthesis = InvestigationSynthesisService(db).get_by_id(synthesis_id)
    if synthesis is None:
        raise HTTPException(status_code=404, detail="SYNTHESIS_NOT_FOUND")
    review = InvestigationSynthesisService(db).create_review(
        synthesis_id,
        synthesis.investigation_id,
        payload.section,
        payload.item_reference,
        payload.review_status,
        payload.note,
    )
    return {"success": True, "data": _serialize_review(review)}


@router.get("/syntheses/{synthesis_id}/reviews")
def list_synthesis_reviews(synthesis_id: UUID, db: Session = Depends(get_db)):
    synthesis = InvestigationSynthesisService(db).get_by_id(synthesis_id)
    if synthesis is None:
        raise HTTPException(status_code=404, detail="SYNTHESIS_NOT_FOUND")
    reviews = InvestigationSynthesisService(db).list_reviews(synthesis_id)
    return {"success": True, "data": [_serialize_review(item) for item in reviews]}


def _serialize_synthesis(item):
    return {
        "id": str(item.id),
        "investigation_id": str(item.investigation_id),
        "version": item.version,
        "status": item.status,
        "model_name": item.model_name,
        "prompt_version": item.prompt_version,
        "context_hash": item.context_hash,
        "generated_at": item.generated_at.isoformat() if item.generated_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
        "executive_summary": item.executive_summary,
        "synthesis_json": item.synthesis_json,
        "source_count": item.source_count,
        "evidence_count": item.evidence_count,
        "claim_count": item.claim_count,
        "contradiction_count": item.contradiction_count,
        "research_gap_count": item.research_gap_count,
        "token_usage": item.token_usage,
        "metadata": item.metadata,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _serialize_review(item):
    return {
        "id": str(item.id),
        "synthesis_id": str(item.synthesis_id),
        "investigation_id": str(item.investigation_id),
        "section": item.section,
        "item_reference": item.item_reference,
        "review_status": item.review_status,
        "note": item.note,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }
