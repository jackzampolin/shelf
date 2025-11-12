from dataclasses import dataclass
from typing import Optional

from .request_phase import RequestPhase

@dataclass
class RequestStatus:
    request_id: str
    phase: RequestPhase
    queued_at: float
    phase_entered_at: float
    retry_count: int = 0
    rate_limit_eta: Optional[float] = None
