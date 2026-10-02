import re
from app.correlation.normalizers import normalize_text, normalize_location

CASE_ID = re.compile(r"\b(?:case|incident|file|ref(?:erence)?)\s*(?:#|no\.?|id)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9/_-]{2,})\b", re.I)
DATE_PATTERNS = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
    re.compile(r"\b[A-Z][a-z]+\s+\d{1,2},?\s+\d{4}\b"),
)
MARKED_ENTITY = re.compile(r"\b(PERSON|LOCATION|ORGANIZATION|EVENT|CASE_ID)\s*:\s*([^;\n,]{2,100})", re.I)


def extract_entities(*texts: str | None, metadata: dict | None = None) -> list[dict]:
    """Conservative extraction: dates/IDs by format, other entities only when explicitly marked."""
    found: dict[tuple[str, str], dict] = {}
    for text in texts:
        if not text:
            continue
        for match in CASE_ID.finditer(text):
            value = match.group(1).strip()
            if not any(char.isdigit() for char in value) and not any(mark in value for mark in ("-", "_", "/")):
                continue
            found[("CASE_ID", normalize_text(value))] = {"type": "CASE_ID", "value": value, "normalized_value": normalize_text(value), "method": "CASE_ID_PATTERN"}
        for pattern in DATE_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                found[("DATE", normalize_text(value))] = {"type": "DATE", "value": value, "normalized_value": normalize_text(value), "method": "DATE_PATTERN"}
        for match in MARKED_ENTITY.finditer(text):
            entity_type, value = match.group(1).upper(), match.group(2).strip()
            normalized = normalize_location(value)["normalized_value"] if entity_type == "LOCATION" else normalize_text(value)
            found[(entity_type, normalized)] = {"type": entity_type, "value": value, "normalized_value": normalized, "method": "EXPLICIT_LABEL"}
    for entity_type, key in ((metadata or {}).get("entities", {}).items() if isinstance((metadata or {}).get("entities"), dict) else []):
        values = key if isinstance(key, list) else [key]
        for value in values:
            if isinstance(value, str) and value.strip() and entity_type.upper() in {"PERSON", "LOCATION", "ORGANIZATION", "EVENT", "CASE_ID"}:
                normalized = normalize_location(value)["normalized_value"] if entity_type.upper() == "LOCATION" else normalize_text(value)
                found[(entity_type.upper(), normalized)] = {"type": entity_type.upper(), "value": value, "normalized_value": normalized, "method": "SOURCE_METADATA"}
    return list(found.values())
