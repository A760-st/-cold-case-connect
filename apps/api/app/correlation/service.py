import re
import logging
from difflib import SequenceMatcher
from datetime import date
from collections import defaultdict
from bisect import bisect_left, bisect_right
from uuid import UUID
from sqlalchemy import select, func, delete, or_, case
from sqlalchemy.orm import Session
from app.config import settings
from app.correlation.entity_extractor import extract_entities
from app.correlation.normalizers import normalize_date, normalize_location, normalize_text
from app.correlation.rules import similarity_label, temporal_relation
from app.correlation.schemas import CorrelationScope, ManualCorrelationRequest, CorrelationReviewRequest
from app.models.agent import AgentAction, AgentActionType
from app.models.correlation import (Correlation, CorrelationCreatedBy, CorrelationObjectType,
    CorrelationReview, CorrelationReviewStatus, CorrelationType)
from app.models.evidence import Evidence
from app.models.historical_case import HistoricalCase
from app.models.historical_case_image import HistoricalCaseImage
from app.models.investigation import Investigation
from app.models.web_research import WebSearchResult, WebSource, ResultType, ResearchSearch, ResearchStatus, SearchType

logger = logging.getLogger("coldsync.correlation")


class CorrelationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code, self.message, self.status_code = code, message, status_code


class CorrelationService:
    MAX_CASES = 1000
    MAX_RESULTS = 2000
    MAX_CORRELATIONS_PER_RUN = 5000

    def __init__(self, db: Session):
        self.db = db

    def run(self, investigation_id: UUID, scope: CorrelationScope) -> dict:
        investigation = self.db.get(Investigation, investigation_id)
        if investigation is None:
            raise CorrelationError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        context = {"title": investigation.title, "description": investigation.description}
        stats = {"created": 0, "updated": 0, "existing": 0, "failed_rules": [], "completed_rule_names": [], "candidate_limit_reached": False}
        evidence = list(self.db.scalars(select(Evidence).where(Evidence.investigation_id == investigation_id).order_by(Evidence.created_at).limit(500)))
        cases = []
        results = []
        if scope in set(CorrelationScope):
            cases = list(self.db.scalars(select(HistoricalCase).order_by(HistoricalCase.updated_at.desc()).limit(self.MAX_CASES)))
        if scope in {CorrelationScope.ALL, CorrelationScope.WEB, CorrelationScope.NEWS, CorrelationScope.IMAGES}:
            query = select(WebSearchResult).where(WebSearchResult.investigation_id == investigation_id).order_by(WebSearchResult.created_at.desc())
            if scope == CorrelationScope.WEB:
                query = query.where(WebSearchResult.result_type == ResultType.WEB)
            elif scope == CorrelationScope.NEWS:
                query = query.where(WebSearchResult.result_type == ResultType.NEWS)
            elif scope == CorrelationScope.IMAGES:
                query = query.where(WebSearchResult.result_type == ResultType.IMAGE)
            results = list(self.db.scalars(query.limit(self.MAX_RESULTS)))
        actions = list(self.db.scalars(select(AgentAction).where(AgentAction.investigation_id == investigation_id,
            AgentAction.action_type.in_([AgentActionType.SEARCH_HISTORICAL_TEXT, AgentActionType.SEARCH_HISTORICAL_IMAGES])).order_by(AgentAction.created_at.desc()).limit(1000)))
        searches_query = select(ResearchSearch).where(ResearchSearch.investigation_id == investigation_id, ResearchSearch.status == ResearchStatus.FAILED)
        if scope == CorrelationScope.WEB:
            searches_query = searches_query.where(ResearchSearch.search_type == SearchType.WEB)
        elif scope == CorrelationScope.NEWS:
            searches_query = searches_query.where(ResearchSearch.search_type.in_([SearchType.NEWS, SearchType.NEWS_TAB]))
        elif scope == CorrelationScope.IMAGES:
            searches_query = searches_query.where(ResearchSearch.search_type == SearchType.IMAGE)
        failed_public_searches = list(self.db.scalars(searches_query.limit(100))) if scope in {CorrelationScope.ALL, CorrelationScope.WEB, CorrelationScope.NEWS, CorrelationScope.IMAGES} else []

        def apply_rule(name, operation):
            local_counts = {"created": 0, "updated": 0, "existing": 0}
            try:
                for candidate in operation():
                    if sum(stats[key] + local_counts[key] for key in ("created", "updated", "existing")) >= self.MAX_CORRELATIONS_PER_RUN:
                        stats["candidate_limit_reached"] = True
                        break
                    outcome = self._upsert(investigation_id, **candidate)
                    local_counts[outcome] += 1
                self.db.commit()
                for key, value in local_counts.items():
                    stats[key] += value
                stats["completed_rule_names"].append(name)
            except Exception:
                logger.exception("Correlation rule failed: %s", name)
                self.db.rollback()
                stats["failed_rules"].append(name)

        if scope in {CorrelationScope.ALL, CorrelationScope.EVIDENCE, CorrelationScope.HISTORICAL}:
            apply_rule("semantic_similarity", lambda: self._semantic(actions, evidence, cases))
            apply_rule("shared_location", lambda: self._attribute_correlations(evidence, cases, "location", context))
            apply_rule("temporal_proximity", lambda: self._attribute_correlations(evidence, cases, "date", context))
            apply_rule("shared_case_type", lambda: self._attribute_correlations(evidence, cases, "case_type", context))
        if scope in set(CorrelationScope):
            apply_rule("entity_overlap", lambda: self._entity_correlations(evidence, cases, results, context))
        if scope in {CorrelationScope.ALL, CorrelationScope.EVIDENCE, CorrelationScope.HISTORICAL, CorrelationScope.IMAGES}:
            apply_rule("visual_similarity", lambda: self._visual(actions, evidence))
        if scope in {CorrelationScope.ALL, CorrelationScope.WEB, CorrelationScope.NEWS, CorrelationScope.IMAGES}:
            apply_rule("source_reference", lambda: self._source_references(results, cases))
            apply_rule("contextual_relevance", lambda: self._contextual_correlations(evidence, results))
        failed_action_types = {action.action_type for action in actions if action.status.value == "FAILED"}
        for action_type, rule_name in ((AgentActionType.SEARCH_HISTORICAL_TEXT, "semantic_similarity"), (AgentActionType.SEARCH_HISTORICAL_IMAGES, "visual_similarity")):
            if rule_name == "semantic_similarity" and scope not in {CorrelationScope.ALL, CorrelationScope.EVIDENCE, CorrelationScope.HISTORICAL}:
                continue
            if rule_name == "visual_similarity" and scope not in {CorrelationScope.ALL, CorrelationScope.EVIDENCE, CorrelationScope.HISTORICAL, CorrelationScope.IMAGES}:
                continue
            if action_type in failed_action_types and rule_name not in stats["failed_rules"]:
                stats["failed_rules"].append(rule_name)
                if rule_name in stats["completed_rule_names"]:
                    stats["completed_rule_names"].remove(rule_name)
        if failed_public_searches:
            stats["failed_rules"].append("public_research_results")
        self.db.commit()
        return {"status": "PARTIAL" if stats["failed_rules"] or stats["candidate_limit_reached"] else "COMPLETED", "scope": scope.value,
                "completed_rules": len(stats["completed_rule_names"]), "completed_rule_names": stats["completed_rule_names"], "failed_rules": stats["failed_rules"],
                "created": stats["created"], "updated": stats["updated"], "existing": stats["existing"],
                "candidate_limit_reached": stats["candidate_limit_reached"],
                "records_considered": {"evidence": len(evidence), "historical_cases": len(cases), "research_results": len(results), "agent_actions": len(actions), "failed_public_searches": len(failed_public_searches)},
                "truncated": {"evidence": len(evidence) >= 500, "historical_cases": len(cases) >= self.MAX_CASES, "research_results": len(results) >= self.MAX_RESULTS}}

    def _semantic(self, actions, evidence, cases):
        evidence_by_id, cases_by_id = {str(x.id): x for x in evidence}, {str(x.id): x for x in cases}
        for action in actions:
            if action.action_type != AgentActionType.SEARCH_HISTORICAL_TEXT or action.status.value != "COMPLETED":
                continue
            basis_ids = (action.input_payload or {}).get("evidence_ids", [])
            for match in (action.output_summary or {}).get("matches", []):
                case = cases_by_id.get(str(match.get("historical_case_id")))
                score = self._score(match.get("similarity_score"))
                if not case or score is None:
                    continue
                for evidence_id in basis_ids:
                    item = evidence_by_id.get(str(evidence_id))
                    if item:
                        yield self._candidate(item.id, CorrelationObjectType.EVIDENCE, case.id, CorrelationObjectType.HISTORICAL_CASE,
                            CorrelationType.SEMANTIC_SIMILARITY, score, "The historical case was retrieved through SBERT semantic search of this evidence.",
                            [{"type": "SEMANTIC_SIMILARITY", "score": score}], {"method": "SBERT", "model": settings.sbert_model_name,
                                "score": score, "source": "historical_search", "agent_action_id": str(action.id), "evidence_id": str(item.id), "requires_verification": True})

    def _visual(self, actions, evidence):
        evidence_by_id = {str(x.id): x for x in evidence}
        for action in actions:
            if action.action_type != AgentActionType.SEARCH_HISTORICAL_IMAGES or action.status.value != "COMPLETED":
                continue
            ids = (action.input_payload or {}).get("evidence_ids", [])
            for match in (action.output_summary or {}).get("matches", []):
                try:
                    image_id = UUID(str(match.get("image_id")))
                except (ValueError, TypeError):
                    continue
                image = self.db.get(HistoricalCaseImage, image_id)
                score = self._score(match.get("visual_similarity"))
                if not image or score is None:
                    continue
                for evidence_id in ids:
                    item = evidence_by_id.get(str(evidence_id))
                    if item:
                        yield self._candidate(item.id, CorrelationObjectType.EVIDENCE, image.id, CorrelationObjectType.HISTORICAL_IMAGE,
                            CorrelationType.VISUAL_SIMILARITY, score, "The historical image was retrieved through CLIP visual similarity; this signal does not establish identity.",
                            [{"type": "VISUAL_SIMILARITY", "score": score}], {"method": "CLIP", "model": settings.clip_model_name,
                                "score": score, "source": "historical_image_search", "agent_action_id": str(action.id), "evidence_id": str(item.id),
                                "historical_case_id": str(image.historical_case_id), "requires_verification": True})

    def _attribute_correlations(self, evidence, cases, field, context=None):
        case_index = defaultdict(list)
        dated_cases = []
        dates_by_year, dates_by_month = defaultdict(list), defaultdict(list)
        for case in cases:
            if field == "location":
                normalized = normalize_location(case.location)
                if normalized:
                    case_index[normalized["normalized_value"]].append(case)
            elif field == "case_type":
                normalized = normalize_text(case.case_type)
                if normalized:
                    case_index[normalized].append(case)
            elif field == "date" and case.case_date:
                ordinal = case.case_date.toordinal()
                dated_cases.append((ordinal, case))
                dates_by_year[case.case_date.year].append((ordinal, case))
                dates_by_month[(case.case_date.year, case.case_date.month)].append((ordinal, case))
        dated_cases.sort(key=lambda row: row[0])
        ordinals = [row[0] for row in dated_cases]
        for item in evidence:
            candidates = []
            if field == "location":
                value = (item.metadata_json or {}).get("location") or self._marked_value(item, "LOCATION")
                if not value:
                    value = self._marked_context_value(context, "LOCATION")
                normalized = normalize_location(value)
                candidates = case_index.get(normalized["normalized_value"], []) if normalized else []
            elif field == "case_type":
                value = (item.metadata_json or {}).get("case_type")
                candidates = case_index.get(normalize_text(value), []) if value else []
            else:
                item_date = self._evidence_date(item)
                if item_date:
                    parsed = date.fromisoformat(item_date["normalized_date"])
                    candidates = [case for _, case in dates_by_year.get(parsed.year, [])]
                    candidates.extend(case for _, case in dates_by_month.get((parsed.year - 1, 12), []) if abs((case.case_date - parsed).days) <= 30)
                    candidates.extend(case for _, case in dates_by_month.get((parsed.year + 1, 1), []) if abs((case.case_date - parsed).days) <= 30)
                    lo, hi = bisect_left(ordinals, parsed.toordinal() - 30), bisect_right(ordinals, parsed.toordinal() + 30)
                    candidates.extend(case for _, case in dated_cases[lo:hi])
                candidates = list({case.id: case for case in candidates}.values())
            for case in candidates:
                if field == "location":
                    left = (item.metadata_json or {}).get("location") or self._marked_value(item, "LOCATION")
                    value_source = "EVIDENCE_METADATA_OR_TEXT"
                    if not left:
                        left = self._marked_context_value(context, "LOCATION")
                        value_source = "INVESTIGATION_CONTEXT"
                    right = case.location
                    a, b = normalize_location(left), normalize_location(right)
                    if not a or not b or a["normalized_value"] != b["normalized_value"]:
                        continue
                    kind, explanation = CorrelationType.GEOGRAPHIC_OVERLAP, "Both records reference the same normalized location; this alone does not establish an event connection."
                    signal = {"type": kind.value, "raw_values": [a["raw_value"], b["raw_value"]], "normalized_value": a["normalized_value"]}
                    basis = {"method": "ATTRIBUTE_MATCH", "field": "location", "current_value": a, "historical_value": b, "current_source": value_source}
                elif field == "case_type":
                    left = (item.metadata_json or {}).get("case_type")
                    right = case.case_type
                    a, b = normalize_text(left), normalize_text(right)
                    if not a or a != b:
                        continue
                    kind, explanation = CorrelationType.SHARED_ATTRIBUTE, "Both records contain the same normalized case type."
                    signal = {"type": kind.value, "field": "case_type", "value": a}
                    basis = {"method": "ATTRIBUTE_MATCH", "field": "case_type", "current_value": left, "historical_value": right}
                else:
                    left = self._evidence_date(item, context)
                    right = normalize_date(case.case_date)
                    if not left or not right:
                        continue
                    relation = temporal_relation(date.fromisoformat(left["normalized_date"]), date.fromisoformat(right["normalized_date"]))
                    if not relation:
                        continue
                    type_value, days = relation
                    current_date, historical_date = date.fromisoformat(left["normalized_date"]), date.fromisoformat(right["normalized_date"])
                    relative_order = "SAME_DATE" if current_date == historical_date else ("BEFORE" if current_date < historical_date else "AFTER")
                    kind = CorrelationType(type_value)
                    explanation = "The records have dates within the same month/year or within 30 days; temporal proximity alone does not establish a connection."
                    signal = {"type": kind.value, "days_apart": days, "relative_order": relative_order, "dates": [left["normalized_date"], right["normalized_date"]]}
                    basis = {"method": "DATE_COMPARISON", "field": "date", "current_value": left, "historical_value": right, "relative_order": relative_order}
                yield self._candidate(item.id, CorrelationObjectType.EVIDENCE, case.id, CorrelationObjectType.HISTORICAL_CASE,
                    kind, None, explanation, [signal], basis)

    def _entity_correlations(self, evidence, cases, results, context=None):
        context_entities = extract_entities((context or {}).get("title"), (context or {}).get("description"))
        ev_entities = {}
        for item in evidence:
            entities = extract_entities(item.title, item.description, item.text_content, metadata=item.metadata_json)
            keys = {(entity["type"], entity["normalized_value"]) for entity in entities}
            for entity in context_entities:
                key = (entity["type"], entity["normalized_value"])
                if key not in keys:
                    entities.append({**entity, "source_origin": "INVESTIGATION_CONTEXT"})
            ev_entities[item.id] = entities
        hist_entities = {case.id: extract_entities(case.title, case.summary, case.description, metadata=case.metadata_json) for case in cases}
        historical_index = defaultdict(list)
        for case in cases:
            for entity in hist_entities[case.id]:
                prefix = entity["normalized_value"][:1]
                historical_index[(entity["type"], prefix)].append((case, entity))
        result_entities = {result.id: extract_entities(result.title, result.snippet, result.published_at, metadata=result.metadata_json) for result in results}
        result_index = defaultdict(list)
        for result in results:
            for entity in result_entities[result.id]:
                prefix = entity["normalized_value"][:1]
                result_index[(entity["type"], prefix)].append((result, entity))
        for item in evidence:
            candidate_cases = {}
            for entity in ev_entities[item.id]:
                for case, candidate_entity in historical_index.get((entity["type"], entity["normalized_value"][:1]), []):
                    if self._entity_match(entity, candidate_entity):
                        candidate_cases[case.id] = case
            for case in candidate_cases.values():
                overlaps = self._overlaps(ev_entities[item.id], hist_entities[case.id])
                if overlaps:
                    yield self._candidate(item.id, CorrelationObjectType.EVIDENCE, case.id, CorrelationObjectType.HISTORICAL_CASE,
                        CorrelationType.ENTITY_OVERLAP, None, "Both records contain an exact entity overlap or a conservative fuzzy candidate; verify the underlying references.", overlaps,
                        {"method": "ENTITY_MATCH", "matches": overlaps, "requires_verification": True})
        for item in evidence:
            left_entities = ev_entities[item.id]
            candidate_results = {}
            for entity in left_entities:
                for result, candidate_entity in result_index.get((entity["type"], entity["normalized_value"][:1]), []):
                    if self._entity_match(entity, candidate_entity):
                        candidate_results[result.id] = result
            for result in candidate_results.values():
                right_entities = result_entities[result.id]
                overlaps = self._overlaps(left_entities, right_entities)
                if overlaps:
                    yield self._candidate(item.id, CorrelationObjectType.EVIDENCE, result.id, self._result_object_type(result.result_type),
                        CorrelationType.ENTITY_OVERLAP, None, "Evidence and the public result contain an exact entity overlap or a conservative fuzzy candidate.", overlaps,
                        {"method": "ENTITY_MATCH", "matches": overlaps, "research_run_id": str(result.research_run_id), "search_id": str(result.search_id), "source_id": str(result.source_id) if result.source_id else None, "requires_verification": True})

    def _source_references(self, results, cases):
        case_index = {}
        token_index = defaultdict(set)
        for case in cases:
            markers = [normalize_text(case.external_id), normalize_text(case.title)]
            case_index[case.id] = (case, [marker for marker in markers if marker])
            for term in set().union(*(self._terms(marker) for marker in markers if marker)):
                token_index[term].add(case.id)
        for result in results:
            text = normalize_text(f"{result.title or ''} {result.snippet or ''} {result.url or ''}")
            possible_cases = set().union(*(token_index.get(term, set()) for term in self._terms(text))) if text else set()
            for case_id in possible_cases:
                case, terms = case_index[case_id]
                matched = [term for term in terms if term and (term in text)]
                if matched:
                    yield self._candidate(result.id, self._result_object_type(result.result_type), case.id, CorrelationObjectType.HISTORICAL_CASE,
                        CorrelationType.SOURCE_REFERENCE, None, "The public result title, snippet, or URL contains the historical case title or source identifier.",
                        [{"type": "SOURCE_REFERENCE", "matched_terms": matched}], {"method": "EXACT_SOURCE_TEXT_REFERENCE", "matched_terms": matched,
                         "research_run_id": str(result.research_run_id), "search_id": str(result.search_id), "source_id": str(result.source_id) if result.source_id else None,
                         "url": result.url, "requires_verification": True})
            if result.source_id:
                source = self.db.get(WebSource, result.source_id)
                if source:
                    yield self._candidate(result.id, self._result_object_type(result.result_type), source.id, CorrelationObjectType.SOURCE,
                        CorrelationType.SOURCE_REFERENCE, None, "This result is linked to the investigation source record shown in its research provenance.",
                        [{"type": "SOURCE_REFERENCE", "field": "source_id"}], {"method": "RESEARCH_PROVENANCE", "research_run_id": str(result.research_run_id), "search_id": str(result.search_id), "source_id": str(source.id), "url": source.url})

    def _contextual_correlations(self, evidence, results):
        term_index = defaultdict(list)
        terms_by_result = {}
        for result in results:
            terms = self._terms(normalize_text(" ".join([result.title or "", result.snippet or ""])))
            terms_by_result[result.id] = terms
            for term in terms:
                term_index[term].append(result)
        for item in evidence:
            e_text = normalize_text(" ".join([item.title or "", item.description or "", item.text_content or ""]))
            e_terms = self._terms(e_text)
            if not e_terms:
                continue
            candidates = {}
            for term in e_terms:
                for result in term_index.get(term, []):
                    candidates[result.id] = result
            for result in candidates.values():
                r_terms = terms_by_result[result.id]
                overlap = sorted(e_terms & r_terms)
                if len(overlap) < 2:
                    continue
                yield self._candidate(item.id, CorrelationObjectType.EVIDENCE, result.id, self._result_object_type(result.result_type),
                    CorrelationType.CONTEXTUAL_RELEVANCE, None, "The evidence and public result share multiple distinctive normalized terms; this is a text-overlap lead, not a factual confirmation.",
                    [{"type": "CONTEXTUAL_RELEVANCE", "method": "DISTINCTIVE_TOKEN_OVERLAP", "terms": overlap}],
                    {"method": "TOKEN_OVERLAP", "shared_terms": overlap, "research_run_id": str(result.research_run_id), "search_id": str(result.search_id), "source_id": str(result.source_id) if result.source_id else None, "url": result.url, "requires_verification": True})

    def _upsert(self, investigation_id, source_id, source_type, target_id, target_type, correlation_type, score, explanation, supporting_attributes, evidence_basis):
        source_type, source_id, target_type, target_id = self._canonical(source_type, target_type, source_id, target_id)
        row = self.db.scalar(select(Correlation).where(Correlation.investigation_id == investigation_id, Correlation.source_type == source_type,
            Correlation.source_id == source_id, Correlation.target_type == target_type, Correlation.target_id == target_id,
            Correlation.correlation_type == correlation_type))
        if row is None:
            row = Correlation(investigation_id=investigation_id, source_type=source_type, source_id=source_id,
                target_type=target_type, target_id=target_id, correlation_type=correlation_type, score=score,
                confidence_label=similarity_label(score) if score is not None else None, explanation=explanation,
                supporting_attributes=supporting_attributes, evidence_basis=evidence_basis, created_by=CorrelationCreatedBy.AI)
            self.db.add(row)
            self.db.flush()
            return "created"
        if row.created_by == CorrelationCreatedBy.INVESTIGATOR:
            return "existing"
        signals = list(row.supporting_attributes or [])
        changed = False
        for signal in supporting_attributes:
            if signal not in signals:
                signals.append(signal)
                changed = True
        row.supporting_attributes = signals
        basis = dict(row.evidence_basis or {})
        observations = list(basis.get("observations", [basis] if basis else []))
        if evidence_basis not in observations:
            observations.append(evidence_basis)
            changed = True
        row.evidence_basis = {"observations": observations}
        if score is not None and (row.score is None or score > row.score):
            row.score = score
            row.confidence_label = similarity_label(score)
            changed = True
        return "updated" if changed else "existing"

    def create_manual(self, investigation_id: UUID, payload: ManualCorrelationRequest) -> dict:
        if self.db.get(Investigation, investigation_id) is None:
            raise CorrelationError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        source = self._resolve(payload.source_type, payload.source_id, investigation_id)
        target = self._resolve(payload.target_type, payload.target_id, investigation_id)
        if source is None or target is None:
            raise CorrelationError("CORRELATION_OBJECT_NOT_FOUND", "Both records must exist in this investigation context.", 404)
        if payload.source_type == payload.target_type and payload.source_id == payload.target_id:
            raise CorrelationError("INVALID_CORRELATION_PAIR", "A record cannot be related to itself.", 422)
        pair = {payload.source_type, payload.target_type}
        if payload.correlation_type == CorrelationType.SEMANTIC_SIMILARITY and pair != {CorrelationObjectType.EVIDENCE, CorrelationObjectType.HISTORICAL_CASE}:
            raise CorrelationError("INVALID_CORRELATION_PAIR", "Semantic similarity requires evidence and a historical case.", 422)
        if payload.correlation_type == CorrelationType.VISUAL_SIMILARITY and pair != {CorrelationObjectType.EVIDENCE, CorrelationObjectType.HISTORICAL_IMAGE}:
            raise CorrelationError("INVALID_CORRELATION_PAIR", "Visual similarity requires evidence and a historical image.", 422)
        if payload.correlation_type == CorrelationType.SOURCE_REFERENCE:
            result_types = {CorrelationObjectType.WEB_RESULT, CorrelationObjectType.NEWS_RESULT, CorrelationObjectType.IMAGE_RESULT}
            if not ((payload.source_type in result_types and payload.target_type in {CorrelationObjectType.SOURCE, CorrelationObjectType.HISTORICAL_CASE}) or
                    (payload.target_type in result_types and payload.source_type in {CorrelationObjectType.SOURCE, CorrelationObjectType.HISTORICAL_CASE})):
                raise CorrelationError("INVALID_CORRELATION_PAIR", "A source reference must link a public result with a source or historical case.", 422)
        row = self._get_pair(investigation_id, payload.source_type, payload.source_id, payload.target_type, payload.target_id, payload.correlation_type)
        basis = {"method": "INVESTIGATOR_ADDED", "note": payload.note, "requires_verification": True}
        if row is None:
            st, si, tt, ti = self._canonical(payload.source_type, payload.target_type, payload.source_id, payload.target_id)
            row = Correlation(investigation_id=investigation_id, source_type=st, source_id=si, target_type=tt, target_id=ti,
                correlation_type=payload.correlation_type, score=None, confidence_label=None,
                explanation=payload.note, supporting_attributes=[], evidence_basis=basis, created_by=CorrelationCreatedBy.INVESTIGATOR)
            self.db.add(row)
        elif row.created_by == CorrelationCreatedBy.INVESTIGATOR:
            basis_old = dict(row.evidence_basis or {})
            observations = list(basis_old.get("observations", [basis_old] if basis_old else []))
            if basis not in observations:
                observations.append(basis)
            row.evidence_basis = {"observations": observations}
        else:
            # Preserve the AI record and its original provenance; investigator feedback is represented separately.
            self.add_review(row, CorrelationReviewRequest(review_status=CorrelationReviewStatus.REQUIRES_VERIFICATION, note=payload.note))
        self.db.commit()
        self.db.refresh(row)
        return self.detail(row.id)

    def _get_pair(self, investigation_id, st, si, tt, ti, kind):
        st, si, tt, ti = self._canonical(st, tt, si, ti)
        return self.db.scalar(select(Correlation).where(Correlation.investigation_id == investigation_id, Correlation.source_type == st, Correlation.source_id == si,
            Correlation.target_type == tt, Correlation.target_id == ti, Correlation.correlation_type == kind))

    def _resolve(self, kind, object_id, investigation_id):
        model_map = {CorrelationObjectType.EVIDENCE: Evidence, CorrelationObjectType.HISTORICAL_CASE: HistoricalCase,
            CorrelationObjectType.HISTORICAL_IMAGE: HistoricalCaseImage, CorrelationObjectType.WEB_RESULT: WebSearchResult,
            CorrelationObjectType.NEWS_RESULT: WebSearchResult, CorrelationObjectType.IMAGE_RESULT: WebSearchResult, CorrelationObjectType.SOURCE: WebSource}
        obj = self.db.get(model_map[kind], object_id)
        if obj is None:
            return None
        if kind == CorrelationObjectType.EVIDENCE or kind in {CorrelationObjectType.WEB_RESULT, CorrelationObjectType.NEWS_RESULT, CorrelationObjectType.IMAGE_RESULT, CorrelationObjectType.SOURCE}:
            if obj.investigation_id != investigation_id:
                return None
        if kind in {CorrelationObjectType.WEB_RESULT, CorrelationObjectType.NEWS_RESULT, CorrelationObjectType.IMAGE_RESULT} and self._result_object_type(obj.result_type) != kind:
            return None
        return obj

    def list(self, investigation_id, correlation_type=None, source_type=None, target_type=None, minimum_score=None, review_status=None, reviewed=None, evidence_id=None, matrix_group=None, limit=100, offset=0):
        if self.db.get(Investigation, investigation_id) is None:
            raise CorrelationError("INVESTIGATION_NOT_FOUND", "Investigation was not found.", 404)
        q = select(Correlation).where(Correlation.investigation_id == investigation_id)
        if correlation_type: q = q.where(Correlation.correlation_type == correlation_type)
        if source_type: q = q.where(Correlation.source_type == source_type)
        if target_type: q = q.where(Correlation.target_type == target_type)
        if minimum_score is not None: q = q.where(Correlation.score >= minimum_score)
        if evidence_id is not None:
            q = q.where(or_((Correlation.source_type == CorrelationObjectType.EVIDENCE) & (Correlation.source_id == evidence_id),
                            (Correlation.target_type == CorrelationObjectType.EVIDENCE) & (Correlation.target_id == evidence_id)))
        if matrix_group == "historical":
            q = q.where(or_(Correlation.source_type.in_([CorrelationObjectType.HISTORICAL_CASE, CorrelationObjectType.HISTORICAL_IMAGE]), Correlation.target_type.in_([CorrelationObjectType.HISTORICAL_CASE, CorrelationObjectType.HISTORICAL_IMAGE])))
        elif matrix_group in {"web", "news", "images"}:
            kind = {"web": CorrelationObjectType.WEB_RESULT, "news": CorrelationObjectType.NEWS_RESULT, "images": CorrelationObjectType.IMAGE_RESULT}[matrix_group]
            q = q.where(or_(Correlation.source_type == kind, Correlation.target_type == kind))
        latest_review = select(CorrelationReview.review_status).where(CorrelationReview.correlation_id == Correlation.id).order_by(CorrelationReview.created_at.desc(), CorrelationReview.id.desc()).limit(1).scalar_subquery()
        if review_status:
            q = q.where(or_(latest_review == review_status, latest_review.is_(None)) if review_status == CorrelationReviewStatus.REQUIRES_VERIFICATION else latest_review == review_status)
        if reviewed is True:
            q = q.where(latest_review.is_not(None))
        elif reviewed is False:
            q = q.where(latest_review.is_(None))
        total = self.db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
        rows = list(self.db.scalars(q.order_by(Correlation.created_at.desc()).offset(offset).limit(limit)))
        latest = {row.id: row for row in self.db.scalars(select(CorrelationReview).where(CorrelationReview.correlation_id.in_([r.id for r in rows])).order_by(CorrelationReview.created_at.asc(), CorrelationReview.id.asc()))} if rows else {}
        return {"items": [self.serialize(row, latest.get(row.id)) for row in rows], "total": total, "limit": limit, "offset": offset,
                "summary": self.summary(investigation_id)}

    def summary(self, investigation_id):
        base = Correlation.investigation_id == investigation_id
        historical_types = [CorrelationObjectType.HISTORICAL_CASE, CorrelationObjectType.HISTORICAL_IMAGE]
        total = self.db.scalar(select(func.count()).select_from(Correlation).where(base)) or 0
        def count_type(kind):
            return self.db.scalar(select(func.count()).select_from(Correlation).where(base, or_(Correlation.source_type == kind, Correlation.target_type == kind))) or 0
        group_kind = case(
            (or_(Correlation.source_type.in_(historical_types), Correlation.target_type.in_(historical_types)), "historical"),
            (or_(Correlation.source_type == CorrelationObjectType.NEWS_RESULT, Correlation.target_type == CorrelationObjectType.NEWS_RESULT), "news"),
            (or_(Correlation.source_type == CorrelationObjectType.IMAGE_RESULT, Correlation.target_type == CorrelationObjectType.IMAGE_RESULT), "images"),
            (or_(Correlation.source_type == CorrelationObjectType.WEB_RESULT, Correlation.target_type == CorrelationObjectType.WEB_RESULT), "web"),
            else_=None)
        evidence_id = case((Correlation.source_type == CorrelationObjectType.EVIDENCE, Correlation.source_id), else_=Correlation.target_id)
        rows = self.db.execute(select(evidence_id, group_kind, func.count()).where(base,
            or_(Correlation.source_type == CorrelationObjectType.EVIDENCE, Correlation.target_type == CorrelationObjectType.EVIDENCE),
            group_kind.is_not(None)).group_by(evidence_id, group_kind)).all()
        matrix = defaultdict(lambda: {"historical": 0, "web": 0, "news": 0, "images": 0})
        for item_id, group, amount in rows:
            matrix[str(item_id)][group] = amount
        return {"total": total, "historical": self.db.scalar(select(func.count()).select_from(Correlation).where(base, or_(Correlation.source_type.in_(historical_types), Correlation.target_type.in_(historical_types)))) or 0,
                "web": count_type(CorrelationObjectType.WEB_RESULT), "news": count_type(CorrelationObjectType.NEWS_RESULT), "images": count_type(CorrelationObjectType.IMAGE_RESULT),
                "evidence_matrix": dict(matrix)}

    def detail(self, correlation_id):
        row = self.db.get(Correlation, correlation_id)
        if row is None:
            raise CorrelationError("CORRELATION_NOT_FOUND", "Correlation was not found.", 404)
        reviews = list(self.db.scalars(select(CorrelationReview).where(CorrelationReview.correlation_id == row.id).order_by(CorrelationReview.created_at.desc())))
        return self.serialize(row, reviews[0] if reviews else None, include_review_history=reviews)

    def add_review(self, row: Correlation, payload: CorrelationReviewRequest):
        review = CorrelationReview(correlation_id=row.id, review_status=payload.review_status, note=payload.note)
        self.db.add(review)
        self.db.flush()
        return review

    def review(self, correlation_id, payload):
        row = self.db.get(Correlation, correlation_id)
        if row is None:
            raise CorrelationError("CORRELATION_NOT_FOUND", "Correlation was not found.", 404)
        self.add_review(row, payload)
        self.db.commit()
        return self.detail(correlation_id)

    def delete(self, correlation_id):
        row = self.db.get(Correlation, correlation_id)
        if row is None:
            raise CorrelationError("CORRELATION_NOT_FOUND", "Correlation was not found.", 404)
        self.db.execute(delete(CorrelationReview).where(CorrelationReview.correlation_id == correlation_id))
        self.db.delete(row)
        self.db.commit()

    def serialize(self, row, review=None, include_review_history=None):
        return {"id": str(row.id), "investigation_id": str(row.investigation_id), "source_type": row.source_type.value, "source_id": str(row.source_id),
            "source": self._object_summary(row.source_type, row.source_id), "target_type": row.target_type.value, "target_id": str(row.target_id),
            "target": self._object_summary(row.target_type, row.target_id), "correlation_type": row.correlation_type.value, "score": row.score,
            "score_semantics": "similarity/relevance signal only; not probability", "confidence_label": row.confidence_label, "explanation": row.explanation,
            "supporting_attributes": row.supporting_attributes or [], "evidence_basis": row.evidence_basis or {}, "created_by": row.created_by.value,
            "created_at": row.created_at.isoformat() if row.created_at else None, "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "review": self._review_dict(review) if review else None, "review_history": [self._review_dict(x) for x in include_review_history] if include_review_history is not None else None}

    def _object_summary(self, kind, object_id):
        model_map = {CorrelationObjectType.EVIDENCE: Evidence, CorrelationObjectType.HISTORICAL_CASE: HistoricalCase,
            CorrelationObjectType.HISTORICAL_IMAGE: HistoricalCaseImage, CorrelationObjectType.WEB_RESULT: WebSearchResult,
            CorrelationObjectType.NEWS_RESULT: WebSearchResult, CorrelationObjectType.IMAGE_RESULT: WebSearchResult, CorrelationObjectType.SOURCE: WebSource}
        obj = self.db.get(model_map[kind], object_id)
        if obj is None: return {"id": str(object_id), "type": kind.value, "title": "Record unavailable"}
        if kind == CorrelationObjectType.EVIDENCE:
            return {"id": str(obj.id), "type": kind.value, "title": obj.title}
        if kind == CorrelationObjectType.HISTORICAL_CASE:
            return {"id": str(obj.id), "type": kind.value, "title": obj.title, "external_id": obj.external_id, "source_url": obj.source_url}
        if kind == CorrelationObjectType.HISTORICAL_IMAGE:
            case = self.db.get(HistoricalCase, obj.historical_case_id)
            return {"id": str(obj.id), "type": kind.value, "title": case.title if case else "Historical image", "historical_case_id": str(obj.historical_case_id), "source_url": obj.source_url or obj.image_url}
        if kind in {CorrelationObjectType.WEB_RESULT, CorrelationObjectType.NEWS_RESULT, CorrelationObjectType.IMAGE_RESULT}:
            return {"id": str(obj.id), "type": kind.value, "title": obj.title or obj.source_name or "Untitled research result", "url": obj.url, "snippet": obj.snippet, "source_id": str(obj.source_id) if obj.source_id else None, "research_run_id": str(obj.research_run_id), "search_id": str(obj.search_id)}
        return {"id": str(obj.id), "type": kind.value, "title": obj.title or obj.source_name or obj.domain or obj.url, "url": obj.url, "domain": obj.domain}

    @staticmethod
    def _review_dict(review):
        return {"id": str(review.id), "review_status": review.review_status.value, "note": review.note,
            "created_at": review.created_at.isoformat() if review.created_at else None, "updated_at": review.updated_at.isoformat() if review.updated_at else None}

    @staticmethod
    def _candidate(source_id, source_type, target_id, target_type, correlation_type, score, explanation, signals, basis):
        return {"source_id": source_id, "source_type": source_type, "target_id": target_id, "target_type": target_type,
            "correlation_type": correlation_type, "score": score, "explanation": explanation, "supporting_attributes": signals, "evidence_basis": basis}

    @staticmethod
    def _canonical(source_type, target_type, source_id, target_id):
        order = {kind: index for index, kind in enumerate(CorrelationObjectType)}
        if (order[source_type], str(source_id)) <= (order[target_type], str(target_id)):
            return source_type, source_id, target_type, target_id
        return target_type, target_id, source_type, source_id

    @staticmethod
    def _result_object_type(result_type):
        return {ResultType.WEB: CorrelationObjectType.WEB_RESULT, ResultType.NEWS: CorrelationObjectType.NEWS_RESULT,
            ResultType.IMAGE: CorrelationObjectType.IMAGE_RESULT}[result_type]

    @staticmethod
    def _score(value):
        try:
            score = float(value)
            return score if 0 <= score <= 1 else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _marked_value(item, entity_type):
        for entity in extract_entities(item.title, item.description, item.text_content, metadata=item.metadata_json):
            if entity["type"] == entity_type:
                return entity["value"]
        return None

    @staticmethod
    def _evidence_date(item, context=None):
        metadata = item.metadata_json or {}
        for key in ("date", "event_date", "incident_date"):
            normalized = normalize_date(metadata.get(key))
            if normalized:
                normalized["source_origin"] = "EVIDENCE_METADATA"
                return normalized
        for entity in extract_entities(item.title, item.description, item.text_content, metadata=metadata):
            if entity["type"] == "DATE":
                normalized = normalize_date(entity["value"])
                if normalized:
                    normalized["source_origin"] = "EVIDENCE_TEXT"
                    return normalized
        for entity in extract_entities((context or {}).get("title"), (context or {}).get("description")):
            if entity["type"] == "DATE":
                normalized = normalize_date(entity["value"])
                if normalized:
                    normalized["source_origin"] = "INVESTIGATION_CONTEXT"
                    return normalized
        return None

    @staticmethod
    def _marked_context_value(context, entity_type):
        for entity in extract_entities((context or {}).get("title"), (context or {}).get("description")):
            if entity["type"] == entity_type:
                return entity["value"]
        return None

    @staticmethod
    def _overlaps(left, right):
        matches = []
        for item in left:
            candidates = [other for other in right if other["type"] == item["type"] and CorrelationService._entity_match(item, other)]
            if candidates:
                other = max(candidates, key=lambda value: SequenceMatcher(None, item["normalized_value"], value["normalized_value"]).ratio())
                exact = item["normalized_value"] == other["normalized_value"]
                matches.append({"type": "ENTITY_OVERLAP", "entity_type": item["type"], "normalized_value": item["normalized_value"] if exact else None,
                    "left_value": item["value"], "right_value": other["value"], "match_strength": "EXACT" if exact else "FUZZY_CANDIDATE",
                    "method": "EXACT_NORMALIZED_MATCH" if exact else "FUZZY_STRING_CANDIDATE", "left_source": item.get("source_origin", "EVIDENCE_OR_METADATA"), "requires_verification": True})
        return matches

    @staticmethod
    def _entity_match(left, right):
        if left["type"] != right["type"]:
            return False
        a, b = left["normalized_value"], right["normalized_value"]
        if a == b:
            return True
        if left["type"] in {"PERSON", "CASE_ID"} or min(len(a), len(b)) < 8 or abs(len(a) - len(b)) > 2:
            return False
        return SequenceMatcher(None, a, b).ratio() >= 0.92

    @staticmethod
    def _terms(text):
        stop = {"the", "and", "for", "with", "from", "that", "this", "was", "were", "has", "have", "into", "near", "about", "incident", "case", "evidence", "source", "reported"}
        return {term for term in re.findall(r"[a-z0-9]{4,}", text) if term not in stop}
