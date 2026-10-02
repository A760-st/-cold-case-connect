import os
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.session import Base, get_db
from app.main import app

engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread":False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def client():
    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

def test_create_list_get_update_delete(client):
    created = client.post("/api/v1/investigations", json={"title":"Example Investigation", "description":"Case context"})
    assert created.status_code == 201
    item = created.json()["data"]
    assert item["title"] == "Example Investigation"
    assert client.get("/api/v1/investigations").json()["data"][0]["id"] == item["id"]
    assert client.get(f"/api/v1/investigations/{item['id']}").json()["data"]["description"] == "Case context"
    updated = client.patch(f"/api/v1/investigations/{item['id']}", json={"title":"Updated", "status":"COMPLETED"})
    assert updated.status_code == 200
    assert updated.json()["data"]["title"] == "Updated"
    assert updated.json()["data"]["status"] == "COMPLETED"
    assert client.delete(f"/api/v1/investigations/{item['id']}").status_code == 204
    assert client.get(f"/api/v1/investigations/{item['id']}").status_code == 404

def test_invalid_and_missing_ids(client):
    assert client.get("/api/v1/investigations/not-a-uuid").status_code == 422
    assert client.get("/api/v1/investigations/00000000-0000-0000-0000-000000000001").json()["error"]["code"] == "INVESTIGATION_NOT_FOUND"

def test_validation_and_health(client):
    assert client.post("/api/v1/investigations", json={"title":"  "}).status_code == 422
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/v1/health").json()["data"]["service"] == "coldsync-api"
