from datetime import date
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.models.investigation import Investigation
from app.models.timeline import TimelineEvent, TimelineStatus, TimelineSourceType, TimelineEventType
from app.timeline.schemas import GenerateTimeline, ManualTimelineEvent, TimelineEventPatch
from app.timeline.service import TimelineService, TimelineError

router=APIRouter(prefix="/api/v1")
def _get(db,event_id):
    row=db.get(TimelineEvent,event_id)
    if not row: raise HTTPException(404,detail="TIMELINE_EVENT_NOT_FOUND")
    return row
@router.post("/investigations/{investigation_id}/timeline/generate")
def generate(investigation_id:UUID,payload:GenerateTimeline,db:Session=Depends(get_db)):
    try: return {"success":True,"data":TimelineService(db).generate(investigation_id,payload.scope)}
    except TimelineError as e: raise HTTPException(404,detail=e.code)
@router.get("/investigations/{investigation_id}/timeline")
def list_events(investigation_id:UUID,event_type:TimelineEventType|None=None,date_from:date|None=None,date_to:date|None=None,source_type:TimelineSourceType|None=None,status:TimelineStatus|None=None,q:str|None=Query(default=None,max_length=200),db:Session=Depends(get_db)):
    if not db.get(Investigation,investigation_id): raise HTTPException(404,detail="INVESTIGATION_NOT_FOUND")
    return {"success":True,"data":TimelineService(db).list(investigation_id,event_type,date_from,date_to,source_type,status,q)}
@router.get("/timeline/events/{event_id}")
def get_event(event_id:UUID,db:Session=Depends(get_db)): return {"success":True,"data":TimelineService(db).serialize(_get(db,event_id))}
@router.post("/investigations/{investigation_id}/timeline/events",status_code=201)
def create_event(investigation_id:UUID,payload:ManualTimelineEvent,db:Session=Depends(get_db)):
    if not db.get(Investigation,investigation_id): raise HTTPException(404,detail="INVESTIGATION_NOT_FOUND")
    if payload.date_end and payload.date_start and payload.date_end<payload.date_start: raise HTTPException(422,detail="INVALID_DATE_RANGE")
    item=TimelineEvent(investigation_id=investigation_id,title=payload.title.strip(),description=payload.description,event_type=payload.event_type,date_start=payload.date_start,date_end=payload.date_end,date_precision=payload.date_precision,date_text=payload.date_text or (payload.date_start.isoformat() if payload.date_start else ""),location=payload.location,normalized_location=payload.location.casefold() if payload.location else None,source_type=TimelineSourceType.INVESTIGATOR,source_id=investigation_id,importance=payload.importance,status=TimelineStatus.INVESTIGATOR_ADDED,created_by="INVESTIGATOR")
    db.add(item);db.flush();from app.models.timeline import TimelineEventSource;db.add(TimelineEventSource(timeline_event_id=item.id,source_type=TimelineSourceType.INVESTIGATOR,source_id=investigation_id,relationship_type="PRIMARY_SOURCE"));db.commit();db.refresh(item)
    return {"success":True,"data":TimelineService(db).serialize(item)}
@router.patch("/timeline/events/{event_id}")
def patch_event(event_id:UUID,payload:TimelineEventPatch,db:Session=Depends(get_db)):
    item=_get(db,event_id)
    for key,value in payload.model_dump(exclude_unset=True).items(): setattr(item,key,value)
    if item.date_start and item.date_end and item.date_end<item.date_start: raise HTTPException(422,detail="INVALID_DATE_RANGE")
    if item.date_precision.value=="UNKNOWN" and (item.date_start or item.date_end): raise HTTPException(422,detail="INVALID_DATE_PRECISION")
    if item.date_precision.value!="UNKNOWN" and not item.date_start: raise HTTPException(422,detail="INVALID_DATE_PRECISION")
    if payload.status is None: item.status=TimelineStatus.REVIEWED
    item.created_by="INVESTIGATOR";db.commit();db.refresh(item)
    return {"success":True,"data":TimelineService(db).serialize(item)}
@router.delete("/timeline/events/{event_id}",status_code=204)
def delete_event(event_id:UUID,db:Session=Depends(get_db)):
    item=_get(db,event_id);db.delete(item);db.commit()
