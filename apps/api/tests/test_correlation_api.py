import os
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database.session import Base, get_db
from app.main import app
from app.models.historical_case import HistoricalCase
from app.models.agent import AgentAction, AgentActionStatus, AgentActionType, AgentRun, AgentRunStatus

engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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


def _investigation(client, title):
    return client.post("/api/v1/investigations", json={"title": title}).json()["data"]["id"]


def test_manual_correlation_review_filter_detail_and_delete(client):
    investigation_id = _investigation(client, "Case One")
    evidence = client.post(f"/api/v1/investigations/{investigation_id}/evidence", json={"title": "Statement", "text_content": "PERSON: Asha Rao", "description": "Witness statement"}).json()["data"]
    session = TestingSession()
    case = HistoricalCase(fingerprint="a" * 64, title="Older case", text_content="Historical summary")
    session.add(case); session.commit(); case_id = str(case.id); session.close()

    created = client.post(f"/api/v1/investigations/{investigation_id}/correlations/manual", json={
        "source_type": "EVIDENCE", "source_id": evidence["id"], "target_type": "HISTORICAL_CASE", "target_id": case_id,
        "correlation_type": "POTENTIAL_CONNECTION", "note": "Review these records together.",
    })
    assert created.status_code == 201
    record = created.json()["data"]
    assert record["created_by"] == "INVESTIGATOR"
    assert record["score"] is None
    assert record["evidence_basis"]["method"] == "INVESTIGATOR_ADDED"
    duplicate = client.post(f"/api/v1/investigations/{investigation_id}/correlations/manual", json={
        "source_type": "HISTORICAL_CASE", "source_id": case_id, "target_type": "EVIDENCE", "target_id": evidence["id"],
        "correlation_type": "POTENTIAL_CONNECTION", "note": "Second investigator note.",
    }).json()["data"]
    assert duplicate["id"] == record["id"]
    assert client.get(f"/api/v1/investigations/{investigation_id}/correlations?reviewed=false").json()["data"]["total"] == 1

    reviewed = client.patch(f"/api/v1/correlations/{record['id']}/review", json={"review_status": "RELEVANT", "note": "Reviewed"})
    assert reviewed.status_code == 200
    assert reviewed.json()["data"]["review"]["review_status"] == "RELEVANT"
    assert client.get(f"/api/v1/investigations/{investigation_id}/correlations?review_status=RELEVANT").json()["data"]["total"] == 1
    assert client.get(f"/api/v1/investigations/{investigation_id}/correlations?reviewed=true").json()["data"]["total"] == 1
    assert client.get(f"/api/v1/investigations/{investigation_id}/correlations?reviewed=false").json()["data"]["total"] == 0
    assert client.get(f"/api/v1/correlations/{record['id']}").json()["data"]["review_history"][0]["note"] == "Reviewed"
    assert client.delete(f"/api/v1/correlations/{record['id']}").status_code == 204
    assert client.get(f"/api/v1/correlations/{record['id']}").status_code == 404


def test_investigation_scope_is_enforced_for_manual_relationships(client):
    investigation_a = _investigation(client, "Case A")
    investigation_b = _investigation(client, "Case B")
    evidence = client.post(f"/api/v1/investigations/{investigation_a}/evidence", json={"title": "Private evidence", "text_content": "Details"}).json()["data"]
    session = TestingSession()
    case = HistoricalCase(fingerprint="b" * 64, title="Historical", text_content="Summary")
    session.add(case); session.commit(); case_id = str(case.id); session.close()
    response = client.post(f"/api/v1/investigations/{investigation_b}/correlations/manual", json={
        "source_type": "EVIDENCE", "source_id": evidence["id"], "target_type": "HISTORICAL_CASE", "target_id": case_id,
        "correlation_type": "POTENTIAL_CONNECTION", "note": "Investigate relationship",
    })
    assert response.status_code == 404
    assert client.get(f"/api/v1/investigations/{investigation_b}/correlations").json()["data"]["items"] == []


def test_correlation_run_on_missing_investigation_returns_not_found(client):
    response = client.post("/api/v1/investigations/00000000-0000-0000-0000-000000000001/correlations/run", json={"scope": "ALL"})
    assert response.status_code == 404


def test_agent_semantic_match_is_persisted_and_deduplicated(client):
    investigation_id = _investigation(client, "Case with historical retrieval")
    evidence = client.post(f"/api/v1/investigations/{investigation_id}/evidence", json={"title": "Witness statement", "text_content": "Warehouse incident details"}).json()["data"]
    session = TestingSession()
    case = HistoricalCase(fingerprint="c" * 64, title="Historic warehouse incident", text_content="Historical detail")
    session.add(case); session.flush()
    run = AgentRun(investigation_id=investigation_id, objective="Find related cases", status=AgentRunStatus.COMPLETED,
        max_iterations=2, max_actions=5, max_serpapi_queries=2, actions_completed=1, metadata_json={})
    session.add(run); session.flush()
    action = AgentAction(investigation_id=investigation_id, agent_run_id=run.id, iteration=1, sequence_number=1,
        action_type=AgentActionType.SEARCH_HISTORICAL_TEXT, status=AgentActionStatus.COMPLETED,
        input_payload={"evidence_ids": [evidence["id"]]}, output_summary={"matches": [{"historical_case_id": str(case.id), "similarity_score": 0.84}]}, reason="SBERT retrieval")
    session.add(action); session.commit(); session.close()

    first = client.post(f"/api/v1/investigations/{investigation_id}/correlations/run", json={"scope": "HISTORICAL"}).json()["data"]
    assert first["created"] >= 1
    listing = client.get(f"/api/v1/investigations/{investigation_id}/correlations?correlation_type=SEMANTIC_SIMILARITY&minimum_score=0.8").json()["data"]
    semantic = next(row for row in listing["items"] if row["correlation_type"] == "SEMANTIC_SIMILARITY")
    assert semantic["score"] == 0.84
    assert semantic["confidence_label"] == "HIGH"
    assert semantic["evidence_basis"]["method"] == "SBERT"
    assert semantic["evidence_basis"]["evidence_id"] == evidence["id"]
    second = client.post(f"/api/v1/investigations/{investigation_id}/correlations/run", json={"scope": "HISTORICAL"}).json()["data"]
    assert second["created"] == 0
    assert client.get(f"/api/v1/investigations/{investigation_id}/correlations").json()["data"]["total"] == listing["total"]
