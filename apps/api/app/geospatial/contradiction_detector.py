import re
from datetime import date
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.timeline import TimelineEvent, TimelineEventSource
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
            if title and e.source_id:groups.setdefault((e.event_type.value,title),[]).append(e)
        for rows in groups.values():
            for i,a in enumerate(rows):
                for b in rows[i+1:]:
                    if a.date_start and b.date_start and (a.date_start!=b.date_start or a.date_end!=b.date_end):
                        created+=self._save(investigation_id,ContradictionType.DATE_CONFLICT,"TIMELINE_EVENT",a.id,"TIMELINE_EVENT",b.id,str(a.date_text),str(b.date_text),date_a=a.date_start,date_b=b.date_start,subject_type="TIMELINE_EVENT",subject_id=a.id,description=f"Sources linked to timeline entries titled ‘{a.title}’ report different dates.")
                    if a.location and b.location and key(a.location)!=key(b.location):
                        created+=self._save(investigation_id,ContradictionType.LOCATION_CONFLICT,"TIMELINE_EVENT",a.id,"TIMELINE_EVENT",b.id,a.location,b.location,subject_type="TIMELINE_EVENT",subject_id=a.id,description=f"Sources linked to timeline entries titled ‘{a.title}’ report different locations.")
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
                            if va and vb and key(va)!=key(vb):created+=self._save(investigation_id,ContradictionType.ATTRIBUTE_CONFLICT,"EVIDENCE",a.id,"EVIDENCE",b.id,va,vb,subject_type="EVIDENCE_TITLE",subject_id=a.id,description=f"Evidence records titled ‘{a.title}’ report different values for ‘{name}’.",metadata={"attribute":name})
        self.db.commit()
        return {"status":"COMPLETED","created":created,"items":self.list(investigation_id)}
    def _evidence_location(self,eid):
        link=self.db.scalar(select(EvidenceLocation).where(EvidenceLocation.evidence_id==eid).limit(1))
        return self.db.get(Location,link.location_id) if link else None
    def _save(self,inv,kind,a_type,a_id,b_type,b_id,value_a,value_b,description,subject_type=None,subject_id=None,date_a=None,date_b=None,location_a_id=None,location_b_id=None,metadata=None):
        # Canonical pair ordering makes repeated detector runs idempotent.
        a=(a_type,str(a_id));b=(b_type,str(b_id))
        if b<a:a,b=b,a;value_a,value_b=value_b,value_a;date_a,date_b=date_b,date_a;location_a_id,location_b_id=location_b_id,location_a_id
        existing=self.db.scalar(select(Contradiction.id).where(Contradiction.investigation_id==inv,Contradiction.type==kind,Contradiction.source_a_type==a[0],Contradiction.source_a_id==UUID(a[1]),Contradiction.source_b_type==b[0],Contradiction.source_b_id==UUID(b[1])))
        if existing:return 0
        self.db.add(Contradiction(investigation_id=inv,type=kind,severity=ContradictionSeverity.MEDIUM,description=description,subject_type=subject_type,subject_id=subject_id,source_a_type=a[0],source_a_id=UUID(a[1]),source_b_type=b[0],source_b_id=UUID(b[1]),value_a=value_a,value_b=value_b,date_a=date_a,date_b=date_b,location_a_id=location_a_id,location_b_id=location_b_id,status=ContradictionStatus.OPEN,metadata_json=metadata or {}));return 1
    def list(self,inv,type_filter=None,status=None,limit=500,offset=0):
        q=select(Contradiction).where(Contradiction.investigation_id==inv)
        if type_filter:q=q.where(Contradiction.type==type_filter)
        if status:q=q.where(Contradiction.status==status)
        rows=self.db.scalars(q.order_by(Contradiction.created_at.desc()).limit(limit).offset(offset)).all()
        return [self.serialize(x) for x in rows]
    def serialize(self,c):
        return {"id":str(c.id),"investigation_id":str(c.investigation_id),"type":c.type.value,"severity":c.severity.value,"description":c.description,"subject_type":c.subject_type,"subject_id":str(c.subject_id) if c.subject_id else None,"source_a_type":c.source_a_type,"source_a_id":str(c.source_a_id),"source_b_type":c.source_b_type,"source_b_id":str(c.source_b_id),"source_a":self._source(c.source_a_type,c.source_a_id),"source_b":self._source(c.source_b_type,c.source_b_id),"value_a":c.value_a,"value_b":c.value_b,"date_a":c.date_a.isoformat() if c.date_a else None,"date_b":c.date_b.isoformat() if c.date_b else None,"location_a_id":str(c.location_a_id) if c.location_a_id else None,"location_b_id":str(c.location_b_id) if c.location_b_id else None,"status":c.status.value,"investigator_note":c.investigator_note,"metadata":c.metadata_json or {},"created_at":c.created_at.isoformat() if c.created_at else None,"updated_at":c.updated_at.isoformat() if c.updated_at else None}
    def _source(self,kind,sid):
        try:
            from app.models.timeline import TimelineEvent
            from app.models.web_research import WebSearchResult,WebSource
            if kind=="EVIDENCE":
                row=self.db.get(Evidence,sid);return {"id":str(sid),"type":kind,"title":row.title if row else None,"text":(row.text_content or row.description)[:500] if row else None}
            if kind=="TIMELINE_EVENT":
                row=self.db.get(TimelineEvent,sid);return {"id":str(sid),"type":kind,"title":row.title if row else None,"date_text":row.date_text if row else None,"location":row.location if row else None}
            if kind=="WEB_RESULT":
                row=self.db.get(WebSearchResult,sid);return {"id":str(sid),"type":kind,"title":row.title if row else None,"url":row.url if row else None,"research_run_id":str(row.research_run_id) if row else None}
            if kind=="HISTORICAL_CASE":
                from app.models.historical_case import HistoricalCase
                row=self.db.get(HistoricalCase,sid);return {"id":str(sid),"type":kind,"title":row.title if row else None,"url":row.source_url if row else None}
        except Exception:pass
        return {"id":str(sid),"type":kind}
