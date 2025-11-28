from dataclasses import dataclass
from typing import List, Dict, Optional, Any
from infra.pipeline.status import PhaseStatusTracker
from ..tools import AgentTools

@dataclass
class AgentConfig:
    # Required fields (no defaults) must come first
    tracker: PhaseStatusTracker
    agent_id: str
    model: str
    tools: AgentTools
    initial_messages: List[Dict]

    # Optional fields (with defaults) come after
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    images: Optional[List[Any]] = None
    max_iterations: int = 15
    timeout: int = 300  # Per-request timeout in seconds
