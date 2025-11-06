from dataclasses import dataclass
from typing import List

from .schemas import AgentResult


@dataclass
class AgentBatchResult:
    results: List[AgentResult]
    total_agents: int
    successful: int
    failed: int
    total_cost_usd: float
    total_time_seconds: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_reasoning_tokens: int
    avg_iterations: float
    avg_cost_per_agent: float
    avg_time_per_agent: float
