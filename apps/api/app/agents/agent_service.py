from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.agents.agent_executor import InvestigationAgentExecutor
from app.agents.agent_models import AgentRunRequest
from app.config import settings
from app.database.session import SessionLocal
from app.models.agent import AgentAction, AgentActionStatus, AgentActionType, AgentRun, AgentRunStatus
from app.models.investigation import Investigation


class AgentServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code, self.message, self.status_code = code, message, status_code


def utcnow():
    return datetime.now(timezone.utc)


class AgentService:
    def __init__(self, db: Session):
        self.db = db

    def start(self, investigation_id: UUID, payload: AgentRunRequest) -> dict:
        if self.db.get(Investigation, investigation_id) is None:
            raise AgentServiceError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        max_iterations = payload.max_iterations or settings.agent_max_iterations
        max_queries = payload.max_serpapi_queries if payload.max_serpapi_queries is not None else settings.agent_max_serpapi_queries
        if max_iterations > settings.agent_max_iterations:
            raise AgentServiceError("AGENT_BUDGET_EXCEEDED", "Requested iteration limit exceeds the configured maximum.", 422)
        if max_queries > settings.agent_max_serpapi_queries:
            raise AgentServiceError("AGENT_BUDGET_EXCEEDED", "Requested public search budget exceeds the configured maximum.", 422)
        active = self.db.scalar(select(AgentRun).where(AgentRun.investigation_id == investigation_id,
            AgentRun.status.in_([AgentRunStatus.QUEUED, AgentRunStatus.RUNNING])).limit(1))
        if active:
            raise AgentServiceError("AGENT_RUN_ALREADY_ACTIVE", "An agent run is already active for this investigation.", 409)
        run = AgentRun(investigation_id=investigation_id, objective=payload.objective,
            status=AgentRunStatus.QUEUED, max_iterations=max_iterations,
            max_actions=settings.agent_max_total_actions, max_serpapi_queries=max_queries,
            metadata_json={"planner": "deterministic", "llm_available": False, "coverage": {}})
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return self.serialize(run)

    @staticmethod
    def background_execute(agent_run_id: str):
        db = SessionLocal()
        try:
            try:
                parsed = UUID(agent_run_id)
            except ValueError:
                return
            InvestigationAgentExecutor(db, parsed).execute()
        finally:
            db.close()

    def run(self, run_id: UUID) -> dict:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            raise AgentServiceError("AGENT_RUN_NOT_FOUND", "Agent run was not found.", 404)
        return InvestigationAgentExecutor(self.db, run.id).serialize_run(run)

    def list_runs(self, investigation_id: UUID, limit: int = 25, offset: int = 0) -> dict:
        if self.db.get(Investigation, investigation_id) is None:
            raise AgentServiceError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        runs = list(self.db.scalars(select(AgentRun).where(AgentRun.investigation_id == investigation_id).order_by(AgentRun.created_at.desc()).offset(offset).limit(limit)))
        return {"items": [self.serialize(run) for run in runs], "limit": limit, "offset": offset}

    def actions(self, run_id: UUID) -> dict:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            raise AgentServiceError("AGENT_RUN_NOT_FOUND", "Agent run was not found.", 404)
        rows = list(self.db.scalars(select(AgentAction).where(AgentAction.agent_run_id == run_id).order_by(AgentAction.sequence_number)))
        return {"items": [self.action_dict(item) for item in rows]}

    def stop(self, run_id: UUID) -> dict:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            raise AgentServiceError("AGENT_RUN_NOT_FOUND", "Agent run was not found.", 404)
        if run.status in {AgentRunStatus.COMPLETED, AgentRunStatus.STOPPED, AgentRunStatus.FAILED}:
            return self.serialize(run)
        run.stop_requested = True
        if run.status == AgentRunStatus.QUEUED:
            run.status, run.stop_reason, run.completed_at = AgentRunStatus.STOPPED, "INVESTIGATOR_STOPPED", utcnow()
            self.db.add(AgentAction(investigation_id=run.investigation_id, agent_run_id=run.id, iteration=run.iteration,
                sequence_number=1, action_type=AgentActionType.STOP, status=AgentActionStatus.COMPLETED,
                output_summary={"status": "STOPPED", "stop_reason": "INVESTIGATOR_STOPPED"}, reason="Stop the queued research run.",
                started_at=utcnow(), completed_at=utcnow()))
        self.db.commit()
        return self.serialize(run)

    def serialize(self, run):
        return InvestigationAgentExecutor(self.db, run.id).serialize_run(run)

    @staticmethod
    def action_dict(action):
        return {"id": str(action.id), "agent_run_id": str(action.agent_run_id), "research_run_id": str(action.research_run_id) if action.research_run_id else None,
            "iteration": action.iteration, "sequence_number": action.sequence_number, "action_type": action.action_type.value,
            "status": action.status.value, "input_payload": action.input_payload or {}, "output_summary": action.output_summary or {},
            "reason": action.reason, "started_at": action.started_at.isoformat() if action.started_at else None,
            "completed_at": action.completed_at.isoformat() if action.completed_at else None,
            "error_code": action.error_code, "error_message": action.error_message}
