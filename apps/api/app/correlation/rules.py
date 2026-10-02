from dataclasses import dataclass


@dataclass(frozen=True)
class CorrelationRule:
    name: str
    enabled: bool = True


RULES = tuple(CorrelationRule(name) for name in (
    "semantic_similarity", "visual_similarity", "shared_location", "temporal_proximity",
    "shared_case_type", "entity_overlap", "source_reference", "contextual_relevance",
))


def similarity_label(score: float) -> str:
    if score >= 0.80:
        return "HIGH"
    if score >= 0.60:
        return "MODERATE"
    return "LOW"


def temporal_relation(left, right) -> tuple[str, int] | None:
    """Classifies exact, same-month/year, or <=30-day temporal proximity."""
    if left is None or right is None:
        return None
    delta = abs((left - right).days)
    if delta == 0:
        return ("TEMPORAL_OVERLAP", 0)
    if left.year == right.year and left.month == right.month:
        return ("TEMPORAL_OVERLAP", delta)
    if left.year == right.year or delta <= 30:
        return ("TEMPORAL_PROXIMITY", delta)
    return None
