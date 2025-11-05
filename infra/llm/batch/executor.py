#!/usr/bin/env python3
"""
Single request execution with error handling and retries.

Handles:
- Model fallback routing
- Request execution via streaming
- JSON parsing and validation
- Error classification (retryable vs permanent)
- Result telemetry
"""

import time
import json
import logging
from typing import Optional, Callable

from infra.llm.models import LLMRequest, LLMResult, LLMEvent, EventData
from .streaming import StreamingExecutor

logger = logging.getLogger(__name__)


class RequestExecutor:
    """
    Executes single LLM requests with telemetry and error handling.

    Provides:
    - Model fallback routing via ModelRouter
    - Error classification and retry logic
    - Comprehensive telemetry (queue time, execution time, TTFT, cost)
    - JSON parsing and validation

    All requests are streamed for full telemetry.
    """

    def __init__(
        self,
        streaming_executor: StreamingExecutor,
        max_retries: int = 5
    ):
        """
        Initialize request executor.

        Args:
            streaming_executor: StreamingExecutor for making API calls
            max_retries: Maximum retry attempts per request
        """
        self.streaming_executor = streaming_executor
        self.max_retries = max_retries

    def execute_request(
        self,
        request: LLMRequest,
        on_event: Optional[Callable[[EventData], None]] = None
    ) -> LLMResult:
        """
        Execute single LLM request with telemetry.

        All requests are streamed for full telemetry (TTFT, tokens/sec, progress).
        All requests must have response_format for structured JSON output.

        Manages:
        - Model fallback routing via ModelRouter
        - Error classification and retry logic
        - Comprehensive telemetry (queue time, execution time, TTFT, cost)

        Args:
            request: LLM request to execute
            on_event: Event callback for lifecycle events

        Returns:
            LLMResult with success/failure status and telemetry
        """
        start_time = time.time()
        queue_time = start_time - request._queued_at

        try:
            # Initialize router if fallback models configured
            if not hasattr(request, '_router') or request._router is None:
                if request.fallback_models:
                    from infra.llm.router import ModelRouter
                    request._router = ModelRouter(
                        primary_model=request.model,
                        fallback_models=request.fallback_models
                    )

            # Get current model from router (or use request.model if no router)
            current_model = request._router.get_current() if request._router else request.model

            # Stream the request
            response_text, usage, cost, ttft = self.streaming_executor.execute_streaming_request(
                request, current_model, on_event, start_time
            )

            # Parse structured JSON response (OpenRouter guarantees valid JSON)
            parsed_json = json.loads(response_text)

            # Mark success in router if present
            if request._router:
                request._router.mark_success()

            # Build success result
            execution_time = time.time() - start_time

            # Calculate tokens per second
            tokens_per_second = 0.0
            completion_tokens = usage.get('completion_tokens', 0)
            if execution_time > 0 and completion_tokens > 0:
                tokens_per_second = completion_tokens / execution_time

            # Extract provider from model name (e.g., "anthropic/claude-sonnet-4" → "anthropic")
            provider = None
            if '/' in current_model:
                provider = current_model.split('/')[0]

            return LLMResult(
                request_id=request.id,
                success=True,
                response=response_text,
                parsed_json=parsed_json,
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                ttft_seconds=ttft,
                tokens_received=completion_tokens,
                tokens_per_second=tokens_per_second,
                usage=usage,
                cost_usd=cost,
                provider=provider,
                model_used=current_model,
                models_attempted=request._router.get_models_attempted() if request._router else [request.model],
                request=request
            )

        except json.JSONDecodeError as e:
            # JSON parsing failed - this should never happen with structured responses
            # Only log as warning if this is the final attempt
            will_retry = request._retry_count < self.max_retries
            log_level = logging.DEBUG if will_retry else logging.WARNING
            log_message = f"Structured JSON parsing failed for {request.id}"
            if will_retry:
                log_message += f" (will retry, attempt {request._retry_count + 1}/{self.max_retries})"
            else:
                log_message += f" (final attempt, giving up)"

            # Truncate response for logging
            response_preview = response_text
            if len(response_text) > 1000:
                response_preview = f"{response_text[:500]}...{response_text[-500:]}"

            logger.log(
                log_level,
                log_message,
                extra={
                    'request_id': request.id,
                    'model': current_model,
                    'error': str(e),
                    'response_length': len(response_text),
                    'response_preview': response_preview,
                    'response_format': request.response_format,
                    'attempt': request._retry_count + 1,
                    'max_retries': self.max_retries
                }
            )

            execution_time = time.time() - start_time
            return LLMResult(
                request_id=request.id,
                success=False,
                error_type="json_parse",
                error_message=f"Structured JSON parsing failed: {str(e)}",
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                request=request
            )

        except Exception as e:
            # Other errors (timeout, HTTP, etc.)
            execution_time = time.time() - start_time
            error_type = self.classify_error(e)

            return LLMResult(
                request_id=request.id,
                success=False,
                error_type=error_type,
                error_message=str(e),
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                request=request
            )

    @staticmethod
    def classify_error(error: Exception) -> str:
        """
        Classify error type for retry logic and error handling.

        Error types (in priority order):
        - 'timeout': Network timeouts (retryable)
        - '5xx': Server errors 500-599 (retryable)
        - '429_rate_limit': Rate limiting (retryable with backoff)
        - '413_payload_too_large': Payload too large (retryable - may succeed on retry)
        - '422_unprocessable': Unprocessable entity (retryable - often transient deserialization issues)
        - '4xx': Other client errors 400-499 (non-retryable)
        - 'unknown': Unclassified errors (retryable to be safe)

        Args:
            error: Exception raised during LLM request

        Returns:
            String error type for use in retry logic
        """
        error_str = str(error).lower()
        if 'timeout' in error_str:
            return 'timeout'
        elif '5' in error_str and ('server' in error_str or 'error' in error_str):
            return '5xx'
        elif '429' in error_str:
            return '429_rate_limit'
        elif '413' in error_str:
            return '413_payload_too_large'
        elif '422' in error_str:
            return '422_unprocessable'
        elif '4' in error_str and ('client' in error_str or 'error' in error_str):
            return '4xx'
        else:
            return 'unknown'

    @staticmethod
    def is_retryable(error_type: Optional[str]) -> bool:
        """
        Check if error type is retryable.

        Retryable errors (retry indefinitely):
        - timeout: Network timeouts
        - 5xx: Server errors (transient)
        - 429_rate_limit: Rate limiting (will retry after wait)
        - 413_payload_too_large: Payload too large (retry - may succeed on different attempt)
        - 422_unprocessable: Provider deserialization issues (transient)
        - json_parse: JSON parsing failures (fallback models may generate valid JSON)
        - unknown: Unclassified errors (retry to be safe)

        Non-retryable errors:
        - 4xx: Client errors (bad request, auth, forbidden, etc.)

        Args:
            error_type: Error type from classify_error()

        Returns:
            True if error should be retried
        """
        retryable = [
            'timeout',
            '5xx',
            '429_rate_limit',
            '413_payload_too_large',
            '422_unprocessable',
            'json_parse',
            'unknown'
        ]
        return error_type in retryable
