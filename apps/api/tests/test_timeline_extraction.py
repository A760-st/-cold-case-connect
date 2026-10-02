from uuid import uuid4
from app.models.timeline import TimelineEventType, TimelineSourceType
from app.timeline.service import TimelineService

def test_evidence_extracts_only_an_explicitly_dated_sentence_with_provenance():
    evidence_id=uuid4(); service=TimelineService(None)
    events=service._extract_text("On 12 March 2024, the report was submitted. A person may have visited later.","Report",TimelineEventType.EVIDENCE_COLLECTED,TimelineSourceType.EVIDENCE,evidence_id,evidence_id)
    assert len(events)==1
    event=events[0]
    assert event["date_text"]=="12 March 2024" and event["date_precision"]=="EXACT"
    assert event["source_type"]==TimelineSourceType.EVIDENCE and event["source_id"]==evidence_id
    assert "report was submitted" in event["description"]
    assert "visited later" not in event["description"]

def test_undated_evidence_creates_no_candidate_event():
    service=TimelineService(None)
    assert service._extract_text("The report was submitted recently.","Report",TimelineEventType.EVIDENCE_COLLECTED,TimelineSourceType.EVIDENCE,uuid4())==[]

def test_date_variance_matching_is_not_causal():
    # Variance presentation uses same-title source records only; timeline model has no causal relation vocabulary.
    assert not {"CAUSED","LED_TO","RESPONSIBLE_FOR"}.intersection({x.value for x in TimelineEventType})
