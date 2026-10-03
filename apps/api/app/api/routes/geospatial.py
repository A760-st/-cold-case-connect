from datetime import date
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.models.investigation import Investigation
from app.models.geospatial import Location,Contradiction,LocationPrecision
from app.geospatial.schemas import GeocodeRequest,ContradictionReview,ManualLocation
from app.geospatial.service import GeospatialService,GeospatialError

router=APIRouter(prefix="/api/v1")
def _failure(exc):raise HTTPException(404 if exc.code=="INVESTIGATION_NOT_FOUND" else 422,detail=exc.code)
@router.post("/investigations/{investigation_id}/geospatial/geocode")
def geocode(investigation_id:UUID,payload:GeocodeRequest,db:Session=Depends(get_db)):
    try:return {"success":True,"data":GeospatialService(db).geocode(investigation_id,payload.limit)}
    except GeospatialError as e:_failure(e)
@router.get("/investigations/{investigation_id}/geospatial/locations")
def locations(investigation_id:UUID,source_type:str|None=None,precision:LocationPrecision|None=None,date_from:date|None=None,date_to:date|None=None,event_type:str|None=None,conflict_only:bool=False,q:str|None=Query(default=None,max_length=200),limit:int=Query(default=500,ge=1,le=1000),offset:int=Query(default=0,ge=0),include_unmapped:bool=True,db:Session=Depends(get_db)):
    try:return {"success":True,"data":GeospatialService(db).locations(investigation_id,source_type,precision,date_from,date_to,event_type,conflict_only,q,limit,offset,include_unmapped)}
    except GeospatialError as e:_failure(e)
@router.get("/investigations/{investigation_id}/geospatial/heatmap")
def heatmap(investigation_id:UUID,mode:str="ALL_RECORDS",date_from:date|None=None,date_to:date|None=None,precision:str|None=None,event_type:str|None=None,conflict_only:bool=False,limit:int=Query(default=1000,ge=1,le=2000),db:Session=Depends(get_db)):
    try:return {"success":True,"data":GeospatialService(db).heatmap(investigation_id,mode,date_from,date_to,precision,event_type,conflict_only,limit)}
    except GeospatialError as e:_failure(e)
@router.get("/investigations/{investigation_id}/geospatial/summary")
def summary(investigation_id:UUID,db:Session=Depends(get_db)):
    try:return {"success":True,"data":GeospatialService(db).summary(investigation_id)}
    except GeospatialError as e:_failure(e)
@router.post("/investigations/{investigation_id}/geospatial/rebuild")
def rebuild(investigation_id:UUID,db:Session=Depends(get_db)):
    try:return {"success":True,"data":GeospatialService(db).rebuild(investigation_id)}
    except GeospatialError as e:_failure(e)
@router.post("/investigations/{investigation_id}/geospatial/locations",status_code=201)
def add_location(investigation_id:UUID,payload:ManualLocation,db:Session=Depends(get_db)):
    try:return {"success":True,"data":GeospatialService(db).create_manual(investigation_id,payload)}
    except GeospatialError as e:_failure(e)
@router.delete("/contradictions/{contradiction_id}",status_code=204)
def delete_contradiction(contradiction_id:UUID,db:Session=Depends(get_db)):
    item=db.get(Contradiction,contradiction_id)
    if item is None:raise HTTPException(404,detail="CONTRADICTION_NOT_FOUND")
    db.delete(item);db.commit()
