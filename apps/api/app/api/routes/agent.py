from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.agents.agent_models import AgentRunRequest
from app.agents.agent_service import AgentService, AgentServiceError
from app.database.session import get_db

router = APIRouter(prefix="/api/v1")


def _call(fn):
    try:
        return {"success": True, "data": fn()}
    except AgentServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from None


@router.post("/investigations/{investigation_id}/agent/run", status_code=202)
def start_agent(investigation_id: UUID, payload: AgentRunRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    service = AgentService(db)
    result = _call(lambda: service.start(investigation_id, payload))
    background.add_task(AgentService.background_execute, result["data"]["id"])
    return result


@router.get("/investigations/{investigation_id}/agent/runs")
def list_agent_runs(investigation_id: UUID, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return _call(lambda: AgentService(db).list_runs(investigation_id, limit, offset))


@router.get("/agent/runs/{agent_run_id}")
def get_agent_run(agent_run_id: UUID, db: Session = Depends(get_db)):
    return _call(lambda: AgentService(db).run(agent_run_id))


@router.get("/agent/runs/{agent_run_id}/actions")
def get_agent_actions(agent_run_id: UUID, db: Session = Depends(get_db)):
    return _call(lambda: AgentService(db).actions(agent_run_id))


@router.post("/agent/runs/{agent_run_id}/stop")
def stop_agent(agent_run_id: UUID, db: Session = Depends(get_db)):
    return _call(lambda: AgentService(db).stop(agent_run_id))
