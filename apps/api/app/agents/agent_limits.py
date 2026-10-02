from dataclasses import dataclass
from app.config import settings


@dataclass(frozen=True)
class AgentLimits:
    max_iterations: int = settings.agent_max_iterations
    max_actions_per_iteration: int = settings.agent_max_actions_per_iteration
    max_serpapi_queries: int = settings.agent_max_serpapi_queries
    max_results: int = settings.agent_max_results
    max_historical_searches: int = settings.agent_max_historical_searches
    max_image_searches: int = settings.agent_max_image_searches
    max_total_actions: int = settings.agent_max_total_actions
