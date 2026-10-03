import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.models.agent import AgentAction, AgentActionType
from app.models.correlation import Correlation, CorrelationObjectType
from app.models.evidence import Evidence
from app.models.geospatial import Contradiction, Location
from app.models.historical_case import HistoricalCase
from app.models.investigation import Investigation
from app.models.investigation_graph import Claim
from app.models.research_intelligence import InvestigationQuestion, ResearchGap
from app.models.timeline import TimelineEvent
from app.models.web_research import ResearchRun, ResearchSearch, WebSource, WebSearchResult


class InvestigationContextBuilder:
    def __init__(self, db, investigation_id):
        self.db = db
        self.investigation_id = investigation_id

    def _serialize_investigation(self):
        item = self.db.get(Investigation, self.investigation_id)
        return {
            "id": str(item.id),
            "title": item.title,
            "description": item.description,
            "status": item.status.value if hasattr(item.status, "value") else str(item.status),
            "created_at": item.created_at.isoformat() if item.created_at else None,
        } if item else {}

    def _safe_count(self, model):
        return self.db.scalar(select(model.id).where(model.investigation_id == self.investigation_id).limit(1)) is not None

    def build(self):
        evidence = [
            {
                "id": str(e.id),
                "type": (e.type.value if hasattr(e.type, "value") else str(e.type)),
                "title": e.title,
                "description": e.description,
                "text_content": e.text_content,
                "metadata": e.metadata_json or {},
                "processing_status": (e.processing_status.value if hasattr(e.processing_status, "value") else str(e.processing_status)),
                "source_ref": f"E-{str(e.id)[:8].upper()}",
            }
            for e in self.db.scalars(select(Evidence).where(Evidence.investigation_id == self.investigation_id).limit(100)).all()
        ]

        claims = [
            {
                "id": str(c.id),
                "claim": f"{c.subject} {c.predicate} {c.object_value}",
                "source": str(c.source_id),
                "provenance": {"source_type": c.source_type, "evidence_id": str(c.evidence_id) if c.evidence_id else None},
                "status": (c.status.value if hasattr(c.status, "value") else str(c.status)),
                "extraction_method": c.extraction_method,
                "source_ref": f"C-{str(c.id)[:8].upper()}",
            }
            for c in self.db.scalars(select(Claim).where(Claim.investigation_id == self.investigation_id).limit(100)).all()
        ]

        sources = [
            {
                "id": str(s.id),
                "title": s.title or s.source_name or s.url,
                "domain": s.domain,
                "source_type": (s.source_type.value if hasattr(s.source_type, "value") else str(s.source_type)),
                "url": s.url,
                "source_ref": f"S-{str(s.id)[:8].upper()}",
            }
            for s in self.db.scalars(select(WebSource).where(WebSource.investigation_id == self.investigation_id).limit(100)).all()
        ]

        research_runs = [
            {
                "id": str(run.id),
                "objective": run.objective,
                "trigger": (run.trigger.value if hasattr(run.trigger, "value") else str(run.trigger)),
                "status": (run.status.value if hasattr(run.status, "value") else str(run.status)),
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "queries": [
                    {"id": str(q.id), "query": q.query, "engine": q.engine, "result_count": q.result_count, "status": (q.status.value if hasattr(q.status, "value") else str(q.status))}
                    for q in self.db.scalars(select(ResearchSearch).where(ResearchSearch.investigation_id == self.investigation_id, ResearchSearch.research_run_id == run.id)).all()
                ],
            }
            for run in self.db.scalars(select(ResearchRun).where(ResearchRun.investigation_id == self.investigation_id).limit(50)).all()
        ]

        timeline = [
            {
                "id": str(item.id),
                "title": item.title,
                "date_start": item.date_start.isoformat() if item.date_start else None,
                "date_end": item.date_end.isoformat() if item.date_end else None,
                "date_text": item.date_text,
                "date_precision": (item.date_precision.value if hasattr(item.date_precision, "value") else str(item.date_precision)),
                "location": item.location,
                "source_ref": f"T-{str(item.id)[:8].upper()}",
            }
            for item in self.db.scalars(select(TimelineEvent).where(TimelineEvent.investigation_id == self.investigation_id).limit(100)).all()
        ]

        locations = [
            {
                "id": str(loc.id),
                "raw_text": loc.raw_text,
                "normalized_text": loc.normalized_text,
                "precision": (loc.precision.value if hasattr(loc.precision, "value") else str(loc.precision)),
                "geocoding_status": (loc.geocoding_status.value if hasattr(loc.geocoding_status, "value") else str(loc.geocoding_status)),
            }
            for loc in self.db.scalars(select(Location).where(Location.investigation_id == self.investigation_id).limit(100)).all()
        ]

        contradictions = [
            {
                "id": str(c.id),
                "type": (c.type.value if hasattr(c.type, "value") else str(c.type)),
                "value_a": c.value_a,
                "value_b": c.value_b,
                "status": (c.status.value if hasattr(c.status, "value") else str(c.status)),
                "severity": (c.severity.value if hasattr(c.severity, "value") else str(c.severity)),
                "source_ref": f"X-{str(c.id)[:8].upper()}",
            }
            for c in self.db.scalars(select(Contradiction).where(Contradiction.investigation_id == self.investigation_id).limit(100)).all()
        ]

        research_gaps = [
            {
                "id": str(g.id),
                "type": (g.gap_type.value if hasattr(g.gap_type, "value") else str(g.gap_type)),
                "description": g.description,
                "priority": g.priority,
                "status": (g.status.value if hasattr(g.status, "value") else str(g.status)),
                "source_ref": f"G-{str(g.id)[:8].upper()}",
            }
            for g in self.db.scalars(select(ResearchGap).where(ResearchGap.investigation_id == self.investigation_id).limit(100)).all()
        ]

        questions = [
            {
                "id": str(q.id),
                "question": q.question,
                "status": (q.status.value if hasattr(q.status, "value") else str(q.status)),
                "priority": q.priority,
            }
            for q in self.db.scalars(select(InvestigationQuestion).where(InvestigationQuestion.investigation_id == self.investigation_id).limit(100)).all()
        ]

        historical_case_ids = set(self.db.scalars(select(TimelineEvent.historical_case_id).where(
            TimelineEvent.investigation_id == self.investigation_id,
            TimelineEvent.historical_case_id.is_not(None),
        )))
        for correlation in self.db.scalars(select(Correlation).where(Correlation.investigation_id == self.investigation_id)):
            for source_type, source_id in ((correlation.source_type, correlation.source_id), (correlation.target_type, correlation.target_id)):
                if source_type == CorrelationObjectType.HISTORICAL_CASE:
                    historical_case_ids.add(source_id)
        for action in self.db.scalars(select(AgentAction).where(
            AgentAction.investigation_id == self.investigation_id,
            AgentAction.action_type == AgentActionType.SEARCH_HISTORICAL_TEXT,
        )):
            for match in (action.output_summary or {}).get("matches", []):
                try:
                    historical_case_ids.add(UUID(str(match.get("historical_case_id"))))
                except (TypeError, ValueError):
                    continue

        historical_cases = self.db.scalars(select(HistoricalCase).where(HistoricalCase.id.in_(historical_case_ids)).limit(50)).all() if historical_case_ids else []
        historical_matches = [
            {
                "id": str(case.id),
                "case": case.title,
                "similarity": case.metadata_json.get("similarity") if case.metadata_json else None,
                "source": case.source_name or case.source_url,
                "metadata": case.metadata_json or {},
            }
            for case in historical_cases
        ]

        graph_relationships = {
            "claims": len(claims),
            "sources": len(sources),
            "contradictions": len(contradictions),
            "research_gaps": len(research_gaps),
        }

        context = {
            "investigation": self._serialize_investigation(),
            "evidence": evidence,
            "claims": claims,
            "historical_matches": historical_matches,
            "image_matches": [],
            "sources": sources,
            "research_runs": research_runs,
            "timeline": timeline,
            "geography": locations,
            "correlations": [],
            "contradictions": contradictions,
            "research_gaps": research_gaps,
            "questions": questions,
            "graph_relationships": graph_relationships,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "limits": {
                "MAX_CONTEXT_EVIDENCE": 25,
                "MAX_CONTEXT_CLAIMS": 20,
                "MAX_CONTEXT_SOURCES": 20,
                "MAX_CONTEXT_RESULTS": 25,
                "MAX_CONTEXT_HISTORICAL_CASES": 10,
                "MAX_CONTEXT_TIMELINE_EVENTS": 20,
                "MAX_CONTEXT_CONTRADICTIONS": 10,
                "MAX_CONTEXT_RESEARCH_GAPS": 10,
            },
        }
        return context

    def hash_context(self, context):
        normalized = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class InvestigationContextProvider:
    def __init__(self, db, investigation_id):
        self.db = db
        self.investigation_id = investigation_id

    def get_context(self):
        return InvestigationContextBuilder(self.db, self.investigation_id).build()
