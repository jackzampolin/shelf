from typing import List, Dict, Optional, Any
from pathlib import Path
from dataclasses import dataclass


@dataclass
class AgentResult:
    success: bool
    iterations: int
    total_cost_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_reasoning_tokens: int
    execution_time_seconds: float
    final_messages: List[Dict]
    run_log_path: Optional[Path] = None
    error_message: Optional[str] = None


@dataclass
class AgentEvent:
    event_type: str
    iteration: int
    timestamp: float
    data: Dict[str, Any]
