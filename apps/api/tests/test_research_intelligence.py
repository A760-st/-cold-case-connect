import os
from uuid import UUID
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database.session import Base, get_db
from app.main import app
from app.models.evidence import Evidence, EvidenceType
from app.models.investigation import Investigation
from app.models.timeline import TimelineDatePrecision, TimelineEvent, TimelineEventType, TimelineSourceType

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

def create_investigation(client):
    return UUID(client.post("/api/v1/investigations",json={"title":"Research coverage test","description":"Fixture investigation"}).json()["data"]["id"])

def test_contradictions_are_deduplicated_reviewable_and_linked_to_gaps(client):
    investigation_id=create_investigation(client)
    db=TestingSession();inv=db.get(Investigation,investigation_id)
    evidence=Evidence(investigation_id=inv.id,type=EvidenceType.TEXT,title="Incident report",text_content="Original source material",metadata_json={})
    db.add(evidence);db.flush()
    from datetime import date
    from app.models.timeline import TimelineEventSource,TimelineSourceType
    event_a=TimelineEvent(investigation_id=inv.id,title="Reported incident",description="Incident account",event_type=TimelineEventType.INCIDENT,date_start=date(2024,6,12),date_end=date(2024,6,12),date_precision=TimelineDatePrecision.EXACT,date_text="12 June 2024, 10:00 AM",location="Bengaluru",source_type=TimelineSourceType.EVIDENCE,source_id=evidence.id,importance="HIGH")
    event_b=TimelineEvent(investigation_id=inv.id,title="Reported incident",description="Incident account",event_type=TimelineEventType.INCIDENT,date_start=date(2024,6,15),date_end=date(2024,6,15),date_precision=TimelineDatePrecision.EXACT,date_text="15 June 2024, 4:00 PM",location="Mysuru",source_type=TimelineSourceType.EVIDENCE,source_id=evidence.id,importance="HIGH")
    db.add_all([event_a,event_b]);db.commit();db.close()

    first=client.post(f"/api/v1/investigations/{investigation_id}/contradictions/detect").json()["data"]
    assert first["created"]>=4
    assert {x["type"] for x in first["items"]}>={"DATE_CONFLICT","TIME_CONFLICT","LOCATION_CONFLICT","SOURCE_CONFLICT"}
    assert all(x["source_a"].get("evidence_ids") is not None for x in first["items"] if x["source_a_type"]=="TIMELINE_EVENT")
    assert first["research_gaps_created"]>=1
    second=client.post(f"/api/v1/investigations/{investigation_id}/contradictions/detect").json()["data"]
    assert second["created"]==0
    assert second["research_gaps_created"]==0
    gaps=client.get(f"/api/v1/investigations/{investigation_id}/gaps").json()["data"]
    assert any(x["gap_type"]=="UNRESOLVED_TIMELINE" for x in gaps)

    contradiction=next(x for x in first["items"] if x["type"]=="DATE_CONFLICT")
    reviewed=client.patch(f"/api/v1/contradictions/{contradiction['id']}",json={"status":"UNDER_REVIEW","investigator_note":"Compare source originals"}).json()["data"]
    assert reviewed["status"]=="UNDER_REVIEW"
    assert reviewed["investigator_note"]=="Compare source originals"

def test_gap_detection_is_deduplicated_and_questions_can_link_to_gaps(client):
    investigation_id=create_investigation(client)
    db=TestingSession();inv=db.get(Investigation,investigation_id)
    evidence=Evidence(investigation_id=inv.id,type=EvidenceType.TEXT,title="Undated incident note",text_content="Source text",metadata_json={})
    db.add(evidence);db.flush()
    event=TimelineEvent(investigation_id=inv.id,title="Incident with unknown location",description="",event_type=TimelineEventType.INCIDENT,date_start=None,date_end=None,date_precision=TimelineDatePrecision.UNKNOWN,date_text="",location=None,source_type=TimelineSourceType.EVIDENCE,source_id=evidence.id,importance="HIGH")
    db.add(event);db.commit();db.close()
    route=f"/api/v1/investigations/{investigation_id}/gaps/detect"
    detected=client.post(route).json()["data"]
    assert {x["gap_type"] for x in detected["items"]}>={"MISSING_DATE","MISSING_LOCATION"}
    assert client.post(route).json()["data"]["created"]==0
    gap=next(x for x in detected["items"] if x["gap_type"]=="MISSING_LOCATION")
    created=client.post(f"/api/v1/investigations/{investigation_id}/questions",json={"question":"Where is this event reported?","related_evidence_ids":[str(evidence.id)],"related_timeline_event_ids":[str(event.id)],"related_gap_ids":[gap["id"]]}).json()["data"]
    assert created["related_gap_ids"]==[gap["id"]]
    updated=client.patch(f"/api/v1/questions/{created['id']}",json={"status":"PARTIALLY_ADDRESSED"}).json()["data"]
    assert updated["status"]=="PARTIALLY_ADDRESSED"
    assert client.post(route).json()["data"]["created"]==1  # one deduplicated unanswered-question gap

def test_gap_detection_reads_only_explicit_structured_entity_metadata(client):
    investigation_id=create_investigation(client)
    db=TestingSession();inv=db.get(Investigation,investigation_id)
    evidence=Evidence(investigation_id=inv.id,type=EvidenceType.TEXT,title="Structured entity record",text_content="No entity should be inferred from this prose.",metadata_json={"entities":{"PERSON":["A. Person"],"LOCATION":"Bengaluru"}})
    db.add(evidence);db.commit();db.close()
    detected=client.post(f"/api/v1/investigations/{investigation_id}/gaps/detect").json()["data"]
    entity_gaps=[item for item in detected["items"] if item["gap_type"]=="UNDER_RESEARCHED_ENTITY"]
    assert {"A. Person","Bengaluru"} <= {item["description"].split("‘")[1].split("’")[0] for item in entity_gaps}
