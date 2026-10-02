import hashlib, re
from datetime import date, timedelta
from uuid import UUID
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from app.models.investigation import Investigation
from app.models.evidence import Evidence
from app.models.historical_case import HistoricalCase
from app.models.web_research import WebSearchResult, WebSource, ResearchSearch
from app.models.correlation import Correlation
from app.models.agent import AgentAction, AgentActionType
from app.models.timeline import *
from app.timeline.date_parser import parse_date, MONTH_RX

DATE_RX = re.compile(
    rf"\b(?:\d{{4}}-\d{{1,2}}-\d{{1,2}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}|"
    rf"{MONTH_RX}\s+\d{{1,2}}\s*[-–]\s*\d{{1,2}},?\s+\d{{4}}|"
    rf"{MONTH_RX}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}|"
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH_RX}\s+\d{{4}}|"
    rf"(?:(?:around|about|approximately)\s+)?(?:(?:early|mid|late)\s+)?{MONTH_RX}\s+\d{{4}}|"
    rf"\b\d{{4}})\b", re.I)

class TimelineError(Exception):
    def __init__(self, code): self.code=code

class TimelineService:
    def __init__(self,db:Session): self.db=db
    def generate(self, investigation_id:UUID, scope:str):
        investigation=self.db.get(Investigation,investigation_id)
        if not investigation: raise TimelineError("INVESTIGATION_NOT_FOUND")
        created=0; partial=[]
        if scope=="ALL":
            parsed=parse_date(investigation.created_at.date().isoformat() if investigation.created_at else None)
            event=self._event("Investigation created",investigation.description or "Investigation record created.",TimelineEventType.CASE_CREATED,parsed,TimelineSourceType.INVESTIGATOR,investigation.id,hash_value=hashlib.sha256(f"{investigation.id}:{investigation.created_at}".encode()).hexdigest())
            created += self._upsert(investigation_id,event)
        if scope in {"ALL","EVIDENCE"}:
            try:
                with self.db.begin_nested():
                    for row in self.db.scalars(select(Evidence).where(Evidence.investigation_id==investigation_id)):
                        content=" ".join(x for x in [row.description,row.text_content] if x)
                        metadata=row.metadata_json or {}
                        explicit_dates=[metadata.get(key) for key in ("event_date","incident_date","event_date_text") if isinstance(metadata.get(key),str)]
                        source_hash=hashlib.sha256(f"{content}|{explicit_dates}".encode()).hexdigest()
                        if self._processed(investigation_id,TimelineSourceType.EVIDENCE,row.id,source_hash): continue
                        if row.created_at:
                            collected=parse_date(row.created_at.date().isoformat())
                            event=self._event(f"Evidence collected: {row.title}","Evidence record added to this investigation.",TimelineEventType.EVIDENCE_COLLECTED,collected,TimelineSourceType.EVIDENCE,row.id,hash_value=source_hash,evidence_id=row.id)
                            created += self._upsert(investigation_id,event)
                        for event in self._extract_text(content,row.title,TimelineEventType.EVIDENCE_COLLECTED,TimelineSourceType.EVIDENCE,row.id,row.id,source_hash): created += self._upsert(investigation_id,event)
                        for raw in explicit_dates:
                            parsed=parse_date(raw)
                            if parsed.precision=="UNKNOWN": continue
                            event=self._event(row.title,f"Explicit {raw} date in evidence metadata.",TimelineEventType.EVIDENCE_COLLECTED,parsed,TimelineSourceType.EVIDENCE,row.id,hash_value=source_hash,evidence_id=row.id)
                            created += self._upsert(investigation_id,event)
            except Exception: partial.append("EVIDENCE")
        if scope in {"ALL","WEB","NEWS"}:
            types=("NEWS",) if scope=="NEWS" else (("WEB","IMAGE") if scope=="WEB" else ("WEB","NEWS","IMAGE"))
            try:
                with self.db.begin_nested():
                    rows=self.db.scalars(select(WebSearchResult).where(WebSearchResult.investigation_id==investigation_id,WebSearchResult.result_type.in_(types))).all()
                    for row in rows:
                        snippet=row.snippet or ""
                        metadata=row.metadata_json or {}
                        source_hash=hashlib.sha256(f"{snippet}|{row.published_at}|{metadata.get('event_date')}|{metadata.get('incident_date')}|{metadata.get('event_date_text')}|{metadata.get('event_dates')}".encode()).hexdigest()
                        stype=TimelineSourceType(row.result_type+"_RESULT")
                        if self._processed(investigation_id,stype,row.id,source_hash): continue
                        published=parse_date(row.published_at or metadata.get("publication_date"))
                        candidates=[(m.group(0),snippet[max(0,m.start()-220):min(len(snippet),m.end()+220)]) for m in DATE_RX.finditer(snippet)]
                        for key in ("event_date","incident_date","event_date_text"):
                            if isinstance(metadata.get(key),str): candidates.append((metadata[key],snippet))
                        if isinstance(metadata.get("event_dates"),list): candidates.extend((raw,snippet) for raw in metadata["event_dates"] if isinstance(raw,str))
                        for raw,context in candidates:
                            parsed=parse_date(raw)
                            if parsed.precision=="UNKNOWN": continue
                            sentence=re.split(r"(?<=[.!?])\s+",context)[0].strip()
                            kind=TimelineEventType.NEWS_REPORT if row.result_type=="NEWS" else TimelineEventType.SEARCH_RESULT
                            event=self._event(row.title or sentence or "Dated research result",sentence,kind,parsed,stype,row.id,location=None,published=published if published.start else None,hash_value=source_hash)
                            created += self._upsert(investigation_id,event)
            except Exception: partial.append("WEB")
        # Use case IDs persisted in completed historical text-search agent actions.
        # Never derive historical events from a correlation alone or index membership.
        if scope in {"ALL","HISTORICAL"}:
            try:
                with self.db.begin_nested():
                    action_rows=self.db.scalars(select(AgentAction).where(AgentAction.investigation_id==investigation_id,AgentAction.action_type==AgentActionType.SEARCH_HISTORICAL_TEXT,AgentAction.status=="COMPLETED")).all()
                    case_ids=set()
                    for action in action_rows:
                        for match in (action.output_summary or {}).get("matches",[]):
                            try: case_ids.add(UUID(str(match.get("historical_case_id"))))
                            except (ValueError,TypeError): continue
                    cases=self.db.scalars(select(HistoricalCase).where(HistoricalCase.id.in_(case_ids))).all() if case_ids else []
                    for case in cases:
                        source_hash=hashlib.sha256(f"{case.id}:{case.updated_at}".encode()).hexdigest()
                        if self._processed(investigation_id,TimelineSourceType.HISTORICAL_CASE,case.id,source_hash): continue
                        parsed=parse_date(case.case_date.isoformat() if case.case_date else None)
                        event=self._event(case.title,case.summary or case.description or "",TimelineEventType.HISTORICAL_CASE,parsed,TimelineSourceType.HISTORICAL_CASE,case.id,location=case.location,hash_value=source_hash)
                        created += self._upsert(investigation_id,event)
            except Exception: partial.append("HISTORICAL")
        self.db.commit()
        return {"status":"PARTIAL" if partial else "COMPLETED","scope":scope,"created":created,"partial_sources":partial,"events":self.list(investigation_id)}
    def _extract_text(self,text,title,kind,stype,sid,evidence_id=None,source_hash=None):
        out=[]
        for m in DATE_RX.finditer(text or ""):
            raw=m.group(0); parsed=parse_date(raw)
            if parsed.precision=="UNKNOWN": continue
            lo=max(0,(text or "").rfind(".",0,m.start())+1); hi=(text or "").find(".",m.end()); hi=len(text) if hi<0 else hi+1
            sentence=(text or "")[lo:hi].strip()
            # The dated sentence itself must carry content beyond just a date.
            desc=re.sub(re.escape(raw),"",sentence,flags=re.I).strip(" ,.;:-")
            if not desc: continue
            out.append(self._event(desc[:500],sentence,kind,parsed,stype,sid,hash_value=source_hash or hashlib.sha256((text or "").encode()).hexdigest(),evidence_id=evidence_id))
        return out
    def _event(self,title,description,kind,parsed,stype,sid,location=None,published=None,hash_value=None,evidence_id=None):
        return {"title":title,"description":description,"event_type":kind,"date_start":parsed.start,"date_end":parsed.end,"date_precision":parsed.precision,"date_text":parsed.text,"source_type":TimelineSourceType(stype),"source_id":sid,"location":location,"published":published,"hash":hash_value,"evidence_id":evidence_id}
    def _processed(self,investigation_id,source_type,source_id,source_hash):
        return self.db.scalar(select(TimelineEvent.id).join(TimelineEventSource,TimelineEventSource.timeline_event_id==TimelineEvent.id).where(TimelineEvent.investigation_id==investigation_id,TimelineEventSource.source_type==source_type,TimelineEventSource.source_id==source_id,TimelineEventSource.content_hash==source_hash).limit(1)) is not None
    def _upsert(self,inv,event):
        norm=re.sub(r"\W+"," ",event["title"].lower()).strip()
        existing=list(self.db.scalars(select(TimelineEvent).where(TimelineEvent.investigation_id==inv,TimelineEvent.date_start==event["date_start"],TimelineEvent.date_end==event["date_end"],TimelineEvent.date_precision==event["date_precision"],TimelineEvent.event_type==event["event_type"])))
        for item in existing:
            if re.sub(r"\W+"," ",item.title.lower()).strip()!=norm: continue
            linked=self.db.scalar(select(TimelineEventSource).where(TimelineEventSource.timeline_event_id==item.id,TimelineEventSource.source_type==event["source_type"],TimelineEventSource.source_id==event["source_id"]))
            if not linked: self.db.add(TimelineEventSource(timeline_event_id=item.id,source_type=event["source_type"],source_id=event["source_id"],relationship_type="SUPPORTING_SOURCE",content_hash=event["hash"]))
            if event.get("evidence_id"): self.db.merge(TimelineEventEvidence(timeline_event_id=item.id,evidence_id=event["evidence_id"],relationship_type="SUPPORTING_EVIDENCE"))
            return 0
        item=TimelineEvent(investigation_id=inv,title=event["title"],description=event["description"],event_type=event["event_type"],date_start=event["date_start"],date_end=event["date_end"],date_precision=event["date_precision"],date_text=event["date_text"],publication_date_start=event["published"].start if event.get("published") else None,publication_date_end=event["published"].end if event.get("published") else None,location=event["location"],normalized_location=(event["location"].casefold() if event["location"] else None),source_type=event["source_type"],source_id=event["source_id"],historical_case_id=event["source_id"] if event["source_type"]==TimelineSourceType.HISTORICAL_CASE else None,importance=TimelineImportance.MEDIUM,status=TimelineStatus.AI_EXTRACTED,created_by="AI",extraction_hash=event["hash"])
        self.db.add(item); self.db.flush(); self.db.add(TimelineEventSource(timeline_event_id=item.id,source_type=event["source_type"],source_id=event["source_id"],relationship_type="PRIMARY_SOURCE",content_hash=event["hash"]))
        if event.get("evidence_id"): self.db.add(TimelineEventEvidence(timeline_event_id=item.id,evidence_id=event["evidence_id"],relationship_type="SUPPORTING_EVIDENCE"))
        return 1
    def list(self,inv,event_type=None,date_from=None,date_to=None,source_type=None,status=None,q=None):
        query=select(TimelineEvent).where(TimelineEvent.investigation_id==inv)
        if event_type: query=query.where(TimelineEvent.event_type==event_type)
        if date_from: query=query.where(TimelineEvent.date_end>=date_from)
        if date_to: query=query.where(TimelineEvent.date_start<=date_to)
        if source_type: query=query.where(TimelineEvent.source_type==source_type)
        if status: query=query.where(TimelineEvent.status==status)
        rows=list(self.db.scalars(query.order_by(TimelineEvent.date_start.asc().nulls_last(),TimelineEvent.created_at.asc())))
        if q:
            found=[]
            for x in rows:
                searchable=f"{x.title} {x.description} {x.location or ''} {x.date_text}"
                for src in self.db.scalars(select(TimelineEventSource).where(TimelineEventSource.timeline_event_id==x.id)):
                    if src.source_type==TimelineSourceType.EVIDENCE:
                        record=self.db.get(Evidence,src.source_id); searchable+=f" {record.title}" if record else ""
                    elif src.source_type in {TimelineSourceType.WEB_RESULT,TimelineSourceType.NEWS_RESULT,TimelineSourceType.IMAGE_RESULT}:
                        record=self.db.get(WebSearchResult,src.source_id)
                        if record: searchable+=f" {record.title or ''} {record.source_name or ''} {record.url or ''}"
                    elif src.source_type==TimelineSourceType.HISTORICAL_CASE:
                        record=self.db.get(HistoricalCase,src.source_id)
                        if record: searchable+=f" {record.source_name or ''} {record.source_url or ''}"
                if q.casefold() in searchable.casefold(): found.append(x)
            rows=found
        return [self.serialize(x) for x in rows]
    def serialize(self,item):
        sources=list(self.db.scalars(select(TimelineEventSource).where(TimelineEventSource.timeline_event_id==item.id)))
        evidence=list(self.db.scalars(select(TimelineEventEvidence).where(TimelineEventEvidence.timeline_event_id==item.id)))
        correlations=list(self.db.scalars(select(Correlation).where(Correlation.investigation_id==item.investigation_id)))
        linked_ids={s.source_id for s in sources}|{e.evidence_id for e in evidence}
        related=[str(c.id) for c in correlations if c.source_id in linked_ids or c.target_id in linked_ids]
        conflicts=[]
        if item.date_start:
            peers=self.db.scalars(select(TimelineEvent).where(TimelineEvent.investigation_id==item.investigation_id,TimelineEvent.id!=item.id,TimelineEvent.event_type==item.event_type,or_(TimelineEvent.date_start!=item.date_start,TimelineEvent.date_end!=item.date_end)))
            n=lambda t: re.sub(r"\W+"," ",t.lower()).strip()
            conflicts=[{"event_id":str(p.id),"date_text":p.date_text,"date_start":p.date_start.isoformat() if p.date_start else None,"source_type":p.source_type.value if p.source_type else None,"source_id":str(p.source_id) if p.source_id else None} for p in peers if n(p.title)==n(item.title)]
        provenance=[]
        for s in sources:
            detail={"source_type":s.source_type.value,"source_id":str(s.source_id),"relationship_type":s.relationship_type}
            if s.source_type==TimelineSourceType.EVIDENCE:
                record=self.db.get(Evidence,s.source_id)
                if record: detail.update(title=record.title,checksum=record.checksum)
            elif s.source_type in {TimelineSourceType.WEB_RESULT,TimelineSourceType.NEWS_RESULT,TimelineSourceType.IMAGE_RESULT}:
                record=self.db.get(WebSearchResult,s.source_id)
                if record:
                    search=self.db.get(ResearchSearch,record.search_id)
                    detail.update(title=record.title,url=record.url,published_at=record.published_at,search_id=str(record.search_id),research_run_id=str(record.research_run_id),query=search.query if search else None)
                    if record.source_id:
                        src=self.db.get(WebSource,record.source_id)
                        if src: detail.update(source_name=src.source_name,canonical_url=src.canonical_url,domain=src.domain)
            elif s.source_type==TimelineSourceType.HISTORICAL_CASE:
                record=self.db.get(HistoricalCase,s.source_id)
                if record: detail.update(title=record.title,source_name=record.source_name,url=record.source_url,external_id=record.external_id)
            elif s.source_type==TimelineSourceType.INVESTIGATOR:
                detail["title"]="Investigator provided"
            provenance.append(detail)
        rows=list(self.db.scalars(select(TimelineEvent).where(TimelineEvent.investigation_id==item.investigation_id,TimelineEvent.id!=item.id,TimelineEvent.date_start.is_not(None))))
        temporal=[]
        if item.date_start and item.date_end:
            for other in rows:
                if not other.date_start or not other.date_end: continue
                if other.date_start==item.date_start and other.date_end==item.date_end: relation="SAME_DAY" if item.date_start==item.date_end else "OVERLAPS"
                elif item.date_end + timedelta(days=1) == other.date_start or other.date_end + timedelta(days=1) == item.date_start: relation="ADJACENT"
                elif item.date_end < other.date_start: relation="BEFORE"
                elif item.date_start > other.date_end: relation="AFTER"
                elif item.date_start<=other.date_start and item.date_end>=other.date_end: relation="CONTAINS"
                else: relation="OVERLAPS"
                temporal.append({"event_id":str(other.id),"relationship":relation})
        return {"id":str(item.id),"investigation_id":str(item.investigation_id),"title":item.title,"description":item.description,"event_type":item.event_type.value,"date_start":item.date_start.isoformat() if item.date_start else None,"date_end":item.date_end.isoformat() if item.date_end else None,"date_precision":item.date_precision.value,"date_text":item.date_text,"publication_date_start":item.publication_date_start.isoformat() if item.publication_date_start else None,"publication_date_end":item.publication_date_end.isoformat() if item.publication_date_end else None,"location":item.location,"normalized_location":item.normalized_location,"source_type":item.source_type.value if item.source_type else None,"source_id":str(item.source_id) if item.source_id else None,"historical_case_id":str(item.historical_case_id) if item.historical_case_id else None,"correlation_ids":related,"temporal_relationships":temporal,"importance":item.importance.value,"status":item.status.value,"created_by":item.created_by,"sources":provenance,"evidence_ids":[str(e.evidence_id) for e in evidence],"date_variance":conflicts,"created_at":item.created_at.isoformat() if item.created_at else None,"updated_at":item.updated_at.isoformat() if item.updated_at else None}
