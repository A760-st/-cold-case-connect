from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.correlation.schemas import CorrelationRunRequest, ManualCorrelationRequest, CorrelationReviewRequest, CorrelationScope
from app.correlation.service import CorrelationService
from app.database.session import get_db
from app.models.correlation import CorrelationObjectType, CorrelationType, CorrelationReviewStatus

router = APIRouter(prefix="/api/v1")


@router.post("/investigations/{investigation_id}/correlations/run")
def run_correlations(investigation_id: UUID, payload: CorrelationRunRequest, db: Session = Depends(get_db)):
    return {"success": True, "data": CorrelationService(db).run(investigation_id, payload.scope)}


@router.get("/investigations/{investigation_id}/correlations")
def list_correlations(investigation_id: UUID,
    correlation_type: CorrelationType | None = None,
    source_type: CorrelationObjectType | None = None,
    target_type: CorrelationObjectType | None = None,
    minimum_score: float | None = Query(default=None, ge=0, le=1),
    review_status: CorrelationReviewStatus | None = None,
    reviewed: bool | None = None,
    evidence_id: UUID | None = None,
    matrix_group: str | None = Query(default=None, pattern="^(historical|web|news|images)$"),
    limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)):
    data = CorrelationService(db).list(investigation_id, correlation_type, source_type, target_type, minimum_score, review_status, reviewed, evidence_id, matrix_group, limit, offset)
    return {"success": True, "data": data}


@router.post("/investigations/{investigation_id}/correlations/manual", status_code=201)
def create_manual_correlation(investigation_id: UUID, payload: ManualCorrelationRequest, db: Session = Depends(get_db)):
    return {"success": True, "data": CorrelationService(db).create_manual(investigation_id, payload)}


@router.get("/correlations/{correlation_id}")
def get_correlation(correlation_id: UUID, db: Session = Depends(get_db)):
    return {"success": True, "data": CorrelationService(db).detail(correlation_id)}


@router.patch("/correlations/{correlation_id}/review")
def review_correlation(correlation_id: UUID, payload: CorrelationReviewRequest, db: Session = Depends(get_db)):
    return {"success": True, "data": CorrelationService(db).review(correlation_id, payload)}


@router.delete("/correlations/{correlation_id}", status_code=204)
def delete_correlation(correlation_id: UUID, db: Session = Depends(get_db)):
    CorrelationService(db).delete(correlation_id)
