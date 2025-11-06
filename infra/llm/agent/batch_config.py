from dataclasses import dataclass
from typing import List

from .config import AgentConfig


@dataclass
class AgentBatchConfig:
    agent_configs: List[AgentConfig]
    max_workers: int = 10
    max_visible_agents: int = 10
    completed_agent_display_seconds: float = 5.0
