from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from app.correlation.entity_extractor import extract_entities
from app.correlation.normalizers import normalize_date, normalize_location, normalize_text
from app.correlation.rules import RULES, similarity_label, temporal_relation
from app.models.correlation import CorrelationType
from app.correlation.service import CorrelationService
from app.models.web_research import ResultType


def test_location_alias_and_ambiguous_location_normalization():
    assert normalize_location("Bangalore")["normalized_value"] == "bengaluru"
    result = normalize_location("Springfield, District 4")
    assert result["normalized_value"] == "springfield district 4"
    assert result["raw_value"] == "Springfield, District 4"


def test_date_and_text_normalization_preserve_original_values():
    assert normalize_date("31/12/2024") == {"original_value": "31/12/2024", "normalized_date": "2024-12-31"}
    assert normalize_text("  Case #HC-102:   OPEN! ") == "case #hc-102 open"


def test_entity_extraction_is_limited_to_patterns_and_explicit_labels():
    entities = extract_entities("Case ID HC-102 on 2024-04-02. PERSON: Asha Rao; LOCATION: Bengaluru")
    assert {(item["type"], item["normalized_value"]) for item in entities} >= {
        ("CASE_ID", "hc-102"), ("DATE", "2024-04-02"), ("PERSON", "asha rao"), ("LOCATION", "bengaluru")
    }
    assert not any(item["type"] == "PERSON" for item in extract_entities("Asha Rao visited Bengaluru"))
    alias = extract_entities("LOCATION: Bangalore")
    canonical = extract_entities("LOCATION: Bengaluru")
    assert alias[0]["normalized_value"] == canonical[0]["normalized_value"]


def test_temporal_rule_and_similarity_labels_have_documented_semantics():
    assert temporal_relation(date(2024, 4, 1), date(2024, 4, 1)) == ("TEMPORAL_OVERLAP", 0)
    assert temporal_relation(date(2024, 4, 1), date(2024, 4, 12)) == ("TEMPORAL_OVERLAP", 11)
    assert temporal_relation(date(2024, 4, 1), date(2024, 9, 1)) == ("TEMPORAL_PROXIMITY", 153)
    assert temporal_relation(date(2024, 4, 1), date(2026, 4, 1)) is None
    assert similarity_label(0.82) == "HIGH"
    assert similarity_label(0.65) == "MODERATE"
    assert similarity_label(0.3) == "LOW"


def test_rules_are_explicit_and_do_not_define_investigative_verdicts():
    names = {rule.name for rule in RULES if rule.enabled}
    assert {"semantic_similarity", "visual_similarity", "shared_location", "temporal_proximity", "shared_case_type", "entity_overlap", "source_reference", "contextual_relevance"} == names
    forbidden = {"GUILT", "PERPETRATOR", "SAME_PERSON", "CONFIRMED_CONNECTION"}
    assert not forbidden.intersection(kind.value for kind in CorrelationType)


def test_entity_matching_returns_fuzzy_candidates_without_person_identity_claims():
    def entity(kind, value):
        return {"type": kind, "value": value, "normalized_value": normalize_text(value)}
    org_match = CorrelationService._overlaps([entity("ORGANIZATION", "Northstar Logistics")], [entity("ORGANIZATION", "Northstar Logistic")])
    assert org_match[0]["match_strength"] == "FUZZY_CANDIDATE"
    assert org_match[0]["requires_verification"] is True
    person_match = CorrelationService._overlaps([entity("PERSON", "Rahul Kumar")], [entity("PERSON", "Rahul Kumarr")])
    assert person_match == []
    case_id_match = CorrelationService._overlaps([entity("CASE_ID", "HC-102A")], [entity("CASE_ID", "HC-102B")])
    assert case_id_match == []


def test_location_temporal_and_case_type_rules_report_source_values():
    engine = object.__new__(CorrelationService)
    evidence = SimpleNamespace(id=uuid4(), metadata_json={"location": "Bangalore", "case_type": "Missing Person", "date": "31/12/2024"},
        title="Evidence", description="", text_content="")
    case = SimpleNamespace(id=uuid4(), location="Bengaluru", case_type="missing person", case_date=date(2025, 1, 2))
    location = list(engine._attribute_correlations([evidence], [case], "location"))[0]
    temporal = list(engine._attribute_correlations([evidence], [case], "date"))[0]
    case_type = list(engine._attribute_correlations([evidence], [case], "case_type"))[0]
    assert location["correlation_type"] == CorrelationType.GEOGRAPHIC_OVERLAP
    assert location["evidence_basis"]["current_value"]["raw_value"] == "Bangalore"
    assert temporal["correlation_type"] == CorrelationType.TEMPORAL_PROXIMITY
    assert temporal["evidence_basis"]["relative_order"] == "BEFORE"
    assert case_type["correlation_type"] == CorrelationType.SHARED_ATTRIBUTE


def test_source_reference_and_contextual_rules_use_research_record_fields():
    engine = object.__new__(CorrelationService)
    case = SimpleNamespace(id=uuid4(), external_id="HC-102", title="Harbor Warehouse Event")
    result = SimpleNamespace(id=uuid4(), result_type=ResultType.NEWS,
        title="Harbor Warehouse Event case HC-102", snippet="", url="https://example.test/article", source_id=None,
        research_run_id=uuid4(), search_id=uuid4())
    reference = list(engine._source_references([result], [case]))[0]
    assert reference["correlation_type"] == CorrelationType.SOURCE_REFERENCE
    assert reference["evidence_basis"]["method"] == "EXACT_SOURCE_TEXT_REFERENCE"

    evidence = SimpleNamespace(id=uuid4(), title="Harbor warehouse", description="", text_content="warehouse harbor event update")
    context = list(engine._contextual_correlations([evidence], [result]))
    assert context and context[0]["correlation_type"] == CorrelationType.CONTEXTUAL_RELEVANCE
    assert context[0]["score"] is None


def test_explicit_investigation_context_is_traceable_in_entity_basis():
    engine = object.__new__(CorrelationService)
    evidence = SimpleNamespace(id=uuid4(), title="Witness record", description="", text_content="", metadata_json={})
    case = SimpleNamespace(id=uuid4(), title="Historical record", summary="", description="PERSON: Asha Rao", metadata_json={})
    candidate = list(engine._entity_correlations([evidence], [case], [], {"title": "", "description": "PERSON: Asha Rao"}))[0]
    assert candidate["correlation_type"] == CorrelationType.ENTITY_OVERLAP
    assert candidate["evidence_basis"]["matches"][0]["left_source"] == "INVESTIGATION_CONTEXT"
