from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.config import settings
from app.models.evidence import Evidence
from app.models.investigation import Investigation
from app.models.web_research import ResearchRun, ResearchRunEvidence, ResearchSearch, ResearchStatus, ResearchTrigger, SearchType, WebSearchResult, WebSource
from app.serpapi.client import SerpApiClient, SerpApiError
from app.serpapi.parsers import canonicalize_url, parse_results

serpapi_client = SerpApiClient(settings.serpapi_api_key, settings.serpapi_timeout_seconds, mock_mode=settings.serpapi_mock_mode)


class WebResearchError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code, self.message, self.status_code = code, message, status_code


class WebResearchService:
    def __init__(self, db: Session, client: SerpApiClient | None = None):
        self.db = db
        self.client = client or serpapi_client

    def engine_type(self, search_type: SearchType) -> tuple[str, dict]:
        if search_type == SearchType.NEWS:
            return "google_news", {}
        if search_type == SearchType.NEWS_TAB:
            return "google", {"tbm": "nws"}
        if search_type == SearchType.IMAGE:
            return "google_images", {}
        return settings.serpapi_default_engine, {}

    def manual_search(self, investigation_id: UUID, query: str, search_type: SearchType) -> dict:
        clean = " ".join(query.split())
        if not clean or len(clean) > settings.max_search_query_length:
            raise WebResearchError("INVALID_QUERY", f"Search query must contain 1 to {settings.max_search_query_length} characters.", 422)
        return self._run(investigation_id, f"Manual {search_type.value} search", ResearchTrigger.MANUAL,
                         [{"query": clean, "search_type": search_type}], [])

    def run_generated(self, investigation_id: UUID, queries: list[dict], evidence_ids: list[UUID] | None = None, agent_run_id: UUID | None = None, result_limit: int | None = None) -> dict:
        if not queries or len(queries) > settings.serpapi_max_queries_per_run:
            raise WebResearchError("INVALID_QUERY_COUNT", f"A research run must contain 1 to {settings.serpapi_max_queries_per_run} queries.", 422)
        clean_queries = []
        for query in queries:
            clean = " ".join(str(query.get("query", "")).split())
            if not clean or len(clean) > settings.max_search_query_length:
                raise WebResearchError("INVALID_QUERY", f"Every search query must contain 1 to {settings.max_search_query_length} characters.", 422)
            kind = query.get("search_type", SearchType.WEB)
            try: kind = kind if isinstance(kind, SearchType) else SearchType(kind)
            except ValueError: raise WebResearchError("INVALID_SEARCH_TYPE", "Search type must be WEB, NEWS, NEWS_TAB, or IMAGE.", 422) from None
            clean_queries.append({"query": clean, "search_type": kind})
        investigation = self.db.get(Investigation, investigation_id)
        if investigation is None:
            raise WebResearchError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        evidence = []
        if evidence_ids:
            evidence = list(self.db.scalars(select(Evidence).where(Evidence.investigation_id == investigation_id, Evidence.id.in_(evidence_ids))))
            if len({item.id for item in evidence}) != len(set(evidence_ids)):
                raise WebResearchError("EVIDENCE_INVESTIGATION_MISMATCH", "Selected evidence must belong to this investigation.", 403)
        return self._run(investigation_id, "Investigator defined research queries", ResearchTrigger.EVIDENCE_RESEARCH if evidence else ResearchTrigger.MANUAL, clean_queries, evidence, agent_run_id, result_limit)

    def from_evidence(self, investigation_id: UUID, evidence_ids: list[UUID] | None = None) -> dict:
        investigation = self.db.get(Investigation, investigation_id)
        if investigation is None:
            raise WebResearchError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        stmt = select(Evidence).where(Evidence.investigation_id == investigation_id).order_by(Evidence.created_at.desc())
        if evidence_ids:
            stmt = stmt.where(Evidence.id.in_(evidence_ids))
        evidence = list(self.db.scalars(stmt))
        if evidence_ids and len({item.id for item in evidence}) != len(set(evidence_ids)):
            raise WebResearchError("EVIDENCE_INVESTIGATION_MISMATCH", "Selected evidence must belong to this investigation.", 403)
        if not evidence:
            raise WebResearchError("NO_EVIDENCE", "Add or select evidence before starting evidence research.", 422)
        # Bounded deterministic strategies use only investigator-supplied words.
        seeds = []
        for item in evidence:
            value = item.text_content if item.text_content else " ".join((item.title, item.description, item.original_filename or ""))
            if value and value.strip():
                seeds.append((value.strip(), item.id))
        seeds.append((investigation.title, None))
        if investigation.description.strip():
            seeds.append((investigation.description.strip(), None))
        queries = []
        seen = set()
        for seed, evidence_id in seeds:
            clean = " ".join(seed.split())[:500]
            for kind, suffix, reason in ((SearchType.WEB, "", "Search the web for the provided case or evidence text."),
                                         (SearchType.NEWS, " news", "Search public news reporting using the provided case or evidence text."),
                                         (SearchType.IMAGE, "", "Search public images using the provided case or evidence text.")):
                variant = f"{clean}{suffix}".strip()[:settings.max_search_query_length]
                key = (variant.casefold(), kind.value)
                if variant and key not in seen:
                    seen.add(key)
                    queries.append({"query": variant, "search_type": kind, "reason": reason, "evidence_ids": [str(evidence_id)] if evidence_id else []})
                    if len(queries) >= settings.serpapi_max_queries_per_run:
                        break
            if len(queries) >= settings.serpapi_max_queries_per_run:
                break
        if not queries:
            raise WebResearchError("NO_SEARCHABLE_TEXT", "Selected evidence contains no searchable text or descriptive metadata.", 422)
        return self._run(investigation_id, "Research public web sources based on selected case evidence", ResearchTrigger.EVIDENCE_RESEARCH, queries, evidence)

    def _run(self, investigation_id: UUID, objective: str, trigger: ResearchTrigger, searches: list[dict], evidence: list[Evidence], agent_run_id: UUID | None = None, result_limit: int | None = None) -> dict:
        if self.db.get(Investigation, investigation_id) is None:
            raise WebResearchError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        searches = searches[:settings.serpapi_max_queries_per_run]
        now = datetime.now(timezone.utc)
        run = ResearchRun(investigation_id=investigation_id, agent_run_id=agent_run_id, objective=objective[:500], trigger=trigger, status=ResearchStatus.RUNNING, metadata_json={"query_count": len(searches)})
        self.db.add(run)
        self.db.flush()
        for item in evidence:
            self.db.add(ResearchRunEvidence(research_run_id=run.id, evidence_id=item.id))
        records = []
        for item in searches:
            search_type = item["search_type"]
            engine, params = self.engine_type(search_type)
            params.update({"engine": engine, "q": item["query"], "gl": settings.serpapi_default_gl, "hl": settings.serpapi_default_hl,
                           "reason": item.get("reason"), "evidence_ids": item.get("evidence_ids", [])})
            params = {key: value for key, value in params.items() if value is not None}
            record = ResearchSearch(investigation_id=investigation_id, research_run_id=run.id, query=item["query"], engine=engine,
                                    search_type=search_type, parameters=params.copy(), status=ResearchStatus.RUNNING)
            self.db.add(record)
            records.append((record, params))
        self.db.commit()
        any_success = False
        total = 0
        for search, params in records:
            try:
                provider_params = {key: value for key, value in params.items() if key not in {"reason", "evidence_ids"}}
                payload = self.client.search(provider_params)
                search.serpapi_search_id = self._search_id(payload)
                metadata = payload.get("search_metadata") if isinstance(payload.get("search_metadata"), dict) else {}
                search.serpapi_status = str(metadata.get("status") or ("Demo" if metadata.get("mock") else "Success"))[:80]
                search.search_timestamp = str(metadata.get("created_at") or metadata.get("processed_at") or "")[:120] or None
                rows = parse_results(payload, search.search_type, min(settings.serpapi_max_results_per_query, result_limit) if result_limit is not None else settings.serpapi_max_results_per_query)
                for result in rows:
                    source_id = self._upsert_source(investigation_id, result.url, result.title, result.source_name, result.result_type)
                    self.db.add(WebSearchResult(investigation_id=investigation_id, research_run_id=run.id, search_id=search.id, source_id=source_id,
                        result_type=result.result_type, title=result.title, url=result.url, snippet=result.snippet, source_name=result.source_name,
                        displayed_url=result.displayed_url, published_at=result.published_at, thumbnail_url=result.thumbnail_url,
                        position=result.position, metadata_json=result.metadata or {}))
                search.status = ResearchStatus.COMPLETED
                search.result_count = len(rows)
                search.completed_at = datetime.now(timezone.utc)
                any_success = True
                total += len(rows)
            except SerpApiError as exc:
                search.status = ResearchStatus.FAILED
                search.error_code = exc.code
                search.error_message = exc.message[:500]
                search.completed_at = datetime.now(timezone.utc)
        run.status = ResearchStatus.COMPLETED if any_success else ResearchStatus.FAILED
        run.completed_at = datetime.now(timezone.utc)
        run.metadata_json = self._summary(records, run.id)
        self.db.commit()
        self.db.refresh(run)
        return self.get_run(investigation_id, run.id)

    def _upsert_source(self, investigation_id, url, title, source_name, result_type):
        original, canonical = canonicalize_url(url)
        if not canonical:
            return None
        source = self.db.scalar(select(WebSource).where(WebSource.investigation_id == investigation_id, WebSource.canonical_url == canonical))
        if source is None:
            host = urlsplit(canonical).hostname
            source = WebSource(investigation_id=investigation_id, url=original, canonical_url=canonical, domain=host, title=title,
                               source_name=source_name, source_type=result_type, metadata_json={})
            self.db.add(source)
            self.db.flush()
        else:
            source.last_seen_at = datetime.now(timezone.utc)
            if title and not source.title: source.title = title
            if source_name and not source.source_name: source.source_name = source_name
        return source.id

    @staticmethod
    def _search_id(payload):
        value = payload.get("search_metadata")
        identifier = (value.get("id") or value.get("job_id")) if isinstance(value, dict) else None
        return str(identifier)[:120] if identifier is not None else None

    def _summary(self, records, run_id):
        successful = [row for row, _ in records if row.status == ResearchStatus.COMPLETED]
        failed = [row for row, _ in records if row.status == ResearchStatus.FAILED]
        rows = list(self.db.scalars(select(WebSearchResult).where(WebSearchResult.research_run_id == run_id)))
        return {"query_count": len(records), "completed_search_count": len(successful), "failed_search_count": len(failed),
                "result_count": len(rows), "unique_source_count": len({row.source_id for row in rows if row.source_id}),
                "web_count": sum(row.result_type.value == "WEB" for row in rows), "news_count": sum(row.result_type.value == "NEWS" for row in rows),
                "image_count": sum(row.result_type.value == "IMAGE" for row in rows), "demo_mode": self.client.last_status == "MOCK_MODE"}

    def list_runs(self, investigation_id: UUID, limit: int = 25, offset: int = 0) -> dict:
        self._require_investigation(investigation_id)
        runs = list(self.db.scalars(select(ResearchRun).where(ResearchRun.investigation_id == investigation_id).order_by(ResearchRun.created_at.desc()).offset(offset).limit(limit)))
        items = []
        for run in runs:
            searches = list(self.db.scalars(select(ResearchSearch).where(ResearchSearch.research_run_id == run.id)))
            evidence = list(self.db.scalars(select(Evidence).join(ResearchRunEvidence, ResearchRunEvidence.evidence_id == Evidence.id).where(ResearchRunEvidence.research_run_id == run.id)))
            item = self._run_dict(run, evidence)
            item["searches"] = []
            item["search_count"] = len(searches)
            items.append(item)
        return {"items": items, "limit": limit, "offset": offset}

    def get_run(self, investigation_id: UUID, run_id: UUID) -> dict:
        run = self.db.scalar(select(ResearchRun).where(ResearchRun.investigation_id == investigation_id, ResearchRun.id == run_id))
        if run is None:
            raise WebResearchError("RESEARCH_RUN_NOT_FOUND", "Research run was not found.", 404)
        searches = list(self.db.scalars(select(ResearchSearch).where(ResearchSearch.research_run_id == run_id).order_by(ResearchSearch.created_at)))
        evidence = list(self.db.scalars(select(Evidence).join(ResearchRunEvidence, ResearchRunEvidence.evidence_id == Evidence.id).where(ResearchRunEvidence.research_run_id == run_id)))
        result = self._run_dict(run, evidence)
        result["searches"] = []
        for search in searches:
            rows = list(self.db.scalars(select(WebSearchResult).where(WebSearchResult.search_id == search.id).order_by(WebSearchResult.position).limit(100)))
            result["searches"].append({"id": str(search.id), "query": search.query, "engine": search.engine, "search_type": search.search_type.value,
                "parameters": search.parameters, "serpapi_search_id": search.serpapi_search_id, "serpapi_status": search.serpapi_status,
                "search_timestamp": search.search_timestamp, "status": search.status.value,
                "result_count": search.result_count, "error_code": search.error_code, "error_message": search.error_message,
                "created_at": search.created_at.isoformat() if search.created_at else None,
                "results": [self._result_dict(row) for row in rows]})
        return result

    def sources(self, investigation_id: UUID, limit: int = 25, offset: int = 0, query: str | None = None) -> dict:
        self._require_investigation(investigation_id)
        stmt = select(WebSource).where(WebSource.investigation_id == investigation_id).order_by(WebSource.last_seen_at.desc())
        count_stmt = select(func.count(WebSource.id)).where(WebSource.investigation_id == investigation_id)
        if query:
            predicate = WebSource.title.ilike(f"%{query}%") | WebSource.domain.ilike(f"%{query}%") | WebSource.source_name.ilike(f"%{query}%")
            stmt = stmt.where(predicate)
            count_stmt = count_stmt.where(predicate)
        items = list(self.db.scalars(stmt.offset(offset).limit(limit)))
        return {"items": [self._source_dict(item) for item in items], "total": self.db.scalar(count_stmt) or 0, "limit": limit, "offset": offset}

    def _require_investigation(self, investigation_id):
        if self.db.get(Investigation, investigation_id) is None:
            raise WebResearchError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)

    @staticmethod
    def _run_dict(run, evidence):
        return {"id": str(run.id), "investigation_id": str(run.investigation_id), "objective": run.objective, "trigger": run.trigger.value,
            "status": run.status.value, "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None, "metadata": run.metadata_json or {},
            "evidence": [{"id": str(e.id), "title": e.title, "type": e.type.value} for e in evidence]}

    def _source_dict(self, source):
        count = self.db.scalar(select(func.count(WebSearchResult.id)).where(WebSearchResult.source_id == source.id)) or 0
        return {"id": str(source.id), "url": source.url, "canonical_url": source.canonical_url, "domain": source.domain, "title": source.title,
            "source_name": source.source_name, "source_type": source.source_type.value, "first_seen_at": source.first_seen_at.isoformat(),
            "last_seen_at": source.last_seen_at.isoformat(), "result_count": count}

    def _result_dict(self, row):
        source = self.db.get(WebSource, row.source_id) if row.source_id else None
        return {"id": str(row.id), "investigation_id": str(row.investigation_id), "research_run_id": str(row.research_run_id), "search_id": str(row.search_id),
            "source_id": str(row.source_id) if row.source_id else None, "result_type": row.result_type.value, "title": row.title, "url": row.url,
            "snippet": row.snippet, "source_name": row.source_name, "displayed_url": row.displayed_url, "published_at": row.published_at,
            "thumbnail_url": row.thumbnail_url, "position": row.position, "metadata": row.metadata_json or {},
            "source": self._source_dict(source) if source else None}

    def usage(self, investigation_id: UUID) -> dict:
        self._require_investigation(investigation_id)
        searches = list(self.db.scalars(select(ResearchSearch).where(ResearchSearch.investigation_id == investigation_id)))
        today = datetime.now(timezone.utc).date()
        return {"search_count": len(searches), "today_search_count": sum(item.created_at.date() == today for item in searches if item.created_at),
                "result_count": sum(item.result_count for item in searches), "successful_search_count": sum(item.status == ResearchStatus.COMPLETED for item in searches),
                "failed_search_count": sum(item.status == ResearchStatus.FAILED for item in searches),
                "configured": bool(settings.serpapi_api_key) or settings.serpapi_mock_mode, "demo_mode": settings.serpapi_mock_mode, "recent_status": self.client.last_status}
