from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.agents.agent_models import ActionType, AgentActionSpec
from app.agents.agent_planner import DeterministicAgentPlanner
from app.agents.agent_state import InvestigationAgentState
from app.agents.agent_tools import AgentToolError, AgentToolRegistry
from app.config import settings
from app.models.agent import AgentAction, AgentActionStatus, AgentActionType, AgentRun, AgentRunStatus
from app.models.web_research import ResearchRun, ResearchSearch, ResearchStatus, SearchType


def _now():
    return datetime.now(timezone.utc)


class InvestigationAgentExecutor:
    def __init__(self, db: Session, agent_run_id):
        self.db, self.agent_run_id = db, agent_run_id
        self.planner = DeterministicAgentPlanner()

    def execute(self) -> dict:
        run = self.db.get(AgentRun, self.agent_run_id)
        if run is None:
            return {"status": "NOT_FOUND"}
        if run.status in {AgentRunStatus.STOPPED, AgentRunStatus.COMPLETED, AgentRunStatus.FAILED}:
            return self.serialize_run(run)
        if run.stop_requested:
            run.status = AgentRunStatus.STOPPED
            run.stop_reason = "INVESTIGATOR_STOPPED"
            run.completed_at = _now()
            self.db.commit()
            return self.serialize_run(run)
        run.status = AgentRunStatus.RUNNING
        run.started_at = run.started_at or _now()
        self.db.commit()
        state = self._load_state(run)
        tools = AgentToolRegistry(self.db, run.investigation_id, run.id)
        try:
            for iteration in range(run.max_iterations):
                self._refresh_run(run.id)
                if run.stop_requested:
                    self._stop(run, "INVESTIGATOR_STOPPED")
                    break
                run.iteration = iteration + 1
                state.iteration = iteration
                self.db.commit()
                plan = self.planner.plan(state, settings.agent_max_actions_per_iteration)
                if not plan:
                    failed = any(key.startswith("SEARCH_") and value is False for key, value in state.coverage.items())
                    succeeded = any(key.startswith("SEARCH_") and value is True for key, value in state.coverage.items())
                    if failed and not succeeded:
                        self._finish(run, "PROVIDER_ERROR", AgentRunStatus.STOPPED)
                    elif state.serpapi_queries_used >= state.max_serpapi_queries and state.max_serpapi_queries >= 0 and state.investigation:
                        self._finish(run, "QUERY_BUDGET_EXHAUSTED", AgentRunStatus.STOPPED)
                    else:
                        self._finish(run, "NO_USEFUL_NEXT_ACTION", AgentRunStatus.COMPLETED)
                    break
                stop_loop = False
                for spec in plan:
                    self._refresh_run(run.id)
                    if run.stop_requested:
                        self._stop(run, "INVESTIGATOR_STOPPED")
                        stop_loop = True
                        break
                    limit_reason = self._budget_stop_reason(run, spec)
                    if limit_reason:
                        self._finish(run, limit_reason, AgentRunStatus.STOPPED)
                        stop_loop = True
                        break
                    duplicate = self._is_duplicate(run, spec)
                    action = self._create_action(run, spec, iteration + 1)
                    self.db.commit()
                    if duplicate:
                        action.status = AgentActionStatus.SKIPPED
                        action.output_summary = {"status": "SKIPPED_DUPLICATE", "message": "Equivalent query already exists in this investigation."}
                        action.completed_at = _now()
                        run.actions_completed += 1
                        self.db.commit()
                        state.completed_actions.append(spec.action.value)
                        continue
                    self._start_action(action)
                    try:
                        output, research_run_id = self._execute_action(tools, spec, state)
                        action.research_run_id = research_run_id
                        action.output_summary = output
                        if output.get("tool_failed"):
                            action.status = AgentActionStatus.FAILED
                            action.error_code = output.get("error_code", "PROVIDER_ERROR")
                            action.error_message = output.get("error_message", "Research provider failed.")[:500]
                        else:
                            action.status = AgentActionStatus.COMPLETED
                        state.completed_actions.append(spec.action.value)
                        self._update_state(state, spec, output, action.status)
                    except AgentToolError as exc:
                        action.status = AgentActionStatus.FAILED
                        action.error_code = exc.code
                        action.error_message = exc.message[:500]
                        action.output_summary = {"status": "FAILED", "error_code": exc.code}
                        state.completed_actions.append(spec.action.value)
                        state.coverage[spec.action.value] = False
                    except Exception:
                        action.status = AgentActionStatus.FAILED
                        action.error_code = "TOOL_FAILED"
                        action.error_message = "The research action failed safely."
                        action.output_summary = {"status": "FAILED", "error_code": "TOOL_FAILED"}
                        state.completed_actions.append(spec.action.value)
                        state.coverage[spec.action.value] = False
                    action.completed_at = _now()
                    run.actions_completed += 1
                    self._persist_state(run, state)
                    self.db.commit()
                    if run.actions_completed >= run.max_actions:
                        self._finish(run, "TOTAL_ACTIONS_EXHAUSTED", AgentRunStatus.STOPPED)
                        stop_loop = True
                        break
                if stop_loop:
                    break
            else:
                self._finish(run, "MAX_ITERATIONS_REACHED", AgentRunStatus.STOPPED)
            run = self._refresh_run(run.id)
            if run.status == AgentRunStatus.RUNNING:
                self._finish(run, "NO_USEFUL_NEXT_ACTION", AgentRunStatus.COMPLETED)
        except Exception:
            self.db.rollback()
            run = self.db.get(AgentRun, self.agent_run_id)
            if run and run.status not in {AgentRunStatus.STOPPED, AgentRunStatus.COMPLETED}:
                self._finish(run, "AGENT_EXECUTION_FAILED", AgentRunStatus.FAILED)
        return self.serialize_run(self.db.get(AgentRun, self.agent_run_id))

    def _load_state(self, run):
        return InvestigationAgentState(investigation_id=run.investigation_id, objective=run.objective,
            max_iterations=run.max_iterations, max_serpapi_queries=run.max_serpapi_queries, max_results=settings.agent_max_results,
            max_historical_searches=settings.agent_max_historical_searches, max_image_searches=settings.agent_max_image_searches,
            serpapi_queries_used=run.queries_used, results_collected=run.results_collected)

    def _execute_action(self, tools, spec: AgentActionSpec, state):
        if spec.action == ActionType.GET_INVESTIGATION:
            result = tools.get_investigation()
            state.investigation = result
            return {"status": "COMPLETED", "investigation": {"id": result["id"], "title": result["title"], "status": result["status"]}}, None
        if spec.action == ActionType.GET_EVIDENCE:
            data = tools.get_evidence()
            state.evidence = data["items"]
            state.evidence_ids = [UUID(item["id"]) for item in data["items"]]
            return {"status": "COMPLETED", "evidence_count": len(data["items"]), "items": [{"id": item["id"], "title": item["title"], "type": item["type"]} for item in data["items"]]}, None
        if spec.action == ActionType.GET_RESEARCH_HISTORY:
            data = tools.get_research_history()
            state.research_history = data["searches"]
            return {"status": "COMPLETED", "research_runs": len(data["runs"]), "searches_reviewed": len(data["searches"])}, None
        if spec.action == ActionType.SEARCH_HISTORICAL_TEXT:
            state.historical_searches_used += 1
            limit = max(0, min(10, state.max_results - state.results_collected))
            data = tools.search_historical_text(spec.evidence_ids, limit)
            rows = data.get("results", [])[:limit]
            matches = [{"match_type": "SEMANTIC_SIMILARITY", "historical_case_id": row.get("historical_case_id"), "title": row.get("title"), "similarity_score": row.get("similarity_score"), "requires_verification": True} for row in rows]
            return {"status": "COMPLETED", "match_count": len(rows), "matches": matches, "index_status": data.get("index_status"), "retrieval": data.get("retrieval")}, None
        if spec.action == ActionType.SEARCH_HISTORICAL_IMAGES:
            state.image_searches_used += min(len(spec.evidence_ids), settings.agent_max_image_searches)
            limit = max(0, min(10, state.max_results - state.results_collected))
            data = tools.search_historical_images(spec.evidence_ids, limit)
            rows = data.get("results", [])[:limit]
            matches = [{"match_type": "VISUAL_SIMILARITY", "historical_case_id": row.get("historical_case_id"), "image_id": row.get("image_id"), "title": row.get("title"), "visual_similarity": row.get("visual_similarity"), "requires_verification": True} for row in rows]
            output = {"status": "COMPLETED", "match_count": len(rows), "matches": matches, "index_status": data.get("index_status"), "errors": data.get("errors", [])}
            if data.get("index_status") == "FAILED" and not rows:
                output.update({"tool_failed": True, "error_code": "HISTORICAL_IMAGE_SEARCH_FAILED", "error_message": "Historical image retrieval is unavailable for one or more images."})
            return output, None
        if spec.action in {ActionType.SEARCH_WEB, ActionType.SEARCH_NEWS, ActionType.SEARCH_IMAGES}:
            kind = {ActionType.SEARCH_WEB: SearchType.WEB, ActionType.SEARCH_NEWS: SearchType.NEWS, ActionType.SEARCH_IMAGES: SearchType.IMAGE}[spec.action]
            if state.serpapi_queries_used >= state.max_serpapi_queries:
                return {"tool_failed": True, "error_code": "QUERY_BUDGET_EXHAUSTED", "error_message": "The configured public search budget is exhausted."}, None
            state.serpapi_queries_used += 1
            remaining = max(0, state.max_results - state.results_collected)
            data = tools.search_public(spec.action.value, spec.query or "", spec.evidence_ids, remaining)
            searches = data.get("searches", [])
            search = searches[0] if searches else {}
            rows = search.get("results", [])
            summary = data.get("metadata", {})
            sources = list(dict.fromkeys(row.get("source_id") for row in rows if row.get("source_id")))
            output = {"status": data.get("status"), "research_run_id": data.get("id"), "search_type": kind.value,
                      "result_count": len(rows), "source_count": int(summary.get("unique_source_count", len(sources))),
                      "source_ids": sources, "engine": search.get("engine"), "query": search.get("query"),
                      "serpapi_search_id": search.get("serpapi_search_id"), "demo_mode": bool(summary.get("demo_mode"))}
            if data.get("status") == "FAILED" or search.get("status") == ResearchStatus.FAILED.value:
                output.update({"tool_failed": True, "error_code": search.get("error_code") or "SERPAPI_FAILED",
                               "error_message": search.get("error_message") or "Public search provider failed."})
            return output, UUID(data["id"])
        raise AgentToolError("INVALID_ACTION", "The requested agent action is not registered.")

    def _update_state(self, state, spec, output, status):
        if spec.action in {ActionType.SEARCH_WEB, ActionType.SEARCH_NEWS, ActionType.SEARCH_IMAGES}:
            if status == AgentActionStatus.COMPLETED:
                state.coverage[spec.action.value] = True
                state.results_collected += int(output.get("result_count", 0))
                state.discovered_sources.extend(output.get("source_ids", []))
            else:
                state.coverage.setdefault(spec.action.value, False)
        elif spec.action == ActionType.SEARCH_HISTORICAL_TEXT:
            state.coverage[spec.action.value] = status == AgentActionStatus.COMPLETED
            state.historical_matches.extend(output.get("matches", []))
            state.results_collected += int(output.get("match_count", 0))
        elif spec.action == ActionType.SEARCH_HISTORICAL_IMAGES:
            state.coverage[spec.action.value] = status == AgentActionStatus.COMPLETED
            state.historical_matches.extend(output.get("matches", []))
            state.results_collected += int(output.get("match_count", 0))

    def _budget_stop_reason(self, run, spec):
        if run.actions_completed >= run.max_actions:
            return "TOTAL_ACTIONS_EXHAUSTED"
        if spec.action in {ActionType.SEARCH_WEB, ActionType.SEARCH_NEWS, ActionType.SEARCH_IMAGES} and run.queries_used >= run.max_serpapi_queries:
            return "QUERY_BUDGET_EXHAUSTED"
        if run.results_collected >= settings.agent_max_results and spec.action in {ActionType.SEARCH_WEB, ActionType.SEARCH_NEWS, ActionType.SEARCH_IMAGES, ActionType.SEARCH_HISTORICAL_TEXT, ActionType.SEARCH_HISTORICAL_IMAGES}:
            return "RESULT_BUDGET_EXHAUSTED"
        return None

    def _create_action(self, run, spec, iteration):
        sequence = (self.db.scalar(select(AgentAction.sequence_number).where(AgentAction.agent_run_id == run.id).order_by(AgentAction.sequence_number.desc()).limit(1)) or 0) + 1
        return AgentAction(investigation_id=run.investigation_id, agent_run_id=run.id, iteration=iteration, sequence_number=sequence,
            action_type=AgentActionType(spec.action.value), status=AgentActionStatus.PENDING,
            input_payload={"query": spec.query, "evidence_ids": [str(item) for item in spec.evidence_ids], "priority": spec.priority}, reason=spec.reason)

    def _is_duplicate(self, run, spec):
        if spec.action not in {ActionType.SEARCH_WEB, ActionType.SEARCH_NEWS, ActionType.SEARCH_IMAGES} or not spec.query:
            return False
        kind = {ActionType.SEARCH_WEB: SearchType.WEB, ActionType.SEARCH_NEWS: SearchType.NEWS, ActionType.SEARCH_IMAGES: SearchType.IMAGE}[spec.action]
        normalized = " ".join(spec.query.split()).casefold()
        existing = self.db.scalars(select(ResearchSearch).where(ResearchSearch.investigation_id == run.investigation_id, ResearchSearch.search_type == kind))
        if any(" ".join(row.query.split()).casefold() == normalized for row in existing):
            return True
        prior = self.db.scalars(select(AgentAction).where(AgentAction.agent_run_id == run.id, AgentAction.action_type == AgentActionType(spec.action.value)))
        return any(" ".join((row.input_payload or {}).get("query", "").split()).casefold() == normalized for row in prior)

    def _start_action(self, action):
        action.status = AgentActionStatus.RUNNING
        action.started_at = _now()
        self.db.commit()

    def _persist_state(self, run, state):
        run = self.db.get(AgentRun, run.id)
        run.queries_used = state.serpapi_queries_used
        run.results_collected = state.results_collected
        run.metadata_json = {"coverage": state.coverage, "historical_match_count": len(state.historical_matches),
                             "sources_discovered": len(set(state.discovered_sources)), "planner": "deterministic"}

    def _refresh_run(self, run_id):
        self.db.expire_all()
        return self.db.get(AgentRun, run_id)

    def _finish(self, run, reason, status):
        run = self.db.get(AgentRun, run.id)
        run.status, run.stop_reason, run.completed_at = status, reason, _now()
        has_stop = self.db.scalar(select(AgentAction.id).where(AgentAction.agent_run_id == run.id, AgentAction.action_type == AgentActionType.STOP).limit(1))
        if not has_stop:
            self._persist_stop_action(run, reason)
        self.db.commit()

    def _stop(self, run, reason):
        self._persist_stop_action(run, reason)
        self._finish(run, reason, AgentRunStatus.STOPPED)

    def _persist_stop_action(self, run, reason):
        sequence = (self.db.scalar(select(AgentAction.sequence_number).where(AgentAction.agent_run_id == run.id).order_by(AgentAction.sequence_number.desc()).limit(1)) or 0) + 1
        self.db.add(AgentAction(investigation_id=run.investigation_id, agent_run_id=run.id, iteration=run.iteration, sequence_number=sequence,
            action_type=AgentActionType.STOP, status=AgentActionStatus.COMPLETED, input_payload={},
            output_summary={"status": "STOPPED", "stop_reason": reason}, reason="Stop the bounded research run.", started_at=_now(), completed_at=_now()))
        self.db.commit()

    def serialize_run(self, run):
        actions = list(self.db.scalars(select(AgentAction).where(AgentAction.agent_run_id == run.id)))
        linked_searches = list(self.db.scalars(select(ResearchSearch).join(ResearchRun, ResearchSearch.research_run_id == ResearchRun.id).where(ResearchRun.agent_run_id == run.id)))
        return {"id": str(run.id), "agent_run_id": str(run.id), "investigation_id": str(run.investigation_id), "objective": run.objective,
            "status": run.status.value, "max_iterations": run.max_iterations, "max_actions": run.max_actions,
            "max_serpapi_queries": run.max_serpapi_queries, "actions_completed": run.actions_completed,
            "queries_used": run.queries_used, "results_collected": run.results_collected,
            "stop_reason": run.stop_reason, "iteration": run.iteration, "metadata": run.metadata_json or {},
            "historical_matches": sum(len((a.output_summary or {}).get("matches", [])) for a in actions if a.action_type in {AgentActionType.SEARCH_HISTORICAL_TEXT, AgentActionType.SEARCH_HISTORICAL_IMAGES}),
            "web_results": sum(s.result_count for s in linked_searches if s.search_type == SearchType.WEB),
            "news_results": sum(s.result_count for s in linked_searches if s.search_type == SearchType.NEWS),
            "image_results": sum(s.result_count for s in linked_searches if s.search_type == SearchType.IMAGE),
            "sources_discovered": (run.metadata_json or {}).get("sources_discovered", 0),
            "research_summary": (run.metadata_json or {}).get("coverage", {}),
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "research_message": "Research completed within configured limits." if run.status == AgentRunStatus.COMPLETED else None}
