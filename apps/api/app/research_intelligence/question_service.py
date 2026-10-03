from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.evidence import Evidence
from app.models.geospatial import Location, Contradiction
from app.models.investigation import Investigation
from app.models.research_intelligence import InvestigationQuestion, InvestigationQuestionStatus, ResearchGap
from app.models.timeline import TimelineEvent
from app.models.web_research import ResearchSearch, WebSearchResult, WebSource


class QuestionServiceError(Exception):
    def __init__(self, code: str, status_code: int = 404):
        self.code, self.status_code = code, status_code


class QuestionService:
    def __init__(self, db: Session): self.db = db

    def create(self, investigation_id, payload):
        self._investigation(investigation_id)
        data = payload.model_dump()
        for field, model in (("related_evidence_ids", Evidence), ("related_timeline_event_ids", TimelineEvent), ("related_location_ids", Location), ("related_gap_ids", ResearchGap)):
            ids = data[field]
            if ids:
                rows = list(self.db.scalars(select(model).where(model.id.in_(ids), model.investigation_id == investigation_id)))
                if len({r.id for r in rows}) != len(set(ids)):
                    raise QuestionServiceError("RELATED_RECORD_OUTSIDE_INVESTIGATION", 422)
        if data["related_source_ids"]:
            src_ids = set(data["related_source_ids"])
            found = set(self.db.scalars(select(WebSource.id).where(WebSource.id.in_(src_ids), WebSource.investigation_id == investigation_id)))
            found |= set(self.db.scalars(select(WebSearchResult.id).where(WebSearchResult.id.in_(src_ids), WebSearchResult.investigation_id == investigation_id)))
            if found != src_ids: raise QuestionServiceError("RELATED_RECORD_OUTSIDE_INVESTIGATION", 422)
        item = InvestigationQuestion(investigation_id=investigation_id, question=data.pop("question"), priority=data.pop("priority"), **{k: [str(x) for x in v] for k,v in data.items()})
        self.db.add(item); self.db.commit(); self.db.refresh(item)
        return self.serialize(item)

    def list(self, investigation_id, status=None, priority=None, limit=200, offset=0):
        self._investigation(investigation_id)
        q = select(InvestigationQuestion).where(InvestigationQuestion.investigation_id == investigation_id)
        if status: q=q.where(InvestigationQuestion.status == status)
        if priority: q=q.where(InvestigationQuestion.priority == priority)
        rows=self.db.scalars(q.order_by(InvestigationQuestion.created_at.desc()).limit(limit).offset(offset)).all()
        return [self.serialize(row) for row in rows]

    def update(self, question_id, payload):
        item=self.db.get(InvestigationQuestion, question_id)
        if item is None: raise QuestionServiceError("QUESTION_NOT_FOUND")
        data=payload.model_dump(exclude_unset=True)
        if "related_gap_ids" in data:
            ids=data["related_gap_ids"] or []
            rows=list(self.db.scalars(select(ResearchGap).where(ResearchGap.id.in_(ids),ResearchGap.investigation_id==item.investigation_id))) if ids else []
            if len({r.id for r in rows}) != len(set(ids)): raise QuestionServiceError("RELATED_RECORD_OUTSIDE_INVESTIGATION",422)
            data["related_gap_ids"]=[str(x) for x in ids]
        for key,value in data.items():
            if key in {"question","status","priority"} and value is None:continue
            setattr(item,key,value)
        self.db.commit();self.db.refresh(item)
        return self.serialize(item)

    def research_context(self, question_id):
        item=self.db.get(InvestigationQuestion,question_id)
        if item is None: raise QuestionServiceError("QUESTION_NOT_FOUND")
        self._investigation(item.investigation_id)
        event_titles=list(self.db.scalars(select(TimelineEvent.title).where(TimelineEvent.id.in_([UUID(x) for x in item.related_timeline_event_ids])))) if item.related_timeline_event_ids else []
        gap_titles=list(self.db.scalars(select(ResearchGap.title).where(ResearchGap.id.in_([UUID(x) for x in item.related_gap_ids])))) if item.related_gap_ids else []
        evidence_titles=list(self.db.scalars(select(Evidence.title).where(Evidence.id.in_([UUID(x) for x in item.related_evidence_ids])))) if item.related_evidence_ids else []
        location_names=list(self.db.scalars(select(Location.raw_text).where(Location.id.in_([UUID(x) for x in item.related_location_ids]),Location.investigation_id==item.investigation_id))) if item.related_location_ids else []
        contradiction_ids={UUID(x) for gap_id in item.related_gap_ids for x in self.db.scalar(select(ResearchGap.related_contradiction_ids).where(ResearchGap.id==UUID(gap_id))) or []}
        conflict_notes=list(self.db.scalars(select(Contradiction.description).where(Contradiction.id.in_(contradiction_ids),Contradiction.investigation_id==item.investigation_id))) if contradiction_ids else []
        source_titles=[]
        if item.related_source_ids:
            ids=[UUID(x) for x in item.related_source_ids]
            source_titles.extend(self.db.scalars(select(WebSource.title).where(WebSource.id.in_(ids),WebSource.investigation_id==item.investigation_id)))
            source_titles.extend(self.db.scalars(select(WebSearchResult.title).where(WebSearchResult.id.in_(ids),WebSearchResult.investigation_id==item.investigation_id)))
        existing_queries=list(self.db.scalars(select(ResearchSearch.query).where(ResearchSearch.investigation_id==item.investigation_id).order_by(ResearchSearch.created_at.desc()).limit(5)))
        context=" ".join(x for x in [item.question,"Documented context:",*event_titles,*location_names,*evidence_titles,*source_titles,*gap_titles,*conflict_notes,"Existing research queries:",*existing_queries] if x)
        return item, context[:900]

    def _investigation(self, investigation_id):
        if self.db.get(Investigation, investigation_id) is None: raise QuestionServiceError("INVESTIGATION_NOT_FOUND")

    @staticmethod
    def serialize(item):
        return {"id":str(item.id),"investigation_id":str(item.investigation_id),"question":item.question,"status":item.status.value,"priority":item.priority,"related_evidence_ids":item.related_evidence_ids or [],"related_timeline_event_ids":item.related_timeline_event_ids or [],"related_location_ids":item.related_location_ids or [],"related_source_ids":item.related_source_ids or [],"related_gap_ids":item.related_gap_ids or [],"last_agent_run_id":str(item.last_agent_run_id) if item.last_agent_run_id else None,"created_at":item.created_at.isoformat() if item.created_at else None,"updated_at":item.updated_at.isoformat() if item.updated_at else None}
