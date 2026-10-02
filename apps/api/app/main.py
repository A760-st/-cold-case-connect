import logging
from uuid import UUID
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import httpx

from app.config import settings
from app.services.web_research import WebResearchError, serpapi_client
from app.database.session import SessionLocal, get_db
from app.schemas.investigation import InvestigationCreate, InvestigationUpdate, InvestigationRead
from app.services.investigations import InvestigationService
from app.api.routes.evidence import router as evidence_router
from app.services.evidence import EvidenceError
from app.api.routes.historical import router as historical_router
from app.services.historical_search import HistoricalSearchError
from app.services.historical_index import HistoricalIndexService
from app.services.historical_image_index import HistoricalImageIndexService
from app.services.historical_image_search import HistoricalImageSearchError
from app.api.routes.research import router as research_router
from app.api.routes.agent import router as agent_router
from app.agents.agent_service import AgentServiceError
from app.api.routes.correlations import router as correlations_router
from app.api.routes.timeline import router as timeline_router
from app.api.routes.geospatial import router as geospatial_router
from app.correlation.service import CorrelationError
from app.correlation.rules import RULES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("coldsync.api")
app = FastAPI(title="ColdSync AI API", version="0.1.0", description="Investigative research and evidence correlation API")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["*"])
engine = create_engine(settings.database_url, pool_pre_ping=True)
api = APIRouter(prefix="/api/v1")


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled API error", exc_info=exc)
    return JSONResponse(status_code=500, content={"success": False, "error": {"code": "INTERNAL_ERROR", "message": "An unexpected server error occurred."}})


@app.get("/api/v1/health")
def api_health() -> dict:
    database = "healthy"
    text_index = {"status": "NOT_INITIALIZED", "historical_case_count": 0, "vector_index_count": 0, "embedding_model": settings.sbert_model_name}
    image_index = {"status": "NOT_INITIALIZED", "historical_image_count": 0, "vector_index_count": 0, "embedding_model": settings.clip_model_name}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        with SessionLocal() as db:
            text_index = HistoricalIndexService(db).status()
            image_index = HistoricalImageIndexService(db).status()
    except Exception:
        logger.exception("Health check dependency failed")
        database = "unavailable"
    degraded_index_states = {"BUILDING", "FAILED", "INDEX_OUT_OF_SYNC"}
    status = "healthy" if database == "healthy" and text_index["status"] not in degraded_index_states and image_index["status"] not in degraded_index_states else "degraded"
    serp_status = serpapi_client.last_status
    if serp_status == "IDLE":
        serp_status = "AVAILABLE"
    geospatial = {"status": "UNKNOWN", "locations": None, "mapped_locations": None, "heatmap_records": None, "contradictions": None, "open_contradictions": None}
    try:
        from sqlalchemy import func, select
        from app.models.geospatial import Location, Contradiction, ContradictionStatus
        with SessionLocal() as db:
            geospatial.update({"status": "ENABLED" if settings.geocoding_enabled else "DISABLED", "locations": db.scalar(select(func.count(Location.id))) or 0, "mapped_locations": db.scalar(select(func.count(Location.id)).where(Location.latitude.is_not(None), Location.longitude.is_not(None))) or 0, "heatmap_records": db.scalar(select(func.count(Location.id)).where(Location.latitude.is_not(None), Location.longitude.is_not(None))) or 0, "contradictions": db.scalar(select(func.count(Contradiction.id))) or 0, "open_contradictions": db.scalar(select(func.count(Contradiction.id)).where(Contradiction.status.in_([ContradictionStatus.OPEN, ContradictionStatus.REQUIRES_VERIFICATION]))) or 0})
    except SQLAlchemyError:
        logger.exception("Geospatial health metrics unavailable")
    return {"success": True, "data": {"status": status, "service": "coldsync-api", "database": database, "historical_case_count": text_index["historical_case_count"], "vector_index_status": text_index["status"], "vector_index_count": text_index["vector_index_count"], "embedding_model": text_index["embedding_model"], "historical_text_index": {"status": text_index["status"], "count": text_index["vector_index_count"]}, "historical_image_index": {"status": image_index["status"], "count": image_index["vector_index_count"]}, "clip_model": settings.clip_model_name, "serpapi": {"configured": bool(settings.serpapi_api_key), "status": serp_status, "mock_mode": settings.serpapi_mock_mode}, "agent": {"available": True, "planner": "deterministic", "llm_available": False, "max_iterations": settings.agent_max_iterations, "max_serpapi_queries": settings.agent_max_serpapi_queries}, "correlation_engine": {"available": True, "rules_enabled": len(RULES), "semantic_engine": text_index["status"] == "READY", "visual_engine": image_index["status"] == "READY"}, "geospatial": geospatial}}


@api.post("/investigations", status_code=201)
def create_investigation(payload: InvestigationCreate, db=Depends(get_db)):
    result = InvestigationService(db).create(payload)
    return {"success": True, "data": InvestigationRead.model_validate(result).model_dump(mode="json")}


@api.get("/investigations")
def list_investigations(db=Depends(get_db)):
    results = InvestigationService(db).list()
    return {"success": True, "data": [InvestigationRead.model_validate(item).model_dump(mode="json") for item in results]}


@api.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: UUID, db=Depends(get_db)):
    item = InvestigationService(db).get(investigation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="INVESTIGATION_NOT_FOUND")
    return {"success": True, "data": InvestigationRead.model_validate(item).model_dump(mode="json")}


@api.patch("/investigations/{investigation_id}")
def update_investigation(investigation_id: UUID, payload: InvestigationUpdate, db=Depends(get_db)):
    item = InvestigationService(db).update(investigation_id, payload)
    if item is None:
        raise HTTPException(status_code=404, detail="INVESTIGATION_NOT_FOUND")
    return {"success": True, "data": InvestigationRead.model_validate(item).model_dump(mode="json")}


@api.delete("/investigations/{investigation_id}", status_code=204)
def delete_investigation(investigation_id: UUID, db=Depends(get_db)):
    if not InvestigationService(db).delete(investigation_id):
        raise HTTPException(status_code=404, detail="INVESTIGATION_NOT_FOUND")


app.include_router(api)
app.include_router(evidence_router)
app.include_router(historical_router)
app.include_router(research_router)
app.include_router(agent_router)
app.include_router(correlations_router)
app.include_router(timeline_router)
app.include_router(geospatial_router)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    code = exc.detail if isinstance(exc.detail, str) else "REQUEST_ERROR"
    messages = {"INVESTIGATION_NOT_FOUND": "Investigation was not found.", "EVIDENCE_NOT_FOUND": "Evidence was not found.", "HISTORICAL_CASE_NOT_FOUND": "Historical case was not found.", "HISTORICAL_IMAGE_NOT_FOUND": "Historical image is unavailable.", "FILE_TOO_LARGE": "The uploaded file exceeds the configured size limit.", "INVALID_IMAGE_TYPE": "Upload a JPEG, PNG, or WebP image."}
    message = messages.get(code, "The request could not be completed.")
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": code, "message": message}})


@app.exception_handler(EvidenceError)
async def evidence_error_handler(request: Request, exc: EvidenceError):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(HistoricalSearchError)
async def historical_search_error_handler(request: Request, exc: HistoricalSearchError):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(HistoricalImageSearchError)
async def historical_image_search_error_handler(request: Request, exc: HistoricalImageSearchError):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(AgentServiceError)
async def agent_service_error_handler(request: Request, exc: AgentServiceError):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(CorrelationError)
async def correlation_error_handler(request: Request, exc: CorrelationError):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(WebResearchError)
async def web_research_error_handler(request: Request, exc: WebResearchError):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": exc.code, "message": exc.message}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"success": False, "error": {"code": "VALIDATION_ERROR", "message": "The request contains invalid or missing fields."}})


@app.exception_handler(404)
async def route_not_found_handler(request: Request, exc):
    return JSONResponse(status_code=404, content={"success": False, "error": {"code": "NOT_FOUND", "message": "The requested resource was not found."}})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "coldsync-api"}


@app.get("/api/v1/health/dependencies")
def dependency_health() -> dict:
    dependencies = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        dependencies["postgres"] = "ONLINE"
    except SQLAlchemyError:
        dependencies["postgres"] = "OFFLINE"
    try:
        response = httpx.get(f"http://{settings.chroma_host}:{settings.chroma_port}/api/v2/heartbeat", timeout=2)
        dependencies["chromadb"] = "ONLINE" if response.is_success else "DEGRADED"
    except httpx.HTTPError:
        dependencies["chromadb"] = "OFFLINE"
    return {"service": "backend", "status": "ONLINE", "dependencies": dependencies}
