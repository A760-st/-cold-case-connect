import os
from uuid import UUID
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database.session import Base, get_db
from app.main import app
from app.models.evidence import Evidence, EvidenceType
from app.models.investigation import Investigation
from app.models.timeline import TimelineDatePrecision, TimelineEvent, TimelineEventEvidence, TimelineEventType, TimelineSourceType

engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
TestingSession=sessionmaker(bind=engine,autoflush=False,expire_on_commit=False)

@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def client():
    def override():
        db=TestingSession()
        try:yield db
        finally:db.close()
    app.dependency_overrides[get_db]=override
    with TestClient(app) as test_client:yield test_client
    app.dependency_overrides.clear()

def make_investigation(client,title="Graph test"):
    return UUID(client.post("/api/v1/investigations",json={"title":title,"description":"Graph fixture"}).json()["data"]["id"])

def test_graph_rebuild_imports_only_structured_claims_and_is_idempotent(client):
    investigation_id=make_investigation(client)
    db=TestingSession();inv=db.get(Investigation,investigation_id)
    evidence=Evidence(investigation_id=inv.id,type=EvidenceType.TEXT,title="Witness note",text_content="The unstructured words are not claims.",metadata_json={"claims":[{"claim_type":"LOCATION","subject":"reported event","predicate":"occurred at","object_value":"Bengaluru"},{"claim_type":"DATE","subject":"reported event","predicate":"date","value":"2024-06-12"},{"subject":"incomplete","predicate":"is missing"},"ignored"]})
    db.add(evidence);db.flush()
    event=TimelineEvent(investigation_id=inv.id,title="Reported incident",description="Date and place in the timeline record",event_type=TimelineEventType.INCIDENT,date_start=date(2024,6,12),date_end=date(2024,6,12),date_precision=TimelineDatePrecision.EXACT,date_text="12 June 2024",location="Bengaluru",source_type=TimelineSourceType.EVIDENCE,source_id=evidence.id,importance="HIGH")
    db.add(event);db.flush();db.add(TimelineEventEvidence(timeline_event_id=event.id,evidence_id=evidence.id,relationship_type="SUPPORTING_EVIDENCE"));db.commit();evidence_id=str(evidence.id);event_id=str(event.id);db.close()
    db=TestingSession();inv=db.get(Investigation,investigation_id);evidence=db.get(Evidence,UUID(evidence_id))
    conflicting=TimelineEvent(investigation_id=inv.id,title="Reported incident",description="Another source-backed report",event_type=TimelineEventType.INCIDENT,date_start=date(2024,6,15),date_end=date(2024,6,15),date_precision=TimelineDatePrecision.EXACT,date_text="15 June 2024",location="Mysuru",source_type=TimelineSourceType.EVIDENCE,source_id=evidence.id,importance="HIGH")
    db.add(conflicting);db.flush();db.add(TimelineEventEvidence(timeline_event_id=conflicting.id,evidence_id=evidence.id,relationship_type="SUPPORTING_EVIDENCE"));db.commit();conflicting_id=str(conflicting.id);db.close()

    first=client.post(f"/api/v1/investigations/{investigation_id}/graph/rebuild")
    assert first.status_code==200
    assert first.json()["data"]["claims_created"]==6
    second=client.post(f"/api/v1/investigations/{investigation_id}/graph/rebuild")
    assert second.json()["data"]["claims_created"]==0
    detected=client.post(f"/api/v1/investigations/{investigation_id}/contradictions/detect")
    assert detected.status_code==200
    graph=client.get(f"/api/v1/investigations/{investigation_id}/graph?limit=100")
    assert graph.status_code==200
    data=graph.json()["data"]
    claims=[node for node in data["nodes"] if node["type"]=="CLAIM"]
    assert len(claims)==6
    assert all(node["metadata"]["status"]=="SOURCE_REPORTED" for node in claims)
    assert len([node for node in claims if node["metadata"]["extraction_method"]=="STRUCTURED_EVIDENCE_METADATA"])==2
    assert len([edge for edge in data["edges"] if edge["type"]=="REPORTED_BY" and edge["target"] in {f"timeline_event:{event_id}",f"timeline_event:{conflicting_id}"}])==4
    assert any(node["type"]=="CONTRADICTION" for node in data["nodes"])
    assert any(node["type"]=="RESEARCH_GAP" for node in data["nodes"])
    assert any(edge["type"]=="EXTRACTED_FROM" and edge["target"]==f"evidence:{evidence_id}" for edge in data["edges"])

def test_graph_pagination_neighborhood_and_note_are_investigation_scoped(client):
    investigation_id=make_investigation(client)
    other_id=make_investigation(client,"Other investigation")
    db=TestingSession();inv=db.get(Investigation,investigation_id)
    evidence=Evidence(investigation_id=inv.id,type=EvidenceType.TEXT,title="Scoped evidence",text_content="Report",metadata_json={})
    db.add(evidence);db.commit();evidence_id=str(evidence.id);db.close()

    page=client.get(f"/api/v1/investigations/{investigation_id}/graph?limit=1&edge_limit=20").json()["data"]
    ids={node["id"] for node in page["nodes"]}
    assert all(edge["source"] in ids and edge["target"] in ids for edge in page["edges"])
    neighborhood=client.get(f"/api/v1/investigations/{investigation_id}/graph/neighborhood/EVIDENCE/{evidence_id}?depth=1&max_nodes=10")
    assert neighborhood.status_code==200
    assert f"evidence:{evidence_id}" in {node["id"] for node in neighborhood.json()["data"]["nodes"]}

    note=client.post(f"/api/v1/investigations/{investigation_id}/graph/notes",json={"node_type":"EVIDENCE","node_id":evidence_id,"note":"Review the original attachment."})
    assert note.status_code==201
    assert note.json()["data"]["created_by"]=="INVESTIGATOR"
    wrong_scope=client.post(f"/api/v1/investigations/{other_id}/graph/notes",json={"node_type":"EVIDENCE","node_id":evidence_id,"note":"Must not cross investigations."})
    assert wrong_scope.status_code==404

def test_graph_bookmarks_reject_unknown_nodes(client):
    investigation_id=make_investigation(client)
    unknown="00000000-0000-0000-0000-000000000001"
    response=client.post(f"/api/v1/investigations/{investigation_id}/graph/bookmarks",json={"name":"Unknown node","node_ids":[f"evidence:{unknown}"]})
    assert response.status_code==422
