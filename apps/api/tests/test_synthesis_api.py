import os
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("GEMINI_MOCK_MODE", "true")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.session import Base, get_db
from app.main import app

engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def reset_db(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "gemini_mock_mode", True)
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


def test_synthesis_generation_and_review_flow(client):
    investigation = client.post("/api/v1/investigations", json={"title": "Synthesis case", "description": "Example investigation"})
    investigation_id = investigation.json()["data"]["id"]

    generated = client.post(f"/api/v1/investigations/{investigation_id}/synthesis")
    assert generated.status_code == 200, generated.text
    payload = generated.json()["data"]
    assert payload["investigation_id"] == investigation_id
    assert payload["version"] == 1
    assert payload["status"] == "COMPLETED"
    assert payload["synthesis_json"]["executive_summary"]
    assert payload["context_hash"]

    versions = client.get(f"/api/v1/investigations/{investigation_id}/syntheses")
    assert versions.status_code == 200
    assert len(versions.json()["data"]) == 1

    current = client.get(f"/api/v1/investigations/{investigation_id}/synthesis/current")
    assert current.status_code == 200
    assert current.json()["data"]["id"] == payload["id"]

    review = client.post(f"/api/v1/syntheses/{payload['id']}/reviews", json={
        "section": "key_facts",
        "item_reference": "C-001",
        "review_status": "NEEDS_VERIFICATION",
        "note": "Check source confirmation."
    })
    assert review.status_code == 200
    assert review.json()["data"]["review_status"] == "NEEDS_VERIFICATION"

    reviews = client.get(f"/api/v1/syntheses/{payload['id']}/reviews")
    assert reviews.status_code == 200
    assert len(reviews.json()["data"]) == 1
