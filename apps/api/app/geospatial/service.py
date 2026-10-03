import re
from datetime import date
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.config import settings
from app.models.investigation import Investigation
from app.models.evidence import Evidence
from app.models.historical_case import HistoricalCase
from app.models.web_research import WebSource, WebSearchResult, ResearchSearch
from app.models.timeline import TimelineEvent, TimelineEventSource, TimelineEventEvidence
from app.models.correlation import Correlation, CorrelationObjectType, CorrelationType
from app.models.agent import AgentAction
from app.models.geospatial import *
from app.geospatial.normalizer import normalize_location, infer_precision, components
from app.geospatial.providers import get_geocoder

class GeospatialError(Exception):
    def __init__(self,code):self.code=code

class GeospatialService:
    def __init__(self,db:Session):self.db=db
    def create_manual(self,inv,payload):
        if not self.db.get(Investigation,inv):raise GeospatialError("INVESTIGATION_NOT_FOUND")
        raw=" ".join(payload.raw_text.split()).strip()[:1000]
        if not raw:raise GeospatialError("INVALID_LOCATION")
        if (payload.latitude is None)!=(payload.longitude is None):raise GeospatialError("COORDINATE_PAIR_REQUIRED")
        normalized=normalize_location(raw)
        loc=self.db.scalar(select(Location).where(Location.investigation_id==inv,Location.raw_text==raw,Location.normalized_name==normalized))
        if loc is None:
            loc=Location(investigation_id=inv,raw_text=raw,normalized_name=normalized,latitude=payload.latitude,longitude=payload.longitude,precision=payload.precision,geocoding_status=GeocodingStatus.NOT_ATTEMPTED,confidence_label=GeoConfidence.UNKNOWN,country=payload.country,state=payload.state,district=payload.district,city=payload.city,locality=payload.locality,metadata_json={"created_by":"INVESTIGATOR","coordinates_provided_by":"INVESTIGATOR" if payload.latitude is not None else None})
            self.db.add(loc);self.db.commit();self.db.refresh(loc)
        return self.serialize(loc)
    def rebuild(self,investigation_id:UUID):
        if not self.db.get(Investigation,investigation_id):raise GeospatialError("INVESTIGATION_NOT_FOUND")
        linked=0
        for row in self.db.scalars(select(Evidence).where(Evidence.investigation_id==investigation_id)):
            md=row.metadata_json or {}; raw=self._first(md,"location","reported_location","address")
            if not raw and row.text_content:
                match=re.search(r"(?im)^\s*(?:reported\s+)?location\s*:\s*(.{1,300})$",row.text_content)
                raw=match.group(1).strip() if match else None
            if raw: linked+=self._associate(investigation_id,raw,md,EvidenceLocation,evidence_id=row.id,relationship="REPORTED_LOCATION")
        for row in self.db.scalars(select(TimelineEvent).where(TimelineEvent.investigation_id==investigation_id,TimelineEvent.location.is_not(None))):
            linked+=self._associate(investigation_id,row.location,{},TimelineEventLocation,timeline_event_id=row.id,relationship="APPROXIMATE_LOCATION" if "near " in row.location.casefold() else "REPORTED_LOCATION")
        for item in self.db.scalars(select(TimelineEventEvidence)):
            event=self.db.get(TimelineEvent,item.timeline_event_id)
            if not event or event.investigation_id!=investigation_id:continue
            for link in self.db.scalars(select(EvidenceLocation).where(EvidenceLocation.evidence_id==item.evidence_id)):
                exists=self.db.scalar(select(TimelineEventLocation.id).where(TimelineEventLocation.timeline_event_id==event.id,TimelineEventLocation.location_id==link.location_id,TimelineEventLocation.relationship_type=="REFERENCE_LOCATION"))
                if not exists:self.db.add(TimelineEventLocation(timeline_event_id=event.id,location_id=link.location_id,relationship_type="REFERENCE_LOCATION"));linked+=1
        case_ids=set(self.db.scalars(select(TimelineEvent.historical_case_id).where(TimelineEvent.investigation_id==investigation_id,TimelineEvent.historical_case_id.is_not(None))))
        for corr in self.db.scalars(select(Correlation).where(Correlation.investigation_id==investigation_id)):
            for kind,cid in ((corr.source_type,corr.source_id),(corr.target_type,corr.target_id)):
                if kind==CorrelationObjectType.HISTORICAL_CASE:case_ids.add(cid)
        for case in self.db.scalars(select(HistoricalCase).where(HistoricalCase.id.in_(case_ids))) if case_ids else []:
            if case.location:linked+=self._associate(investigation_id,case.location,case.metadata_json or {},HistoricalCaseLocation,historical_case_id=case.id,relationship="REPORTED_LOCATION")
        results=self.db.scalars(select(WebSearchResult).where(WebSearchResult.investigation_id==investigation_id)).all()
        source_ids=set()
        for result in results:
            md=result.metadata_json or {};raw=self._first(md,"event_location","reported_location","location","city")
            if raw and result.source_id:
                source_ids.add(result.source_id);linked+=self._associate(investigation_id,raw,md,SourceLocation,source_id=result.source_id,relationship="ARTICLE_LOCATION" if result.result_type.value in {"WEB","NEWS"} else "REFERENCE_LOCATION")
        # Explicit source metadata can contain a location even when a result is not attached.
        for source in self.db.scalars(select(WebSource).where(WebSource.investigation_id==investigation_id)):
            raw=self._first(source.metadata_json or {},"reported_location","location")
            if raw:linked+=self._associate(investigation_id,raw,source.metadata_json or {},SourceLocation,source_id=source.id,relationship="REFERENCE_LOCATION")
        self.db.commit()
        return {"status":"COMPLETED","associations_created":linked,"locations":self.locations(investigation_id)}
    @staticmethod
    def _first(md,*keys):
        for key in keys:
            value=md.get(key)
            if isinstance(value,str) and value.strip():return value.strip()[:1000]
        return None
    def _associate(self,inv,raw,metadata,link_model,relationship,**fk):
        if not isinstance(raw,str) or not raw.strip():return 0
        raw=" ".join(raw.split())[:1000];normalized=normalize_location(raw)
        if not normalized:return 0
        lat=self._number(metadata.get("latitude"),-90,90);lon=self._number(metadata.get("longitude"),-180,180)
        coords=lat is not None and lon is not None
        location=self.db.scalar(select(Location).where(Location.investigation_id==inv,Location.raw_text==raw,Location.normalized_name==normalized))
        if location is None:
            precision=infer_precision(raw,metadata,coords)
            location=Location(investigation_id=inv,raw_text=raw,normalized_name=normalized,latitude=lat if coords else None,longitude=lon if coords else None,precision=precision,geocoding_status=GeocodingStatus.GEOCODED if coords else (GeocodingStatus.PENDING if settings.geocoding_enabled else GeocodingStatus.NOT_ATTEMPTED),geocoding_provider="source_metadata" if coords else None,geocoding_source="stored source coordinates" if coords else None,confidence_label=GeoConfidence.HIGH if coords else GeoConfidence.UNKNOWN,metadata_json={"source_precision":metadata.get("precision") or metadata.get("location_precision"),"coordinates_from_source":coords},**components(raw,metadata))
            self.db.add(location);self.db.flush()
        existing=self.db.scalar(select(link_model.id).where(link_model.location_id==location.id,*(getattr(link_model,key)==value for key,value in fk.items()),link_model.relationship_type==relationship))
        if existing:return 0
        self.db.add(link_model(location_id=location.id,relationship_type=relationship,**fk));return 1
    @staticmethod
    def _number(value,lo,hi):
        try:number=float(value)
        except (ValueError,TypeError):return None
        return number if lo<=number<=hi else None
    def geocode(self,investigation_id:UUID,limit:int=25):
        if not self.db.get(Investigation,investigation_id):raise GeospatialError("INVESTIGATION_NOT_FOUND")
        if not settings.geocoding_enabled:return {"status":"DISABLED","message":"Geocoding unavailable: enable GEOCODING_ENABLED to request provider lookups.","processed":0}
        try:provider=get_geocoder()
        except (ValueError,ImportError):return {"status":"UNAVAILABLE","message":"Configured geocoding provider is unavailable.","processed":0}
        rows=self.db.scalars(select(Location).where(Location.investigation_id==investigation_id,Location.latitude.is_(None),Location.geocoding_status.in_([GeocodingStatus.PENDING,GeocodingStatus.NOT_ATTEMPTED])).order_by(Location.created_at).limit(limit)).all();counts={"GEOCODED":0,"PARTIAL":0,"FAILED":0,"NOT_FOUND":0,"NOT_ATTEMPTED":0}
        for loc in rows:
            query=re.sub(r"^\s*(?:near|nearby|around|approximately|approx\.?|outside|vicinity of)\s+","",loc.normalized_name,flags=re.I)
            result=provider.geocode_location(query);loc.geocoding_status=GeocodingStatus(result.status);loc.geocoding_provider=result.provider
            loc.metadata_json={**(loc.metadata_json or {}),"geocoding":{"provider":result.provider,"raw_query":loc.raw_text,"provider_query":query,"timestamp":date.today().isoformat(),"result":result.raw or {},"display_name":result.display_name}}
            if result.status=="GEOCODED" and result.latitude is not None and result.longitude is not None:
                loc.latitude=result.latitude;loc.longitude=result.longitude;loc.geocoding_source=result.display_name;loc.confidence_label=GeoConfidence(result.confidence)
                for key,value in (result.components or {}).items():
                    if value and not getattr(loc,key):setattr(loc,key,str(value)[:300])
                if loc.precision==LocationPrecision.UNKNOWN:loc.precision=LocationPrecision.CITY if loc.city else LocationPrecision.REGION
            counts[result.status]=counts.get(result.status,0)+1
        self.db.commit()
        return {"status":"COMPLETED" if not any(counts[k] for k in ("FAILED","NOT_FOUND")) else "PARTIAL","processed":len(rows),"counts":counts,"locations":[self.serialize(x) for x in rows]}
    def locations(self,inv,source_type=None,precision=None,date_from=None,date_to=None,event_type=None,conflict_only=False,q=None,limit=500,offset=0,include_unmapped=True):
        if not self.db.get(Investigation,inv):raise GeospatialError("INVESTIGATION_NOT_FOUND")
        rows=self.db.scalars(select(Location).where(Location.investigation_id==inv).order_by(Location.normalized_name,Location.created_at).limit(limit).offset(offset)).all(); result=[]
        for loc in rows:
            records=self._records_for_location(loc)
            if source_type and source_type!="ALL":records=[r for r in records if r["source_type"]==source_type]
            if event_type:records=[r for r in records if r.get("event_type")==event_type]
            if date_from:records=[r for r in records if r.get("date_start") and r["date_end"]>=date_from.isoformat()]
            if date_to:records=[r for r in records if r.get("date_start") and r["date_start"]<=date_to.isoformat()]
            if not records:continue
            if precision and loc.precision.value!=precision:continue
            conflicts=self._conflicts_for_location(loc.id)
            if conflict_only and not conflicts:continue
            if q and q.casefold() not in f"{loc.raw_text} {loc.normalized_name} {loc.city or ''} {loc.state or ''}".casefold():continue
            if loc.latitude is None and not include_unmapped:continue
            result.append({**self.serialize(loc),"records":records,"conflicts":conflicts})
        return result
    def heatmap(self,inv,mode="ALL_RECORDS",date_from=None,date_to=None,precision=None,event_type=None,conflict_only=False,limit=1000):
        valid={"ALL_RECORDS","EVIDENCE","TIMELINE_EVENTS","HISTORICAL_CASES","WEB_SOURCES","NEWS_SOURCES","CORRELATIONS"}
        if mode not in valid:raise GeospatialError("INVALID_HEATMAP_MODE")
        rows=self.locations(inv,date_from=date_from,date_to=date_to,event_type=event_type,precision=precision,conflict_only=conflict_only,limit=limit,include_unmapped=False)
        filter_map={"EVIDENCE":"EVIDENCE","TIMELINE_EVENTS":"TIMELINE_EVENT","HISTORICAL_CASES":"HISTORICAL_CASE","WEB_SOURCES":"WEB_SOURCE","NEWS_SOURCES":"NEWS_SOURCE"}
        if mode in filter_map:
            kind=filter_map[mode]
            for item in rows:item["records"]=[r for r in item["records"] if r["source_type"]==kind]
            rows=[r for r in rows if r["records"]]
        elif mode=="CORRELATIONS":
            correlations=list(self.db.scalars(select(Correlation).where(Correlation.investigation_id==inv,Correlation.correlation_type==CorrelationType.GEOGRAPHIC_OVERLAP)))
            ids={cid for c in correlations for cid in (c.source_id,c.target_id)}
            for item in rows:item["records"]=[r for r in item["records"] if UUID(r["source_id"]) in ids]
            rows=[r for r in rows if r["records"]]
        points=[]
        for item in rows:
            for record in item["records"]:
                points.append({"location_id":item["id"],"latitude":item["latitude"],"longitude":item["longitude"],"precision":item["precision"],"raw_text":item["raw_text"],"weight":1,"record":record,"conflicts":item["conflicts"]})
        correlation_rows=[]
        if mode in {"ALL_RECORDS","CORRELATIONS"}:
            coordinate_by_source={}
            for item in rows:
                for record in item["records"]:coordinate_by_source[record["source_id"]]=(item["latitude"],item["longitude"],item["normalized_name"])
            for corr in self.db.scalars(select(Correlation).where(Correlation.investigation_id==inv,Correlation.correlation_type==CorrelationType.GEOGRAPHIC_OVERLAP)):
                a=coordinate_by_source.get(str(corr.source_id));b=coordinate_by_source.get(str(corr.target_id))
                if a and b:correlation_rows.append({"id":str(corr.id),"source_id":str(corr.source_id),"target_id":str(corr.target_id),"source_location":a[2],"target_location":b[2],"coordinates":[[a[0],a[1]],[b[0],b[1]]],"type":corr.correlation_type.value,"score":corr.score,"explanation":corr.explanation,"review_status":"REQUIRES_VERIFICATION"})
        return {"mode":mode,"methodology":"Each mapped source-backed record contributes weight 1. Points are record density only, not crime or risk probability.","record_count":len(points),"points":points[:limit],"correlations":correlation_rows}
    def summary(self,inv):
        if not self.db.get(Investigation,inv):raise GeospatialError("INVESTIGATION_NOT_FOUND")
        locations=list(self.db.scalars(select(Location).where(Location.investigation_id==inv)));mapped=[l for l in locations if l.latitude is not None and l.longitude is not None]
        from app.models.agent import AgentAction,AgentActionType
        record_counts={"EVIDENCE":self.db.scalar(select(func.count(Evidence.id)).where(Evidence.investigation_id==inv)) or 0,"TIMELINE_EVENT":self.db.scalar(select(func.count(TimelineEvent.id)).where(TimelineEvent.investigation_id==inv)) or 0,"WEB_SOURCE":self.db.scalar(select(func.count(WebSearchResult.id)).where(WebSearchResult.investigation_id==inv)) or 0,"INVESTIGATOR":sum((loc.metadata_json or {}).get("created_by")=="INVESTIGATOR" for loc in locations)}
        case_ids=set(self.db.scalars(select(TimelineEvent.historical_case_id).where(TimelineEvent.investigation_id==inv,TimelineEvent.historical_case_id.is_not(None))))
        for action in self.db.scalars(select(AgentAction).where(AgentAction.investigation_id==inv,AgentAction.action_type==AgentActionType.SEARCH_HISTORICAL_TEXT)):
            for match in (action.output_summary or {}).get("matches",[]):
                try:case_ids.add(UUID(str(match.get("historical_case_id"))))
                except (ValueError,TypeError):pass
        record_counts["HISTORICAL_CASE"]=self.db.scalar(select(func.count(HistoricalCase.id)).where(HistoricalCase.id.in_(case_ids))) or 0 if case_ids else 0
        unique_records=set()
        for loc in mapped:
            for rec in self._records_for_location(loc):unique_records.add((rec["source_type"],rec["source_id"]))
        mapped_count=len(unique_records);all_count=sum(record_counts.values())
        contradictions=list(self.db.scalars(select(Contradiction).where(Contradiction.investigation_id==inv)))
        return {"mapped_records":mapped_count,"unmapped_records":max(0,all_count-mapped_count),"unique_locations":len(locations),"exact_locations":sum(l.precision==LocationPrecision.EXACT_POINT for l in locations),"approximate_locations":sum(l.precision==LocationPrecision.APPROXIMATE for l in locations),"countries":len({l.country for l in mapped if l.country}),"states":len({l.state for l in mapped if l.state}),"cities":len({l.city for l in mapped if l.city}),"geocoding_status":{status.value:sum(l.geocoding_status==status for l in locations) for status in GeocodingStatus},"heatmap_records":mapped_count,"contradiction_count":len(contradictions),"open_contradictions":sum(c.status in {ContradictionStatus.OPEN,ContradictionStatus.UNDER_REVIEW,ContradictionStatus.REQUIRES_VERIFICATION} for c in contradictions)}
    def _records_for_location(self,loc):
        records=[]
        if (loc.metadata_json or {}).get("created_by")=="INVESTIGATOR":records.append(self._record("INVESTIGATOR",loc.id,"Investigator-added location",None,"PRIMARY_LOCATION",status="Requires Verification"))
        for link in self.db.scalars(select(EvidenceLocation).where(EvidenceLocation.location_id==loc.id)):
            row=self.db.get(Evidence,link.evidence_id)
            if row:records.append(self._record("EVIDENCE",row.id,row.title,row.created_at.date() if row.created_at else None,link.relationship_type,url=None))
        for link in self.db.scalars(select(TimelineEventLocation).where(TimelineEventLocation.location_id==loc.id)):
            row=self.db.get(TimelineEvent,link.timeline_event_id)
            if row:records.append(self._record("TIMELINE_EVENT",row.id,row.title,row.date_start,link.relationship_type,event_type=row.event_type.value,date_end=row.date_end.isoformat() if row.date_end else None,status=row.status.value))
        for link in self.db.scalars(select(HistoricalCaseLocation).where(HistoricalCaseLocation.location_id==loc.id)):
            row=self.db.get(HistoricalCase,link.historical_case_id)
            if row:records.append(self._record("HISTORICAL_CASE",row.id,row.title,row.case_date,link.relationship_type,case_type=row.case_type,url=row.source_url,source_name=row.source_name))
        for link in self.db.scalars(select(SourceLocation).where(SourceLocation.location_id==loc.id)):
            row=self.db.get(WebSource,link.source_id)
            if row:
                results=list(self.db.scalars(select(WebSearchResult).where(WebSearchResult.source_id==row.id)))
                if results:
                    for result in results:
                        search=self.db.get(ResearchSearch,result.search_id);kind="NEWS_SOURCE" if result.result_type.value=="NEWS" else "WEB_SOURCE"
                        records.append(self._record(kind,result.id,result.title or row.title, self._parse_pub(result.published_at),link.relationship_type,url=result.url or row.url,source_name=result.source_name or row.source_name,research_run_id=str(result.research_run_id),query=search.query if search else None))
                else:records.append(self._record("WEB_SOURCE",row.id,row.title,None,link.relationship_type,url=row.url,source_name=row.source_name))
        return records
    @staticmethod
    def _parse_pub(raw):
        if not raw:return None
        from app.timeline.date_parser import parse_date
        return parse_date(raw).start
    @staticmethod
    def _record(kind,id,title,dt,relationship,**extra):return {"source_type":kind,"source_id":str(id),"title":title,"date_start":dt.isoformat() if isinstance(dt,date) else None,"date_end":extra.pop("date_end",None) or (dt.isoformat() if isinstance(dt,date) else None),"relationship_type":relationship,**extra}
    def _conflicts_for_location(self,location_id):
        return [{"id":str(c.id),"type":c.type.value,"status":c.status.value,"description":c.description} for c in self.db.scalars(select(Contradiction).where(Contradiction.investigation_id==self.db.scalar(select(Location.investigation_id).where(Location.id==location_id)),(Contradiction.location_a_id==location_id)|(Contradiction.location_b_id==location_id)))]
    def serialize(self,loc):return {"id":str(loc.id),"investigation_id":str(loc.investigation_id),"raw_text":loc.raw_text,"normalized_name":loc.normalized_name,"latitude":loc.latitude,"longitude":loc.longitude,"precision":loc.precision.value,"geocoding_status":loc.geocoding_status.value,"geocoding_source":loc.geocoding_source,"geocoding_provider":loc.geocoding_provider,"confidence_label":loc.confidence_label.value,"country":loc.country,"state":loc.state,"district":loc.district,"city":loc.city,"locality":loc.locality,"metadata":loc.metadata_json or {},"created_at":loc.created_at.isoformat() if loc.created_at else None}
