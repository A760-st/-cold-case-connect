import re
from datetime import date, datetime

LOCATION_ALIASES = {"bangalore": "bengaluru", "bengaluru": "bengaluru"}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s#/-]", " ", value.casefold(), flags=re.UNICODE)).strip()


def normalize_location(value: str | None) -> dict | None:
    if not value or not value.strip():
        return None
    raw = " ".join(value.split())
    normalized = normalize_text(raw)
    if normalized in LOCATION_ALIASES:
        normalized = LOCATION_ALIASES[normalized]
        method = "KNOWN_ALIAS"
    else:
        method = "CASEFOLD_WHITESPACE_PUNCTUATION"
    return {"raw_value": raw, "normalized_value": normalized, "normalization_method": method}


def normalize_date(value) -> dict | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    if isinstance(value, (date, datetime)):
        parsed = value.date() if isinstance(value, datetime) else value
    else:
        parsed = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%B %d %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                parsed = datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return {"original_value": raw, "normalized_date": parsed.isoformat()}
