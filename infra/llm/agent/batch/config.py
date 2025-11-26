from dataclasses import dataclass
from typing import List
from infra.pipeline.status import PhaseStatusTracker

from ..single import AgentConfig


@dataclass
class AgentBatchConfig:
    tracker: PhaseStatusTracker
    agent_configs: List[AgentConfig]
    batch_name: str = "agent-batch"
    max_workers: int = 10
