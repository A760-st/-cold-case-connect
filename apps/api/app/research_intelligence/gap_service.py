"""Conservative, deterministic research gaps derived only from persisted records."""
import hashlib
import json
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.agent import AgentAction, AgentActionType
from app.models.correlation import Correlation, CorrelationReview, CorrelationReviewStatus
from app.models.evidence import Evidence
from app.models.geospatial import Contradiction, ContradictionStatus, EvidenceLocation, Location, TimelineEventLocation
from app.models.historical_case import HistoricalCase
from app.models.investigation import Investigation
from app.models.research_intelligence import ResearchGap, ResearchGapStatus, ResearchGapType
from app.models.timeline import TimelineEvent, TimelineEventEvidence, TimelineEventSource
from app.models.web_research import ResearchSearch, WebSearchResult
from app.models.research_intelligence import InvestigationQuestion, InvestigationQuestionStatus


class ResearchGapError(Exception):
    def __init__(self, code: str, status_code: int = 404):
        self.code, self.status_code = code, status_code


class ResearchGapService:
    def __init__(self, db: Session):
        self.db = db

    def detect(self, investigation_id: UUID) -> dict:
        if self.db.get(Investigation, investigation_id) is None:
            raise ResearchGapError("INVESTIGATION_NOT_FOUND")
        created = 0
        events = list(self.db.scalars(select(TimelineEvent).where(TimelineEvent.investigation_id == investigation_id)))
        for event in events:
            evidence_ids = list(self.db.scalars(select(TimelineEventEvidence.evidence_id).where(TimelineEventEvidence.timeline_event_id == event.id)))
            source_ids = list(self.db.scalars(select(TimelineEventSource.source_id).where(TimelineEventSource.timeline_event_id == event.id)))
            if event.source_id:
                source_ids.append(event.source_id)
            common = {"related_timeline_event_ids": [str(event.id)], "related_evidence_ids": [str(x) for x in evidence_ids], "related_source_ids": [str(x) for x in set(source_ids)]}
            if not event.date_start:
                created += self._upsert(investigation_id, ResearchGapType.MISSING_DATE, event, "Missing documented date", f"Timeline event ‘{event.title}’ has no normalized event date. Available date text: {event.date_text or 'none recorded'}. Missing: a source-backed event date. This does not imply that the event occurred on any particular date.", "MEDIUM", [{"tool": "search_web", "query_template": event.title, "reason": "Search available public sources for a date explicitly associated with this recorded event."}], **common)
            if not event.location:
                created += self._upsert(investigation_id, ResearchGapType.MISSING_LOCATION, event, "Missing documented location", f"Timeline event ‘{event.title}’ has a date or description but no structured location. Missing: a documented location. No location is inferred.", "MEDIUM", [{"tool": "search_web", "query_template": event.title, "reason": "Search existing public-source coverage for explicit location references."}, {"tool": "search_news", "query_template": event.title, "reason": "Check news coverage for a reported location."}], **common)
            if not (event.description or "").strip():
                created += self._upsert(investigation_id, ResearchGapType.MISSING_EVENT_DETAIL, event, "Limited event detail", f"Timeline event ‘{event.title}’ has no descriptive detail attached.", "LOW", [{"tool": "review_evidence", "reason": "Review linked records for source-backed event detail."}], **common)
            source_count = len(set(source_ids))
            if source_count == 0:
                created += self._upsert(investigation_id, ResearchGapType.MISSING_SOURCE, event, "No linked source record", f"Timeline event ‘{event.title}’ has no source record linked to it. The event cannot currently be traced to source material.", "HIGH", [{"tool": "review_evidence", "reason": "Link the original evidence or research source supporting this timeline entry."}], **common)
            if event.importance.value == "HIGH" and source_count == 1:
                created += self._upsert(investigation_id, ResearchGapType.INSUFFICIENT_SOURCE_COVERAGE, event, "Limited source coverage", f"Only one source currently documents this important timeline event in available research records. This describes coverage and does not rate source reliability.", "MEDIUM", [{"tool": "search_news", "query_template": event.title, "reason": "Look for additional source coverage of this documented event."}, {"tool": "search_web", "query_template": event.title, "reason": "Check whether another available public source documents this event."}], **common)
        for contradiction in self.db.scalars(select(Contradiction).where(Contradiction.investigation_id == investigation_id, Contradiction.status.in_([ContradictionStatus.OPEN, ContradictionStatus.UNDER_REVIEW, ContradictionStatus.REQUIRES_VERIFICATION]))):
            kind = ResearchGapType.UNRESOLVED_LOCATION if contradiction.type.value == "LOCATION_CONFLICT" else ResearchGapType.UNRESOLVED_TIMELINE if contradiction.type.value in {"DATE_CONFLICT", "TIME_CONFLICT", "TIMELINE_CONFLICT"} else ResearchGapType.CONTRADICTORY_INFORMATION
            source_ids = self._source_ids_for_contradiction(contradiction)
            event_ids = [str(contradiction.related_event_id)] if contradiction.related_event_id else []
            created += self._upsert(investigation_id, kind, contradiction, "Conflicting reports require review", f"{contradiction.description} Both source reports are retained; no preferred value has been selected.", contradiction.priority, [{"tool": "search_news", "query_template": contradiction.description[:300], "reason": "Seek additional source material relevant to this unresolved conflict."}, {"tool": "review_sources", "reason": "Compare the original source records and record an investigator assessment."}], related_timeline_event_ids=event_ids, related_source_ids=source_ids, related_contradiction_ids=[str(contradiction.id)], related_evidence_ids=self._evidence_ids_for_contradiction(contradiction))
        # Historical context is suggested only when there is documented event context and no recorded historical search.
        if events and any(e.location for e in events):
            historical_searches = self.db.scalar(select(AgentAction.id).where(AgentAction.investigation_id == investigation_id, AgentAction.action_type == AgentActionType.SEARCH_HISTORICAL_TEXT).limit(1))
            if not historical_searches:
                event = next(e for e in events if e.location)
                created += self._upsert(investigation_id, ResearchGapType.MISSING_HISTORICAL_CONTEXT, event, "Historical context not searched", f"The available timeline includes the reported location ‘{event.location}’, but no historical text search is recorded for this investigation.", "LOW", [{"tool": "search_historical_text", "query_template": " ".join(x for x in (event.location, event.event_type.value, event.title) if x), "reason": "Search the existing historical-case collection using documented location and event terms."}], related_timeline_event_ids=[str(event.id)], related_location_ids=[str(x) for x in self.db.scalars(select(TimelineEventLocation.location_id).where(TimelineEventLocation.timeline_event_id == event.id))])
        searches=list(self.db.scalars(select(ResearchSearch).where(ResearchSearch.investigation_id==investigation_id)))
        for event in events:
            if not event.location:continue
            coverage=sum(event.location.casefold() in (search.query or "").casefold() for search in searches)
            if coverage==0:
                location_ids=[str(x) for x in self.db.scalars(select(TimelineEventLocation.location_id).where(TimelineEventLocation.timeline_event_id==event.id))]
                created+=self._upsert(investigation_id,ResearchGapType.UNDER_RESEARCHED_LOCATION,event,"Location has no recorded public search",f"The reported location ‘{event.location}’ is present in a timeline event, but no stored web/news search query currently includes this exact location text.","LOW",[{"tool":"search_web","query_template":f"{event.title} {event.location}","reason":"Check public-source coverage using only the event and location already recorded."},{"tool":"search_news","query_template":f"{event.title} {event.location}","reason":"Check news coverage for the recorded event and location."}],related_timeline_event_ids=[str(event.id)],related_location_ids=location_ids)
        # Under-researched entities are surfaced only when a structured entity is already present in evidence metadata.
        seen_entities=set()
        evidence_rows=list(self.db.scalars(select(Evidence).where(Evidence.investigation_id==investigation_id)))
        for evidence in evidence_rows:
            entities=(evidence.metadata_json or {}).get("entities",[])
            if isinstance(entities,dict):
                structured=[]
                for entity_type,values in entities.items():
                    values=values if isinstance(values,list) else [values]
                    for value in values:
                        structured.append(value if isinstance(value,dict) else {"type":entity_type,"name":value})
                entities=structured
            if not isinstance(entities,list):continue
            for entity in entities:
                if not isinstance(entity,dict):continue
                raw_name=entity.get("name",entity.get("value"))
                if not isinstance(raw_name,str):continue
                name=" ".join(raw_name.split()).strip()
                if not name:continue
                entity_key=str(entity.get("id") or f"{entity.get('type','ENTITY')}:{name.casefold()}")
                if entity_key in seen_entities:continue
                seen_entities.add(entity_key)
                coverage=sum(name.casefold() in (search.query or "").casefold() for search in searches)
                if coverage==0:
                    created+=self._upsert(investigation_id,ResearchGapType.UNDER_RESEARCHED_ENTITY,evidence,"Structured entity has no recorded web/news search",f"The entity ‘{name}’ is explicitly named in evidence metadata, but no stored web/news search query currently includes that name. This is a research coverage observation.","LOW",[{"tool":"search_web","query_template":name,"reason":"Check public-source coverage for this explicitly named entity."},{"tool":"search_news","query_template":name,"reason":"Check news coverage for this explicitly named entity."}],fingerprint_discriminator=entity_key,related_evidence_ids=[str(evidence.id)])
        for question in self.db.scalars(select(InvestigationQuestion).where(InvestigationQuestion.investigation_id==investigation_id,InvestigationQuestion.status.in_([InvestigationQuestionStatus.OPEN,InvestigationQuestionStatus.PARTIALLY_ADDRESSED]))):
            created+=self._upsert(investigation_id,ResearchGapType.UNANSWERED_QUESTION,question,"Open research question",f"Investigator question remains {question.status.value.replace('_',' ').lower()}: {question.question}",question.priority,[{"tool":"research_question","reason":"Use the bounded investigation agent to gather records for this investigator-defined question."}],related_evidence_ids=question.related_evidence_ids or [],related_source_ids=question.related_source_ids or [],related_timeline_event_ids=question.related_timeline_event_ids or [],related_location_ids=question.related_location_ids or [],related_contradiction_ids=[])
        # A reviewable correlation is a gap in review workflow, never a factual connection.
        for corr in self.db.scalars(select(Correlation).where(Correlation.investigation_id == investigation_id)):
            review = self.db.scalar(select(CorrelationReview).where(CorrelationReview.correlation_id == corr.id))
            if review is None:
                created += self._upsert(investigation_id, ResearchGapType.UNREVIEWED_CORRELATION, corr, "Correlation has not been reviewed", "A system-generated correlation exists without an investigator review. It remains a candidate relationship, not an established fact.", "LOW", [{"tool": "review_correlation", "reason": "Review the candidate correlation and record whether it is relevant or needs verification."}], related_correlation_ids=[str(corr.id)])
        self.db.commit()
        return {"status": "COMPLETED", "created": created, "items": self.list(investigation_id)}

    def _upsert(self, investigation_id, gap_type, subject, title, description, priority, actions, fingerprint_discriminator=None, **related):
        normalized = {key: sorted(set(values or [])) for key, values in related.items()}
        material = [str(investigation_id), gap_type.value, getattr(subject, "__tablename__", subject.__class__.__name__), str(subject.id), normalized]
        if fingerprint_discriminator is not None:
            material.append(str(fingerprint_discriminator))
        fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        item = self.db.scalar(select(ResearchGap).where(ResearchGap.investigation_id == investigation_id, ResearchGap.fingerprint == fingerprint))
        if item:
            item.title, item.description, item.priority = title, description, priority
            for key, value in normalized.items():
                setattr(item, key, value)
            item.suggested_research_actions = actions
            return 0
        item = ResearchGap(investigation_id=investigation_id, gap_type=gap_type, title=title, description=description, priority=priority, subject_type=getattr(subject, "__tablename__", subject.__class__.__name__), subject_id=subject.id, fingerprint=fingerprint, suggested_research_actions=actions, **normalized)
        self.db.add(item)
        return 1

    def _evidence_ids_for_contradiction(self, contradiction):
        ids = []
        for kind, source_id in ((contradiction.source_a_type, contradiction.source_a_id), (contradiction.source_b_type, contradiction.source_b_id)):
            if kind == "EVIDENCE":
                ids.append(str(source_id))
            elif kind == "TIMELINE_EVENT":
                ids.extend(str(x) for x in self.db.scalars(select(TimelineEventEvidence.evidence_id).where(TimelineEventEvidence.timeline_event_id == source_id)))
        return sorted(set(ids))

    def _source_ids_for_contradiction(self, contradiction):
        ids=[]
        for kind,source_id in ((contradiction.source_a_type,contradiction.source_a_id),(contradiction.source_b_type,contradiction.source_b_id)):
            if kind in {"WEB_RESULT","SOURCE","HISTORICAL_CASE"}:ids.append(str(source_id))
            elif kind=="TIMELINE_EVENT":
                event=self.db.get(TimelineEvent,source_id)
                if event and event.source_id:ids.append(str(event.source_id))
                ids.extend(str(x) for x in self.db.scalars(select(TimelineEventSource.source_id).where(TimelineEventSource.timeline_event_id==source_id)))
        return sorted(set(ids))

    def list(self, investigation_id, gap_type=None, status=None, priority=None, limit=500, offset=0):
        query = select(ResearchGap).where(ResearchGap.investigation_id == investigation_id)
        if gap_type: query = query.where(ResearchGap.gap_type == gap_type)
        if status: query = query.where(ResearchGap.status == status)
        if priority: query = query.where(ResearchGap.priority == priority)
        rows = self.db.scalars(query.order_by(ResearchGap.created_at.desc()).limit(limit).offset(offset)).all()
        return [self.serialize(item) for item in rows]

    def serialize(self, item):
        return {"id": str(item.id), "investigation_id": str(item.investigation_id), "gap_type": item.gap_type.value, "title": item.title, "description": item.description, "priority": item.priority, "status": item.status.value, "subject_type": item.subject_type, "subject_id": str(item.subject_id) if item.subject_id else None, "related_evidence_ids": item.related_evidence_ids or [], "related_source_ids": item.related_source_ids or [], "related_timeline_event_ids": item.related_timeline_event_ids or [], "related_location_ids": item.related_location_ids or [], "related_correlation_ids": item.related_correlation_ids or [], "related_contradiction_ids": item.related_contradiction_ids or [], "suggested_research_actions": item.suggested_research_actions or [], "investigator_note": item.investigator_note, "last_agent_run_id": str(item.last_agent_run_id) if item.last_agent_run_id else None, "created_at": item.created_at.isoformat() if item.created_at else None, "updated_at": item.updated_at.isoformat() if item.updated_at else None}

    def summary(self, investigation_id):
        items = list(self.db.scalars(select(ResearchGap).where(ResearchGap.investigation_id == investigation_id)))
        by_type = {}
        for item in items:
            by_type[item.gap_type.value] = by_type.get(item.gap_type.value, 0) + 1
        return {"total": len(items), "open": sum(x.status == ResearchGapStatus.OPEN for x in items), "high_priority": sum(x.priority == "HIGH" and x.status == ResearchGapStatus.OPEN for x in items), "researching": sum(x.status == ResearchGapStatus.RESEARCHING for x in items), "addressed": sum(x.status == ResearchGapStatus.SUFFICIENTLY_ADDRESSED for x in items), "dismissed": sum(x.status == ResearchGapStatus.DISMISSED for x in items), "by_type": by_type}
