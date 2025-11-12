#!/usr/bin/env python3
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class LLMRequest:
    id: str
    messages: List[Dict[str, str]]
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    timeout: int = 120  # Default for stages that don't set custom timeout
    images: Optional[List[Any]] = None
    response_format: Optional[Dict] = None

    _retry_count: int = field(default=0, repr=False)
    _queued_at: float = field(default=0.0, repr=False)

    def __lt__(self, other):
        return self._queued_at < other._queued_at


@dataclass
class LLMResult:
    request_id: str
    success: bool
    response: Optional[str] = None
    parsed_json: Optional[Dict] = None

    attempts: int = 0
    total_time_seconds: float = 0.0
    queue_time_seconds: float = 0.0
    execution_time_seconds: float = 0.0

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0

    error_type: Optional[str] = None
    error_message: Optional[str] = None
    retry_after: Optional[int] = None

    provider: Optional[str] = None
    model_used: Optional[str] = None

    tool_calls: Optional[List[Dict]] = None
    reasoning_details: Optional[List[Dict]] = None

    request: Optional['LLMRequest'] = field(default=None, repr=False)

    def record_to_metrics(
        self,
        metrics_manager,
        key: str,
        extra_fields: Optional[Dict[str, Any]] = None,
        accumulate: bool = False
    ):
        custom_metrics = {
            "attempts": self.attempts,
            "model_used": self.model_used,
            "queue_time_seconds": self.queue_time_seconds,
            "execution_time_seconds": self.execution_time_seconds,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }

        if extra_fields:
            custom_metrics.update(extra_fields)

        metrics_manager.record(
            key=key,
            cost_usd=self.cost_usd,
            time_seconds=self.total_time_seconds,
            custom_metrics=custom_metrics,
            accumulate=accumulate
        )
