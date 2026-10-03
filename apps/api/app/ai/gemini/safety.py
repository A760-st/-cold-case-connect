from __future__ import annotations

from typing import Any


def _normalize_ref(ref: str) -> str:
    if not ref:
        return ""
    return str(ref).strip().upper()


def validate_synthesis_references(payload: dict, known_refs: set[str]) -> dict:
    for fact in payload.get("key_facts", []):
        refs = fact.get("supporting_refs", []) or []
        for ref in refs:
            normalized = _normalize_ref(ref)
            if not normalized:
                continue
            if normalized not in known_refs:
                raise ValueError(f"Unsupported statement reference: {normalized}")
    for section in ("potential_connections", "contradictions", "research_gaps", "unanswered_questions"):
        for item in payload.get(section, []) or []:
            refs = item.get("supporting_refs", []) or []
            for ref in refs:
                normalized = _normalize_ref(ref)
                if normalized and normalized not in known_refs:
                    raise ValueError(f"Unsupported section reference: {normalized}")
    return payload


def list_known_refs(context: dict) -> set[str]:
    refs: set[str] = set()
    for item in context.get("evidence", []) or []:
        refs.add(_normalize_ref(item.get("source_ref", "")))
    for item in context.get("claims", []) or []:
        refs.add(_normalize_ref(item.get("source_ref", "")))
    for item in context.get("sources", []) or []:
        refs.add(_normalize_ref(item.get("source_ref", "")))
    for item in context.get("timeline", []) or []:
        refs.add(_normalize_ref(item.get("source_ref", "")))
    for item in context.get("contradictions", []) or []:
        refs.add(_normalize_ref(item.get("source_ref", "")))
    for item in context.get("research_gaps", []) or []:
        refs.add(_normalize_ref(item.get("source_ref", "")))
    return refs


def redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("Bearer ", "").replace("sk-", "[REDACTED]") if "Bearer " in value or value.startswith("sk-") else value
    if isinstance(value, dict):
        return {k: redact_sensitive_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_values(v) for v in value]
    return value
