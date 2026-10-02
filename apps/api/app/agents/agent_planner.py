from app.agents.agent_models import ActionType, AgentActionSpec
from app.agents.agent_state import InvestigationAgentState


class DeterministicAgentPlanner:
    """Small deterministic planner. Reasons are user-facing summaries, not private reasoning."""

    def plan(self, state: InvestigationAgentState, action_limit: int) -> list[AgentActionSpec]:
        seen = set(state.completed_actions)
        initial = [
                AgentActionSpec(action=ActionType.GET_INVESTIGATION, reason="Load investigation title and case metadata."),
                AgentActionSpec(action=ActionType.GET_EVIDENCE, reason="Review evidence available to this investigation."),
                AgentActionSpec(action=ActionType.GET_RESEARCH_HISTORY, reason="Check prior research to avoid repeating searches."),
            ]
        pending_initial = [item for item in initial if item.action.value not in seen]
        if pending_initial:
            return pending_initial[:action_limit]

        candidates: list[AgentActionSpec] = []
        text_ids = [item["id"] for item in state.evidence if item.get("text_content", "").strip()]
        image_ids = [item["id"] for item in state.evidence if item.get("type") == "IMAGE"]
        if text_ids and state.historical_searches_used < state.max_historical_searches:
            candidates.append(AgentActionSpec(action=ActionType.SEARCH_HISTORICAL_TEXT, reason="Compare investigator-provided text with the historical case index.", evidence_ids=text_ids[:20]))
        if image_ids and state.image_searches_used < state.max_image_searches:
            candidates.append(AgentActionSpec(action=ActionType.SEARCH_HISTORICAL_IMAGES, reason="Retrieve visually similar historical images for investigator review.", evidence_ids=image_ids[:20]))

        seed = next((item.get("text_content", "").strip() for item in state.evidence if item.get("text_content", "").strip()), "")
        evidence_ids = [item["id"] for item in state.evidence if item.get("text_content", "").strip() or item.get("title") or item.get("description")][:20]
        if not seed:
            seed = next((" ".join((item.get("title", ""), item.get("description", ""), item.get("filename") or "")).strip() for item in state.evidence if item.get("title") or item.get("description") or item.get("filename")), "")
        if not seed:
            seed = state.investigation.get("title", "").strip()
            evidence_ids = []
        seed = " ".join(f"{state.objective} {seed}".split())[:450]
        if seed and state.serpapi_queries_used < state.max_serpapi_queries:
            if ActionType.SEARCH_WEB.value not in seen:
                candidates.append(AgentActionSpec(action=ActionType.SEARCH_WEB, query=seed, reason="Search public web sources using the documented investigation or evidence text.", evidence_ids=evidence_ids))
            if ActionType.SEARCH_NEWS.value not in seen:
                candidates.append(AgentActionSpec(action=ActionType.SEARCH_NEWS, query=f"{seed} news"[:500], reason="Search news coverage using the documented investigation or evidence text.", evidence_ids=evidence_ids))
            if any(item.get("type") == "IMAGE" for item in state.evidence) and ActionType.SEARCH_IMAGES.value not in seen:
                candidates.append(AgentActionSpec(action=ActionType.SEARCH_IMAGES, query=seed, reason="Search public images using the documented case context.", evidence_ids=evidence_ids))
        return candidates[:action_limit]
