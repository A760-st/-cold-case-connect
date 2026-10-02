from urllib.parse import urlsplit, urlunsplit
from app.models.web_research import ResultType, SearchType
from app.serpapi.schemas import ParsedResult


def canonicalize_url(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    try:
        parts = urlsplit(value.strip())
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None, None
        host = parts.hostname.lower()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parts.port
        netloc = host if port is None or (parts.scheme.lower(), port) in {("http", 80), ("https", 443)} else f"{host}:{port}"
        path = parts.path or "/"
        canonical = urlunsplit(("https", netloc, path, parts.query, ""))
        return value.strip(), canonical
    except ValueError:
        return None, None


def parse_results(data: dict, search_type: SearchType, maximum: int) -> list[ParsedResult]:
    if search_type == SearchType.IMAGE:
        rows, result_type = data.get("images_results", []), ResultType.IMAGE
    elif search_type in {SearchType.NEWS, SearchType.NEWS_TAB}:
        rows, result_type = data.get("news_results", []), ResultType.NEWS
    else:
        rows, result_type = data.get("organic_results", []), ResultType.WEB
    if not isinstance(rows, list):
        rows = []
    parsed = []
    def text(value):
        return value.strip()[:1000] if isinstance(value, str) and value.strip() else None

    for i, row in enumerate(rows[:maximum], 1):
        if not isinstance(row, dict):
            continue
        candidate = row.get("link") or row.get("news_url")
        if not candidate and isinstance(row.get("source"), dict):
            candidate = row["source"].get("link")
        url, _ = canonicalize_url(candidate)
        image_url, _ = canonicalize_url(row.get("original") or row.get("thumbnail"))
        source = row.get("source")
        source_name = text(source.get("name")) if isinstance(source, dict) else text(source)
        displayed = text(row.get("displayed_link")) or text(row.get("displayed_url"))
        metadata = {}
        for key in ("position", "global_position"):
            if isinstance(row.get(key), int):
                metadata[key] = row[key]
        if text(row.get("date")):
            metadata["date"] = text(row["date"])
        for key in ("snippet_highlighted_words", "extensions"):
            value = row.get(key)
            if isinstance(value, list):
                metadata[key] = [item.strip()[:300] for item in value[:10] if isinstance(item, str) and item.strip()]
        if result_type == ResultType.IMAGE and image_url:
            metadata["image_url"] = image_url
        thumbnail, _ = canonicalize_url(row.get("thumbnail"))
        parsed.append(ParsedResult(result_type, text(row.get("title")), url, text(row.get("snippet")) or text(row.get("description")), source_name, displayed,
                                   text(row.get("date")), thumbnail if result_type == ResultType.IMAGE else None,
                                   row.get("position") if isinstance(row.get("position"), int) else i, metadata))
    return parsed
