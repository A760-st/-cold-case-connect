import os
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
import pytest
import io
from PIL import Image
from fastapi.testclient import TestClient
from app.database.session import get_db
from app.main import app

@pytest.fixture
def client(monkeypatch):
    def no_db():
        yield None
    app.dependency_overrides[get_db]=no_db
    with TestClient(app) as value:
        yield value
    app.dependency_overrides.clear()

def test_historical_search_response_envelope(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.historical.HistoricalSearchService.search",lambda self,payload:{"results":[],"query_source":[{"type":"investigator_query"}],"model":"test","index_status":"READY"})
    response=client.post("/api/v1/historical/search",json={"query":"A witness saw a vehicle"})
    assert response.status_code==200
    assert response.json()["success"] is True
    assert response.json()["data"]["results"]==[]

def test_historical_search_validates_input(client):
    response=client.post("/api/v1/historical/search",json={"query":"  ","top_k":100})
    assert response.status_code==422
    assert response.json()["error"]["code"]=="VALIDATION_ERROR"

def test_image_index_status_route_precedes_case_detail_route(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.historical.HistoricalIndexService.status", lambda self: {"status":"NOT_INITIALIZED", "historical_case_count":0,"vector_index_count":0,"embedding_model":"sbert"})
    monkeypatch.setattr("app.api.routes.historical.HistoricalImageIndexService.status", lambda self: {"status":"NO_CORPUS", "historical_image_count":0,"vector_index_count":0,"embedding_model":"clip"})
    response=client.get("/api/v1/historical/index-status")
    assert response.status_code==200
    assert response.json()["data"]["historical_image_index"]["status"]=="NO_CORPUS"

def test_multipart_image_search_accepts_supported_mime_and_rejects_mismatch(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.historical.HistoricalImageSearchService.search_bytes", lambda self, content, top_k, trace: {"results":[],"query_source":trace,"index_status":"NO_CORPUS"})
    buffer=io.BytesIO()
    Image.new("RGB",(8,8)).save(buffer,format="PNG")
    response=client.post("/api/v1/historical/image-search",files={"image":("evidence.png",buffer.getvalue(),"image/png")},data={"top_k":"5"})
    assert response.status_code==200 and response.json()["data"]["results"]==[]
    response=client.post("/api/v1/historical/image-search",files={"image":("evidence.png",buffer.getvalue(),"image/jpeg")})
    assert response.status_code==422
