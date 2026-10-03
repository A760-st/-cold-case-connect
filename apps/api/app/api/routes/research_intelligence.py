from uuid import UUID
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.agents.agent_models import AgentRunRequest
from app.agents.agent_service import AgentService, AgentServiceError
from app.config import settings
from app.database.session import get_db
from app.database.session import SessionLocal
from app.models.geospatial import Contradiction, ContradictionStatus, ContradictionType
from app.models.investigation import Investigation
from app.models.research_intelligence import InvestigationQuestion, InvestigationQuestionStatus, ResearchGap, ResearchGapStatus, ResearchGapType
from app.geospatial.schemas import ContradictionReview
from app.research_intelligence.gap_service import ResearchGapError, ResearchGapService
from app.research_intelligence.question_service import QuestionService, QuestionServiceError
from app.research_intelligence.schemas import GapReview, Priority, QuestionCreate, QuestionUpdate
from app.geospatial.contradiction_detector import ContradictionDetector

router=APIRouter(prefix="/api/v1")

def _raise(exc): raise HTTPException(exc.status_code,detail=exc.code)

@router.post("/investigations/{investigation_id}/contradictions/detect")
def detect_contradictions(investigation_id:UUID,background:BackgroundTasks,db:Session=Depends(get_db)):
    if db.get(Investigation,investigation_id) is None: raise HTTPException(404,detail="INVESTIGATION_NOT_FOUND")
    result=ContradictionDetector(db).detect(investigation_id)
    gaps=ResearchGapService(db).detect(investigation_id)
    result["research_gaps_created"]=gaps["created"]
    return {"success":True,"data":result}

@router.get("/investigations/{investigation_id}/contradictions/summary")
def contradiction_summary(investigation_id:UUID,db:Session=Depends(get_db)):
    if db.get(Investigation,investigation_id) is None: raise HTTPException(404,detail="INVESTIGATION_NOT_FOUND")
    rows=list(db.scalars(select(Contradiction).where(Contradiction.investigation_id==investigation_id)))
    statuses={s.value:sum(x.status==s for x in rows) for s in ContradictionStatus}
    types={t:sum(x.type.value==t for x in rows) for t in ("DATE_CONFLICT","LOCATION_CONFLICT","TIMELINE_CONFLICT","ATTRIBUTE_CONFLICT","SOURCE_CONFLICT")}
    return {"success":True,"data":{"total":len(rows),"statuses":statuses,"types":types,"priorities":{p:sum(x.priority==p for x in rows) for p in ("HIGH","MEDIUM","LOW")}}}

@router.get("/investigations/{investigation_id}/contradictions")
def list_contradictions(investigation_id:UUID,type:ContradictionType|None=None,status:ContradictionStatus|None=None,priority:Priority|None=None,subject:str|None=Query(default=None,max_length=200),limit:int=Query(200,ge=1,le=500),offset:int=Query(0,ge=0),db:Session=Depends(get_db)):
    if db.get(Investigation,investigation_id) is None: raise HTTPException(404,detail="INVESTIGATION_NOT_FOUND")
    q=select(Contradiction).where(Contradiction.investigation_id==investigation_id)
    if type:q=q.where(Contradiction.type==type)
    if status:q=q.where(Contradiction.status==status)
    if priority:q=q.where(Contradiction.priority==priority)
    rows=db.scalars(q.order_by(Contradiction.created_at.desc()).limit(limit).offset(offset)).all()
    items=[ContradictionDetector(db).serialize(x) for x in rows]
    if subject:items=[x for x in items if subject.casefold() in f"{x['description']} {x.get('subject_type') or ''}".casefold()]
    return {"success":True,"data":items}

@router.get("/contradictions/{contradiction_id}")
def get_contradiction(contradiction_id:UUID,db:Session=Depends(get_db)):
    item=db.get(Contradiction,contradiction_id)
    if item is None:raise HTTPException(404,detail="CONTRADICTION_NOT_FOUND")
    return {"success":True,"data":ContradictionDetector(db).serialize(item)}

@router.patch("/contradictions/{contradiction_id}")
def review_contradiction(contradiction_id:UUID,payload:ContradictionReview,db:Session=Depends(get_db)):
    item=db.get(Contradiction,contradiction_id)
    if item is None:raise HTTPException(404,detail="CONTRADICTION_NOT_FOUND")
    if payload.status is not None:item.status=payload.status
    if payload.priority is not None:item.priority=payload.priority
    if "investigator_note" in payload.model_fields_set:item.investigator_note=payload.investigator_note
    db.commit();db.refresh(item)
    return {"success":True,"data":ContradictionDetector(db).serialize(item)}

@router.post("/investigations/{investigation_id}/gaps/detect")
def detect_gaps(investigation_id:UUID,db:Session=Depends(get_db)):
    try:
        ContradictionDetector(db).detect(investigation_id)
        return {"success":True,"data":ResearchGapService(db).detect(investigation_id)}
    except ResearchGapError as exc:_raise(exc)

@router.get("/investigations/{investigation_id}/gaps/summary")
def gap_summary(investigation_id:UUID,db:Session=Depends(get_db)):
    if db.get(Investigation,investigation_id) is None:raise HTTPException(404,detail="INVESTIGATION_NOT_FOUND")
    return {"success":True,"data":ResearchGapService(db).summary(investigation_id)}

@router.get("/investigations/{investigation_id}/gaps")
def list_gaps(investigation_id:UUID,type:ResearchGapType|None=None,status:ResearchGapStatus|None=None,priority:Priority|None=None,limit:int=Query(200,ge=1,le=500),offset:int=Query(0,ge=0),db:Session=Depends(get_db)):
    try:return {"success":True,"data":ResearchGapService(db).list(investigation_id,type,status,priority,limit,offset)}
    except ResearchGapError as exc:_raise(exc)

@router.get("/gaps/{gap_id}")
def get_gap(gap_id:UUID,db:Session=Depends(get_db)):
    item=db.get(ResearchGap,gap_id)
    if item is None:raise HTTPException(404,detail="RESEARCH_GAP_NOT_FOUND")
    return {"success":True,"data":ResearchGapService(db).serialize(item)}

@router.patch("/gaps/{gap_id}")
def patch_gap(gap_id:UUID,payload:GapReview,db:Session=Depends(get_db)):
    item=db.get(ResearchGap,gap_id)
    if item is None:raise HTTPException(404,detail="RESEARCH_GAP_NOT_FOUND")
    changes=payload.model_dump(exclude_unset=True)
    for field,value in changes.items():
        if field in {"status","priority"} and value is None:continue
        setattr(item,field,value)
    db.commit();db.refresh(item)
    return {"success":True,"data":ResearchGapService(db).serialize(item)}

def _start_agent(db,investigation_id,objective):
    request=AgentRunRequest(objective=objective[:1000],max_iterations=min(2,settings.agent_max_iterations),max_serpapi_queries=min(2,settings.agent_max_serpapi_queries))
    result=AgentService(db).start(investigation_id,request)
    return result

def _execute_intelligence_research(agent_run_id,record_type,record_id):
    try:
        AgentService.background_execute(agent_run_id)
    finally:
        db=SessionLocal()
        try:
            model=ResearchGap if record_type=="gap" else InvestigationQuestion
            item=db.get(model,UUID(record_id))
            if item is not None and item.status.value=="RESEARCHING":
                # Search results alone never mark a gap addressed or a question answered.
                item.status=ResearchGapStatus.OPEN if record_type=="gap" else InvestigationQuestionStatus.OPEN
                db.commit()
        finally:db.close()

@router.post("/gaps/{gap_id}/research",status_code=202)
def research_gap(gap_id:UUID,background:BackgroundTasks,db:Session=Depends(get_db)):
    item=db.get(ResearchGap,gap_id)
    if item is None:raise HTTPException(404,detail="RESEARCH_GAP_NOT_FOUND")
    if item.status==ResearchGapStatus.DISMISSED:raise HTTPException(409,detail="DISMISSED_GAP_CANNOT_BE_RESEARCHED")
    if item.status==ResearchGapStatus.RESEARCHING:raise HTTPException(409,detail="GAP_RESEARCH_ALREADY_ACTIVE")
    try:run=_start_agent(db,item.investigation_id,f"Research gap: {item.title}. {item.description} Documented search terms: {'; '.join(a.get('query_template','') for a in item.suggested_research_actions if a.get('query_template'))}")
    except AgentServiceError as exc:raise HTTPException(exc.status_code,detail=exc.code)
    item.status=ResearchGapStatus.RESEARCHING;item.last_agent_run_id=UUID(run["id"]);db.commit()
    background.add_task(_execute_intelligence_research,run["id"],"gap",str(item.id))
    return {"success":True,"data":{"gap_id":str(item.id),"agent_run_id":run["id"],"status":"QUEUED","message":"A bounded research run was queued through the existing investigation agent."}}

@router.post("/investigations/{investigation_id}/questions",status_code=201)
def create_question(investigation_id:UUID,payload:QuestionCreate,db:Session=Depends(get_db)):
    try:return {"success":True,"data":QuestionService(db).create(investigation_id,payload)}
    except QuestionServiceError as exc:_raise(exc)

@router.get("/investigations/{investigation_id}/questions")
def list_questions(investigation_id:UUID,status:InvestigationQuestionStatus|None=None,priority:Priority|None=None,limit:int=Query(200,ge=1,le=500),offset:int=Query(0,ge=0),db:Session=Depends(get_db)):
    try:return {"success":True,"data":QuestionService(db).list(investigation_id,status,priority,limit,offset)}
    except QuestionServiceError as exc:_raise(exc)

@router.patch("/questions/{question_id}")
def patch_question(question_id:UUID,payload:QuestionUpdate,db:Session=Depends(get_db)):
    try:return {"success":True,"data":QuestionService(db).update(question_id,payload)}
    except QuestionServiceError as exc:_raise(exc)

@router.post("/questions/{question_id}/research",status_code=202)
def research_question(question_id:UUID,background:BackgroundTasks,db:Session=Depends(get_db)):
    service=QuestionService(db)
    try:item,context=service.research_context(question_id)
    except QuestionServiceError as exc:_raise(exc)
    if item.status==InvestigationQuestionStatus.DISMISSED:raise HTTPException(409,detail="DISMISSED_QUESTION_CANNOT_BE_RESEARCHED")
    if item.status==InvestigationQuestionStatus.RESEARCHING:raise HTTPException(409,detail="QUESTION_RESEARCH_ALREADY_ACTIVE")
    try:run=_start_agent(db,item.investigation_id,f"Investigative question: {context}")
    except AgentServiceError as exc:raise HTTPException(exc.status_code,detail=exc.code)
    item.status=InvestigationQuestionStatus.RESEARCHING;item.last_agent_run_id=UUID(run["id"]);db.commit()
    background.add_task(_execute_intelligence_research,run["id"],"question",str(item.id))
    return {"success":True,"data":{"question_id":str(item.id),"agent_run_id":run["id"],"status":"QUEUED","message":"A bounded research run was queued through the existing investigation agent."}}
