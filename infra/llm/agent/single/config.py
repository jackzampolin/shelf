from dataclasses import dataclass
from typing import List, Dict, Optional, Any

from ..tools import AgentTools


@dataclass
class AgentConfig:
    model: str
    initial_messages: List[Dict]
    tools: AgentTools
    stage_storage: any
    agent_id: str
    images: Optional[List[Any]] = None  # Images to include in initial message
    max_iterations: int = 15
    temperature: float = 0.0
    max_tokens: Optional[int] = None
