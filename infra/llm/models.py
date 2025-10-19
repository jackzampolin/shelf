#!/usr/bin/env python3
"""
Data models for LLM batch processing.

Defines request/result containers and event types for the batch client.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import time


class LLMEvent(str, Enum):
    """Event types for LLM request lifecycle."""
    QUEUED = "queued"              # Request added to queue
    RATE_LIMITED = "rate_limited"  # Waiting for rate limit
    DEQUEUED = "dequeued"          # Picked up by worker
    EXECUTING = "executing"        # LLM call started
    STREAMING = "streaming"        # Tokens arriving (periodic)
    RETRY_QUEUED = "retry_queued"  # Failed, re-enqueued
    COMPLETED = "completed"        # Success
    FAILED = "failed"              # Permanent failure (max retries)
    PROGRESS = "progress"          # Batch-level aggregate (periodic)


@dataclass
class LLMRequest:
    """
    Container for a single LLM API request.

    Attributes:
        id: User-defined identifier (e.g., "page_042")
        model: OpenRouter model name (e.g., "anthropic/claude-sonnet-4")
        messages: List of message dicts with 'role' and 'content'
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens to generate (None = no limit)
        timeout: Request timeout in seconds
        images: Optional list of images for vision models (bytes, paths, or PIL Images)
        response_format: Optional structured output schema
        metadata: User-defined metadata (carried through to result)
        provider_order: Optional list of provider names to try in order
        provider_sort: Optional sort strategy ("price", "throughput", "latency")
        allow_fallbacks: Whether to allow provider fallbacks
        fallback_models: Optional list of fallback models to try if primary fails
        priority: Queue priority (higher = processed first, default: 0)
    """
    id: str
    model: str
    messages: List[Dict[str, str]]
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    timeout: int = 120
    images: Optional[List[Any]] = None
    response_format: Optional[Dict] = None
    metadata: Dict = field(default_factory=dict)

    # Provider routing
    provider_order: Optional[List[str]] = None
    provider_sort: Optional[str] = None
    allow_fallbacks: bool = True

    # Model fallback routing
    fallback_models: Optional[List[str]] = None

    # Queue management
    priority: int = 0

    # Internal tracking (managed by client)
    _retry_count: int = field(default=0, repr=False)
    _queued_at: float = field(default=0.0, repr=False)
    _router: Optional[Any] = field(default=None, repr=False)  # ModelRouter instance

    def __lt__(self, other):
        """Support priority queue ordering (higher priority first, then FIFO)."""
        if self.priority != other.priority:
            return self.priority > other.priority  # Higher priority first
        return self._queued_at < other._queued_at  # FIFO within same priority


@dataclass
class LLMResult:
    """
    Container for LLM API response with telemetry.

    Attributes:
        request_id: ID from the original request
        success: Whether request succeeded
        response: Raw response text (if successful)
        parsed_json: Parsed JSON response (if json_parser provided)

        # Telemetry
        attempts: Number of attempts (including retries)
        total_time_seconds: Total time from queue to completion
        queue_time_seconds: Time spent waiting in queue
        execution_time_seconds: Time spent in LLM call
        tokens_received: Number of tokens in response
        tokens_per_second: Token generation rate (for streaming)

        # Cost & Usage
        usage: Token usage dict from API (prompt_tokens, completion_tokens)
        cost_usd: Estimated cost in USD

        # Error details (if failed)
        error_type: Error category (timeout, json_parse, 5xx, 4xx)
        error_message: Human-readable error message

        # Provider info
        provider: Provider that handled request (if available)
        model_used: Actual model used (may differ from requested)
        models_attempted: All models tried during fallback attempts

        # Original request
        request: Reference to original LLMRequest
    """
    request_id: str
    success: bool
    response: Optional[str] = None
    parsed_json: Optional[Dict] = None

    # Telemetry
    attempts: int = 0
    total_time_seconds: float = 0.0
    queue_time_seconds: float = 0.0
    execution_time_seconds: float = 0.0
    tokens_received: int = 0
    tokens_per_second: float = 0.0

    # Cost & Usage
    usage: Dict = field(default_factory=dict)
    cost_usd: float = 0.0

    # Error details
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    # Provider info
    provider: Optional[str] = None
    model_used: Optional[str] = None
    models_attempted: Optional[List[str]] = None  # All models tried (for fallback tracking)

    # Original request (for metadata access)
    request: Optional['LLMRequest'] = field(default=None, repr=False)


@dataclass
class EventData:
    """
    Event payload for lifecycle and progress events.

    Attributes:
        event_type: Type of event (from LLMEvent enum)
        request_id: ID of request (None for batch-level events)
        timestamp: Event timestamp (seconds since epoch)

        # Per-request details (for request-level events)
        retry_count: Current retry count
        queue_position: Position in queue (for QUEUED events)
        tokens_received: Tokens received so far (for STREAMING events)
        tokens_per_second: Token generation rate
        eta_seconds: Estimated time to completion
        stage: Pipeline stage name (e.g., "correction", "label")
        message: Pre-formatted display message for progress bar

        # Batch-level details (for PROGRESS events)
        completed: Number of completed requests
        failed: Number of failed requests
        in_flight: Number of requests currently executing
        queued: Number of requests waiting in queue
        total_cost_usd: Total cost so far
        rate_limit_status: Current rate limit state
    """
    event_type: LLMEvent
    request_id: Optional[str] = None
    timestamp: float = 0.0

    # Per-request details
    retry_count: int = 0
    queue_position: Optional[int] = None
    tokens_received: int = 0
    tokens_per_second: float = 0.0
    eta_seconds: Optional[float] = None
    stage: Optional[str] = None
    message: Optional[str] = None

    # Batch-level details
    completed: int = 0
    failed: int = 0
    in_flight: int = 0
    queued: int = 0
    total_cost_usd: float = 0.0
    rate_limit_status: Optional[Dict] = None


class RequestPhase(str, Enum):
    """Request lifecycle phases for tracking."""
    QUEUED = "queued"
    RATE_LIMITED = "rate_limited"
    DEQUEUED = "dequeued"
    EXECUTING = "executing"
    # Terminal states (move to recent_completions)
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class RequestStatus:
    """
    Real-time status for an active request.

    Lifecycle: QUEUED → RATE_LIMITED → DEQUEUED → EXECUTING → [COMPLETED/FAILED]
    """
    request_id: str
    phase: RequestPhase

    # Timestamps
    queued_at: float          # When first queued
    phase_entered_at: float   # When entered current phase

    # Retry tracking
    retry_count: int = 0

    # Phase-specific data
    rate_limit_eta: Optional[float] = None  # For RATE_LIMITED phase

    @property
    def total_elapsed(self) -> float:
        """Total time since queued."""
        return time.time() - self.queued_at

    @property
    def phase_elapsed(self) -> float:
        """Time in current phase."""
        return time.time() - self.phase_entered_at


@dataclass
class CompletedStatus:
    """
    Status for recently completed/failed request (kept for TTL).
    """
    request_id: str
    success: bool

    # Timing
    total_time_seconds: float

    # Cost (if successful)
    cost_usd: float = 0.0

    # Error (if failed)
    error_message: Optional[str] = None

    # Retry tracking
    retry_count: int = 0
    model_used: Optional[str] = None

    # TTL management
    cycles_remaining: int = 6  # Decremented each PROGRESS event


@dataclass
class BatchStats:
    """
    Aggregate statistics for the entire batch.
    """
    # Counts
    total_requests: int
    completed: int
    failed: int
    in_progress: int
    queued: int

    # Timing
    avg_time_per_request: float
    min_time: float
    max_time: float

    # Cost
    total_cost_usd: float
    avg_cost_per_request: float

    # Throughput
    requests_per_second: float

    # Rate limiting
    rate_limit_utilization: float
    rate_limit_tokens_available: int
