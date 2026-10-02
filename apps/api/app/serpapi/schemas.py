from dataclasses import dataclass
from app.models.web_research import ResultType


@dataclass
class ParsedResult:
    result_type: ResultType
    title: str | None
    url: str | None
    snippet: str | None = None
    source_name: str | None = None
    displayed_url: str | None = None
    published_at: str | None = None
    thumbnail_url: str | None = None
    position: int | None = None
    metadata: dict | None = None
