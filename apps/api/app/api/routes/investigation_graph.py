from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database.session import get_db
from app.investigation_graph.service import GraphError, InvestigationGraphService
from app.models.investigation_graph import GraphBookmark, GraphNote, SourceRelationship, SourceRelationshipType
from app.models.web_research import WebSource

router=APIRouter(prefix="/api/v1")

class NoteCreate(BaseModel):
    node_type:str=Field(min_length=2,max_length=40)
    node_id:UUID
    note:str=Field(min_length=1,max_length=5000)

    @field_validator("note")
    @classmethod
    def nonempty_note(cls,value):
        value=value.strip()
        if not value:raise ValueError("note cannot be blank")
        return value
class BookmarkCreate(BaseModel):
    name:str=Field(min_length=1,max_length=200)
    node_ids:list[str]=Field(default_factory=list,max_length=200)
    filters:dict=Field(default_factory=dict,max_length=32)
    layout:str=Field(default="force",pattern="^(force|hierarchical|timeline)$")

    @field_validator("node_ids")
    @classmethod
    def validate_node_ids(cls,values):
        if any(len(value)>300 or ":" not in value for value in values):raise ValueError("node_ids must contain bounded typed graph IDs")
        return values

    @field_validator("filters")
    @classmethod
    def validate_filters(cls,values):
        allowed={"mode","query","edge_category","source_type","status","date_from","date_to","location_id","node_types","edge_types","source_types","statuses","location_ids","claim_types"}
        if any(key not in allowed for key in values):raise ValueError("unsupported graph bookmark filter")
        for value in values.values():
            if isinstance(value,str) and len(value)>500:raise ValueError("filter value is too long")
            if isinstance(value,list) and (len(value)>100 or any(not isinstance(item,str) or len(item)>120 for item in value)):raise ValueError("filter list is too large")
            if not isinstance(value,(str,int,float,bool,list)):raise ValueError("unsupported filter value")
        return values

    @field_validator("name")
    @classmethod
    def nonempty_name(cls,value):
        value=value.strip()
        if not value:raise ValueError("bookmark name cannot be blank")
        return value
class SourceRelationshipCreate(BaseModel):
    source_a_id:UUID
    source_b_id:UUID
    relationship_type:SourceRelationshipType
    explanation:str=Field(min_length=1,max_length=2000)

    @field_validator("explanation")
    @classmethod
    def nonempty_explanation(cls,value):
        value=value.strip()
        if not value:raise ValueError("explanation cannot be blank")
        return value

def _error(exc):raise HTTPException(exc.status_code,detail=exc.code)

@router.get("/investigations/{investigation_id}/graph")
def get_graph(investigation_id:UUID,node_types:list[str]|None=Query(None,max_length=30),edge_types:list[str]|None=Query(None,max_length=50),source_types:list[str]|None=Query(None,max_length=20),statuses:list[str]|None=Query(None,max_length=30),date_from:str|None=None,date_to:str|None=None,location_ids:list[UUID]|None=Query(None,max_length=200),claim_types:list[str]|None=Query(None,max_length=20),q:str|None=Query(None,max_length=200),limit:int=Query(250,ge=1,le=1000),edge_limit:int=Query(600,ge=1,le=2000),offset:int=Query(0,ge=0),db:Session=Depends(get_db)):
    from datetime import date
    try:
        start=date.fromisoformat(date_from) if date_from else None;end=date.fromisoformat(date_to) if date_to else None
        if start and end and start>end:raise HTTPException(422,detail="INVALID_DATE_RANGE")
        return {"success":True,"data":InvestigationGraphService(db).graph(investigation_id,node_types=node_types,edge_types=edge_types,source_types=source_types,statuses=statuses,date_from=start,date_to=end,location_ids=location_ids,claim_types=claim_types,q=q,limit=limit,edge_limit=edge_limit,offset=offset)}
    except GraphError as exc:_error(exc)
    except ValueError:raise HTTPException(422,detail="INVALID_DATE_FILTER")

@router.get("/investigations/{investigation_id}/graph/node/{node_type}/{node_id}")
def get_node(investigation_id:UUID,node_type:str,node_id:UUID,db:Session=Depends(get_db)):
    try:return {"success":True,"data":InvestigationGraphService(db).node(investigation_id,node_type.upper(),node_id)}
    except GraphError as exc:_error(exc)

@router.get("/investigations/{investigation_id}/graph/neighborhood/{node_type}/{node_id}")
def get_neighborhood(investigation_id:UUID,node_type:str,node_id:UUID,depth:int=Query(1,ge=1,le=5),node_types:list[str]|None=Query(None),edge_types:list[str]|None=Query(None),max_nodes:int=Query(100,ge=1,le=300),db:Session=Depends(get_db)):
    try:return {"success":True,"data":InvestigationGraphService(db).neighborhood(investigation_id,node_type.upper(),node_id,depth,max_nodes,node_types,edge_types)}
    except GraphError as exc:_error(exc)

@router.post("/investigations/{investigation_id}/graph/rebuild")
def rebuild_graph(investigation_id:UUID,db:Session=Depends(get_db)):
    try:
        service=InvestigationGraphService(db);claims=service.extract_structured_claims(investigation_id);result=service.rebuild(investigation_id);result["claims_created"]=claims["created"];result["claims_truncated"]=claims["truncated"];return {"success":True,"data":result}
    except GraphError as exc:_error(exc)

@router.get("/investigations/{investigation_id}/graph/summary")
def graph_summary(investigation_id:UUID,db:Session=Depends(get_db)):
    try:return {"success":True,"data":InvestigationGraphService(db).graph(investigation_id,limit=1,edge_limit=1)["metadata"]}
    except GraphError as exc:_error(exc)

@router.post("/investigations/{investigation_id}/graph/notes",status_code=201)
def add_note(investigation_id:UUID,payload:NoteCreate,db:Session=Depends(get_db)):
    service=InvestigationGraphService(db)
    try:service.node(investigation_id,payload.node_type.upper(),payload.node_id)
    except GraphError as exc:_error(exc)
    item=GraphNote(investigation_id=investigation_id,node_type=payload.node_type.upper(),node_id=payload.node_id,note=payload.note.strip(),created_by="INVESTIGATOR");db.add(item);db.commit();db.refresh(item)
    return {"success":True,"data":{"id":str(item.id),"node_type":item.node_type,"node_id":str(item.node_id),"note":item.note,"created_by":item.created_by,"created_at":item.created_at.isoformat()}}

@router.get("/investigations/{investigation_id}/graph/bookmarks")
def list_bookmarks(investigation_id:UUID,db:Session=Depends(get_db)):
    try:InvestigationGraphService(db)._investigation(investigation_id)
    except GraphError as exc:_error(exc)
    rows=db.scalars(select(GraphBookmark).where(GraphBookmark.investigation_id==investigation_id).order_by(GraphBookmark.created_at.desc())).all()
    return {"success":True,"data":[{"id":str(x.id),"name":x.name,"node_ids":x.node_ids,"filters":x.filters,"layout":x.layout,"created_at":x.created_at.isoformat()} for x in rows]}

@router.post("/investigations/{investigation_id}/graph/bookmarks",status_code=201)
def create_bookmark(investigation_id:UUID,payload:BookmarkCreate,db:Session=Depends(get_db)):
    service=InvestigationGraphService(db)
    try:
        graph=service.graph(investigation_id,limit=1000,edge_limit=2000);valid={n["id"] for n in graph["nodes"]}
        if any(x not in valid for x in payload.node_ids):raise HTTPException(422,detail="BOOKMARK_NODE_OUTSIDE_INVESTIGATION")
    except GraphError as exc:_error(exc)
    item=GraphBookmark(investigation_id=investigation_id,name=payload.name.strip(),node_ids=payload.node_ids,filters=payload.filters,layout=payload.layout);db.add(item);db.commit();db.refresh(item)
    return {"success":True,"data":{"id":str(item.id),"name":item.name,"node_ids":item.node_ids,"filters":item.filters,"layout":item.layout}}

@router.patch("/investigations/{investigation_id}/graph/bookmarks/{bookmark_id}")
def rename_bookmark(investigation_id:UUID,bookmark_id:UUID,payload:BookmarkCreate,db:Session=Depends(get_db)):
    item=db.scalar(select(GraphBookmark).where(GraphBookmark.id==bookmark_id,GraphBookmark.investigation_id==investigation_id))
    if item is None:raise HTTPException(404,detail="GRAPH_BOOKMARK_NOT_FOUND")
    graph=InvestigationGraphService(db).graph(investigation_id,limit=1000,edge_limit=2000);valid={n["id"] for n in graph["nodes"]}
    if any(x not in valid for x in payload.node_ids):raise HTTPException(422,detail="BOOKMARK_NODE_OUTSIDE_INVESTIGATION")
    item.name=payload.name.strip();item.node_ids=payload.node_ids;item.filters=payload.filters;item.layout=payload.layout;db.commit()
    return {"success":True,"data":{"id":str(item.id),"name":item.name,"node_ids":item.node_ids,"filters":item.filters,"layout":item.layout}}

@router.delete("/investigations/{investigation_id}/graph/bookmarks/{bookmark_id}",status_code=204)
def delete_bookmark(investigation_id:UUID,bookmark_id:UUID,db:Session=Depends(get_db)):
    item=db.scalar(select(GraphBookmark).where(GraphBookmark.id==bookmark_id,GraphBookmark.investigation_id==investigation_id))
    if item is None:raise HTTPException(404,detail="GRAPH_BOOKMARK_NOT_FOUND")
    db.delete(item);db.commit()

@router.post("/investigations/{investigation_id}/graph/source-relationships",status_code=201)
def add_source_relationship(investigation_id:UUID,payload:SourceRelationshipCreate,db:Session=Depends(get_db)):
    if payload.source_a_id==payload.source_b_id:raise HTTPException(422,detail="SOURCE_RELATIONSHIP_REQUIRES_DISTINCT_SOURCES")
    ids={payload.source_a_id,payload.source_b_id};rows=list(db.scalars(select(WebSource).where(WebSource.id.in_(ids),WebSource.investigation_id==investigation_id)))
    if len(rows)!=2:raise HTTPException(404,detail="SOURCE_NOT_FOUND_IN_INVESTIGATION")
    a,b=sorted(ids,key=str);item=SourceRelationship(investigation_id=investigation_id,source_a_id=a,source_b_id=b,relationship_type=payload.relationship_type,explanation=payload.explanation.strip(),created_by="INVESTIGATOR",status="REQUIRES_VERIFICATION");db.add(item)
    try:db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,detail="SOURCE_RELATIONSHIP_ALREADY_EXISTS")
    db.refresh(item);return {"success":True,"data":{"id":str(item.id),"source_a_id":str(a),"source_b_id":str(b),"relationship_type":item.relationship_type.value,"explanation":item.explanation,"created_by":item.created_by,"status":item.status}}
