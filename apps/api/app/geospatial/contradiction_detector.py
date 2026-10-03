import hashlib
import json
import re
from datetime import date
from uuid import UUID
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from app.models.timeline import TimelineEvent, TimelineEventEvidence, TimelineEventSource
from app.models.evidence import Evidence
from app.models.geospatial import EvidenceLocation, Location, Contradiction, ContradictionType, ContradictionSeverity, ContradictionStatus

def key(value):return re.sub(r"\W+"," ",(value or "").casefold()).strip()

class ContradictionDetector:
    """Deterministic source comparison. It reports disagreements and never selects a preferred value."""
    def __init__(self,db:Session):self.db=db
    def detect(self,investigation_id:UUID):
        created=0;events=list(self.db.scalars(select(TimelineEvent).where(TimelineEvent.investigation_id==investigation_id)))
        groups={}
        for e in events:
            title=key(e.title)
            if title and e.source_id:groups.setdefault(title,[]).append(e)
        for rows in groups.values():
            for i,a in enumerate(rows):
                for b in rows[i+1:]:
                    if a.event_type!=b.event_type:
                        created+=self._save(investigation_id,ContradictionType.EVENT_CONFLICT,"TIMELINE_EVENT",a.id,"TIMELINE_EVENT",b.id,a.event_type.value,b.event_type.value,subject_type="EVENT_TITLE",subject_id=a.id,description=f"Timeline entries titled ‘{a.title}’ classify the event differently.",related_event_id=a.id)
                    if a.date_start and b.date_start and (a.date_start!=b.date_start or a.date_end!=b.date_end):
                        created+=self._save(investigation_id,ContradictionType.DATE_CONFLICT,"TIMELINE_EVENT",a.id,"TIMELINE_EVENT",b.id,str(a.date_text),str(b.date_text),date_a=a.date_start,date_b=b.date_start,subject_type="TIMELINE_EVENT",subject_id=a.id,description=f"Sources linked to timeline entries titled ‘{a.title}’ report different dates.",date_precision=f"{a.date_precision.value}/{b.date_precision.value}",related_event_id=a.id,priority="HIGH")
                        if a.source_id and b.source_id:
                            created+=self._save(investigation_id,ContradictionType.SOURCE_CONFLICT,"TIMELINE_EVENT",a.id,"TIMELINE_EVENT",b.id,str(a.date_text),str(b.date_text),subject_type="TIMELINE_EVENT",subject_id=a.id,description="Source-backed timeline entries contain conflicting date reports.",metadata={"classification":"CONFLICTING_REPORTS"},related_event_id=a.id,priority="HIGH")
                    if a.location and b.location and key(a.location)!=key(b.location):
                        created+=self._save(investigation_id,ContradictionType.LOCATION_CONFLICT,"TIMELINE_EVENT",a.id,"TIMELINE_EVENT",b.id,a.location,b.location,subject_type="TIMELINE_EVENT",subject_id=a.id,description=f"Two source records associated with the same timeline event report different locations: {a.location} and {b.location}.",related_event_id=a.id,priority="HIGH")
                    ta=self._time(a.date_text);tb=self._time(b.date_text)
                    if ta and tb and ta!=tb:
                        created+=self._save(investigation_id,ContradictionType.TIME_CONFLICT,"TIMELINE_EVENT",a.id,"TIMELINE_EVENT",b.id,ta,tb,subject_type="TIMELINE_EVENT",subject_id=a.id,description=f"Source-backed timeline entries titled ‘{a.title}’ report different times ({ta} and {tb}); timezone information is not inferred.",related_event_id=a.id)
                    if self._explicit_order_conflict(a,b):
                        created+=self._save(investigation_id,ContradictionType.TIMELINE_CONFLICT,"TIMELINE_EVENT",a.id,"TIMELINE_EVENT",b.id,str(a.date_text),str(b.date_text),date_a=a.date_start,date_b=b.date_start,subject_type="TIMELINE_EVENT",subject_id=a.id,description="The recorded dates conflict with a stated chronological relationship.",related_event_id=a.id,priority="HIGH")
        evidence=list(self.db.scalars(select(Evidence).where(Evidence.investigation_id==investigation_id)))
        evidence_groups={}
        for e in evidence:
            if e.title:evidence_groups.setdefault(key(e.title),[]).append(e)
        for rows in evidence_groups.values():
            for i,a in enumerate(rows):
                for b in rows[i+1:]:
                    from app.timeline.date_parser import parse_date
                    raw_a=(a.metadata_json or {}).get("event_date") or (a.metadata_json or {}).get("incident_date");raw_b=(b.metadata_json or {}).get("event_date") or (b.metadata_json or {}).get("incident_date")
                    da=parse_date(raw_a if isinstance(raw_a,str) else "");db=parse_date(raw_b if isinstance(raw_b,str) else "")
                    if da.start and db.start and (da.start!=db.start or da.end!=db.end):
                        created+=self._save(investigation_id,ContradictionType.DATE_CONFLICT,"EVIDENCE",a.id,"EVIDENCE",b.id,da.text,db.text,date_a=da.start,date_b=db.start,subject_type="EVIDENCE_TITLE",subject_id=a.id,description=f"Evidence records titled ‘{a.title}’ contain different explicitly recorded event dates.")
                    loc_a=self._evidence_location(a.id);loc_b=self._evidence_location(b.id)
                    if loc_a and loc_b and loc_a.normalized_name!=loc_b.normalized_name:
                        created+=self._save(investigation_id,ContradictionType.LOCATION_CONFLICT,"EVIDENCE",a.id,"EVIDENCE",b.id,loc_a.raw_text,loc_b.raw_text,location_a_id=loc_a.id,location_b_id=loc_b.id,subject_type="EVIDENCE_TITLE",subject_id=a.id,description=f"Evidence records titled ‘{a.title}’ contain different reported locations.")
                    attr_a=(a.metadata_json or {}).get("attributes",{});attr_b=(b.metadata_json or {}).get("attributes",{})
                    if isinstance(attr_a,dict) and isinstance(attr_b,dict):
                        for name in sorted(set(attr_a)&set(attr_b)):
                            va,vb=str(attr_a[name]).strip(),str(attr_b[name]).strip()
                            if va and vb and key(va)!=key(vb):
                                numeric_a=self._numeric(va);numeric_b=self._numeric(vb)
                                kind=ContradictionType.NUMERIC_CONFLICT if numeric_a and numeric_b and numeric_a[1]==numeric_b[1] else ContradictionType.ATTRIBUTE_CONFLICT
                                created+=self._save(investigation_id,kind,"EVIDENCE",a.id,"EVIDENCE",b.id,va,vb,subject_type="EVIDENCE_TITLE",subject_id=a.id,description=f"Evidence records titled ‘{a.title}’ report different values for ‘{name}’.",metadata={"attribute":name,"value_a":numeric_a,"value_b":numeric_b},priority="MEDIUM")
                        entities_a=(a.metadata_json or {}).get("entities",[]);entities_b=(b.metadata_json or {}).get("entities",[])
                        if isinstance(entities_a,list) and isinstance(entities_b,list):
                            by_a={str(x.get("id")):x for x in entities_a if isinstance(x,dict) and x.get("id")};by_b={str(x.get("id")):x for x in entities_b if isinstance(x,dict) and x.get("id")}
                            for entity_id in set(by_a)&set(by_b):
                                org_a=by_a[entity_id].get("organization");org_b=by_b[entity_id].get("organization")
                                if isinstance(org_a,str) and isinstance(org_b,str) and key(org_a)!=key(org_b):created+=self._save(investigation_id,ContradictionType.ENTITY_CONFLICT,"EVIDENCE",a.id,"EVIDENCE",b.id,org_a,org_b,subject_type="ENTITY",subject_id=a.id,description="Evidence records associated with the same structured entity report different organization affiliations.",metadata={"entity_id":entity_id})
        self.db.commit()
        return {"status":"COMPLETED","created":created,"items":self.list(investigation_id)}
    def _evidence_location(self,eid):
        link=self.db.scalar(select(EvidenceLocation).where(EvidenceLocation.evidence_id==eid).limit(1))
        return self.db.get(Location,link.location_id) if link else None
    @staticmethod
    def _time(raw):
        match=re.search(r"\b(1[0-2]|0?[1-9]):([0-5]\d)\s*(AM|PM)\b|\b([01]?\d|2[0-3]):([0-5]\d)\b",raw or "",re.I)
        if not match:return None
        return (match.group(0).upper().replace(" ",""))
    @staticmethod
    def _numeric(value):
        match=re.fullmatch(r"\s*(?:about|approximately|approx\.?\s*)?(\d+(?:\.\d+)?)\s*([\w%/-]*)\s*",value,re.I)
        return (float(match.group(1)),match.group(2).casefold()) if match else None
    @staticmethod
    def _explicit_order_conflict(a,b):
        # Only act on explicit event-title references with a directly stated order.
        for source,target,expected in ((a,b,"before"),(b,a,"before")):
            text=f"{source.description or ''} {source.date_text or ''}"
            escaped=re.escape(key(target.title))
            if escaped and re.search(rf"\b{re.escape(key(source.title))}\s+{expected}\s+{escaped}\b",key(text)):
                return bool(source.date_start and target.date_start and source.date_start>target.date_start)
        return False

    def _save(self,inv,kind,a_type,a_id,b_type,b_id,value_a,value_b,description,subject_type=None,subject_id=None,date_a=None,date_b=None,location_a_id=None,location_b_id=None,metadata=None,date_precision=None,related_event_id=None,priority="MEDIUM"):
        # Canonical pair ordering makes repeated detector runs idempotent.
        a=(a_type,str(a_id));b=(b_type,str(b_id))
        if b<a:a,b=b,a;value_a,value_b=value_b,value_a;date_a,date_b=date_b,date_a;location_a_id,location_b_id=location_b_id,location_a_id
        fingerprint=hashlib.sha256(json.dumps([str(inv),kind.value,a,b,(metadata or {}).get("attribute"),(metadata or {}).get("entity_id")],separators=(",",":"),sort_keys=True).encode()).hexdigest()
        existing=self.db.scalar(select(Contradiction.id).where(Contradiction.fingerprint==fingerprint))
        if existing is None:
            # Rows created by Phase 9 predate fingerprints. Match their original
            # unique-pair identity so the first Phase 10 detection does not
            # duplicate a finding after migration.
            existing=self.db.scalar(select(Contradiction.id).where(
                Contradiction.investigation_id==inv,
                Contradiction.type==kind,
                Contradiction.fingerprint.is_(None),
                or_(
                    and_(Contradiction.source_a_type==a[0],Contradiction.source_a_id==UUID(a[1]),Contradiction.source_b_type==b[0],Contradiction.source_b_id==UUID(b[1])),
                    and_(Contradiction.source_a_type==b[0],Contradiction.source_a_id==UUID(b[1]),Contradiction.source_b_type==a[0],Contradiction.source_b_id==UUID(a[1])),
                ),
            ))
        if existing:return 0
        severity=ContradictionSeverity(priority)
        details=dict(metadata or {})
        if priority=="HIGH":details.setdefault("priority_factors",["TIMELINE_INTEGRITY" if kind in {ContradictionType.DATE_CONFLICT,ContradictionType.TIME_CONFLICT,ContradictionType.TIMELINE_CONFLICT} else "LOCATION_RELATIONSHIP_IMPACT"])
        self.db.add(Contradiction(investigation_id=inv,type=kind,severity=severity,priority=priority,description=description,subject_type=subject_type,subject_id=subject_id,source_a_type=a[0],source_a_id=UUID(a[1]),source_b_type=b[0],source_b_id=UUID(b[1]),value_a=value_a,value_b=value_b,date_a=date_a,date_b=date_b,location_a_id=location_a_id,location_b_id=location_b_id,status=ContradictionStatus.OPEN,metadata_json=details,fingerprint=fingerprint,date_precision=date_precision,related_event_id=related_event_id));return 1
    def list(self,inv,type_filter=None,status=None,limit=500,offset=0):
        q=select(Contradiction).where(Contradiction.investigation_id==inv)
        if type_filter:q=q.where(Contradiction.type==type_filter)
        if status:q=q.where(Contradiction.status==status)
        rows=self.db.scalars(q.order_by(Contradiction.created_at.desc()).limit(limit).offset(offset)).all()
        return [self.serialize(x) for x in rows]
    def serialize(self,c):
        return {"id":str(c.id),"investigation_id":str(c.investigation_id),"type":c.type.value,"severity":c.severity.value,"priority":c.priority,"description":c.description,"subject_type":c.subject_type,"subject_id":str(c.subject_id) if c.subject_id else None,"related_event_id":str(c.related_event_id) if c.related_event_id else None,"date_precision":c.date_precision,"source_a_type":c.source_a_type,"source_a_id":str(c.source_a_id),"source_b_type":c.source_b_type,"source_b_id":str(c.source_b_id),"source_a":self._source(c.source_a_type,c.source_a_id),"source_b":self._source(c.source_b_type,c.source_b_id),"value_a":c.value_a,"value_b":c.value_b,"date_a":c.date_a.isoformat() if c.date_a else None,"date_b":c.date_b.isoformat() if c.date_b else None,"location_a_id":str(c.location_a_id) if c.location_a_id else None,"location_b_id":str(c.location_b_id) if c.location_b_id else None,"status":c.status.value,"investigator_note":c.investigator_note,"metadata":c.metadata_json or {},"created_at":c.created_at.isoformat() if c.created_at else None,"updated_at":c.updated_at.isoformat() if c.updated_at else None}
    def _source(self,kind,sid):
        try:
            from app.models.timeline import TimelineEvent
            from app.models.web_research import WebSearchResult,WebSource
            if kind=="EVIDENCE":
                row=self.db.get(Evidence,sid);return {"id":str(sid),"type":kind,"title":row.title if row else None,"text":(row.text_content or row.description)[:500] if row else None,"investigation_id":str(row.investigation_id) if row else None}
            if kind=="TIMELINE_EVENT":
                row=self.db.get(TimelineEvent,sid)
                evidence_ids=list(self.db.scalars(select(TimelineEventEvidence.evidence_id).where(TimelineEventEvidence.timeline_event_id==sid))) if row else []
                event_sources=list(self.db.scalars(select(TimelineEventSource).where(TimelineEventSource.timeline_event_id==sid))) if row else []
                source_details=[]
                for source in event_sources:
                    entry={"id":str(source.source_id),"type":source.source_type.value,"relationship_type":source.relationship_type}
                    if source.source_type.value in {"WEB_RESULT","NEWS_RESULT","IMAGE_RESULT"}:
                        result=self.db.get(WebSearchResult,source.source_id)
                        if result:entry.update({"title":result.title,"url":result.url,"research_run_id":str(result.research_run_id)})
                    source_details.append(entry)
                return {"id":str(sid),"type":kind,"title":row.title if row else None,"date_text":row.date_text if row else None,"location":row.location if row else None,"investigation_id":str(row.investigation_id) if row else None,"evidence_ids":[str(x) for x in evidence_ids],"sources":source_details}
            if kind=="WEB_RESULT":
                row=self.db.get(WebSearchResult,sid);return {"id":str(sid),"type":kind,"title":row.title if row else None,"url":row.url if row else None,"research_run_id":str(row.research_run_id) if row else None}
            if kind=="HISTORICAL_CASE":
                from app.models.historical_case import HistoricalCase
                row=self.db.get(HistoricalCase,sid);return {"id":str(sid),"type":kind,"title":row.title if row else None,"url":row.source_url if row else None}
        except Exception:pass
        return {"id":str(sid),"type":kind}
