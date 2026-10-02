from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.agent_models import ActionType, AgentActionSpec, AgentRunRequest
from app.agents.agent_planner import DeterministicAgentPlanner
from app.agents.agent_state import InvestigationAgentState


def test_run_objective_is_trimmed_and_blank_is_rejected():
    assert AgentRunRequest(objective="  Find   related cases ").objective == "Find related cases"
    with pytest.raises(ValidationError):
        AgentRunRequest(objective="  \n ")


def test_public_search_requires_a_bounded_nonempty_query():
    with pytest.raises(ValidationError):
        AgentActionSpec(action=ActionType.SEARCH_WEB, query="  ")
    with pytest.raises(ValidationError):
        AgentActionSpec(action=ActionType.SEARCH_NEWS)
    query = AgentActionSpec(action=ActionType.SEARCH_WEB, query="  coastal   warehouse ")
    assert query.query == "coastal warehouse"


def test_planner_loads_context_before_searching():
    state = InvestigationAgentState(investigation_id=uuid4(), objective="Find related cases")
    plan = DeterministicAgentPlanner().plan(state, action_limit=3)
    assert [item.action for item in plan] == [
        ActionType.GET_INVESTIGATION,
        ActionType.GET_EVIDENCE,
        ActionType.GET_RESEARCH_HISTORY,
    ]


def test_planner_bounds_follow_up_to_available_evidence_and_budget():
    text_id, image_id = str(uuid4()), str(uuid4())
    state = InvestigationAgentState(
        investigation_id=uuid4(),
        objective="Find related cases",
        completed_actions=["GET_INVESTIGATION", "GET_EVIDENCE", "GET_RESEARCH_HISTORY"],
        investigation={"title": "Warehouse incident"},
        evidence=[
            {"id": text_id, "type": "TEXT", "text_content": "coastal warehouse incident"},
            {"id": image_id, "type": "IMAGE", "text_content": ""},
        ],
        max_historical_searches=1,
        max_image_searches=1,
        max_serpapi_queries=2,
    )

    plan = DeterministicAgentPlanner().plan(state, action_limit=3)
    assert len(plan) == 3
    assert [item.action for item in plan] == [
        ActionType.SEARCH_HISTORICAL_TEXT,
        ActionType.SEARCH_HISTORICAL_IMAGES,
        ActionType.SEARCH_WEB,
    ]
    assert "Find related cases" in plan[2].query
    assert "coastal warehouse incident" in plan[2].query
    assert all(item.action not in {ActionType.SEARCH_NEWS, ActionType.SEARCH_IMAGES} for item in plan)


def test_planner_returns_no_public_search_when_budget_is_exhausted():
    state = InvestigationAgentState(
        investigation_id=uuid4(), objective="Research", completed_actions=[
            "GET_INVESTIGATION", "GET_EVIDENCE", "GET_RESEARCH_HISTORY"
        ], investigation={"title": "Warehouse incident"}, max_serpapi_queries=0,
    )
    assert DeterministicAgentPlanner().plan(state, action_limit=3) == []
