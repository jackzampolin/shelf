#!/usr/bin/env python3
"""Result handlers for worker pool.

Handles success, retry, permanent failure, and worker crash scenarios.
Each function receives the worker pool instance and delegates to its state.
"""
import sys
import traceback
from typing import Optional, Callable
from queue import PriorityQueue
import random
import time

from infra.llm.models import LLMRequest, LLMResult, LLMEvent


def handle_success(
    worker_pool,
    result: LLMResult,
    request: LLMRequest,
    on_event: Optional[Callable],
    on_result: Optional[Callable]
):
    """Handle successful request completion."""
    worker_pool.logger.debug(f"Worker HANDLING SUCCESS: {request.id}")

    with worker_pool.request_tracking_lock:
        if request.id in worker_pool.active_requests:
            worker_pool.active_requests.pop(request.id)

    worker_pool._emit_event(on_event, LLMEvent.COMPLETED, request_id=request.id)
    worker_pool._store_result(result)

    worker_pool.logger.debug(f"Worker STORED RESULT: {request.id}")

    if on_result:
        try:
            on_result(result)
        except Exception as e:
            # Page may not have been saved despite successful LLM response
            worker_pool.logger.debug(
                f"Result handler failed for {request.id}: {type(e).__name__}: {e}",
                request_id=request.id,
                error_type=type(e).__name__,
                error_message=str(e)
            )


def handle_retry(
    worker_pool,
    result: LLMResult,
    request: LLMRequest,
    queue: PriorityQueue,
    on_event: Optional[Callable]
):
    """Handle retryable failure - re-queue the request."""
    # Record 429 rate limit in rate limiter
    if result.error_type == '429_rate_limit':
        worker_pool.rate_limiter.record_429(retry_after=result.retry_after)

    request._retry_count += 1

    # Only log when exceeding max_retries (infinite retry warning)
    if request._retry_count >= worker_pool.executor.max_retries:
        worker_pool.logger.warning(
            f"Retrying {request.id}: attempt {request._retry_count} (EXCEEDS max_retries={worker_pool.executor.max_retries}, infinite retry!)",
            request_id=request.id,
            retry_count=request._retry_count,
            max_retries=worker_pool.executor.max_retries,
            error_type=result.error_type,
            error_message=result.error_message
        )

    jitter = random.uniform(*worker_pool.retry_jitter)
    time.sleep(jitter)
    queue.put(request)

    with worker_pool.request_tracking_lock:
        if request.id in worker_pool.active_requests:
            from ..schemas import RequestPhase
            status = worker_pool.active_requests[request.id]
            status.phase = RequestPhase.QUEUED
            status.phase_entered_at = time.time()
            status.retry_count = request._retry_count

    worker_pool._emit_event(
        on_event,
        LLMEvent.RETRY_QUEUED,
        request_id=request.id,
        retry_count=request._retry_count,
        queue_position=queue.qsize()
    )


def handle_permanent_failure(
    worker_pool,
    result: LLMResult,
    request: LLMRequest,
    on_event: Optional[Callable],
    on_result: Optional[Callable]
):
    """Handle non-retryable failure - store failed result."""
    with worker_pool.request_tracking_lock:
        if request.id in worker_pool.active_requests:
            worker_pool.active_requests.pop(request.id)

    worker_pool._emit_event(on_event, LLMEvent.FAILED, request_id=request.id)
    worker_pool._store_result(result)
    if on_result:
        try:
            on_result(result)
        except Exception as e:
            worker_pool.logger.debug(
                f"Result handler failed for {request.id} (original error: {result.error_type}): {type(e).__name__}: {e}",
                request_id=request.id,
                error_type=type(e).__name__,
                error_message=str(e),
                original_error_type=result.error_type
            )


def handle_worker_crash(
    worker_pool,
    error: Exception,
    request: Optional[LLMRequest],
    on_event: Optional[Callable],
    on_result: Optional[Callable]
):
    """Handle unexpected worker thread crash."""
    error_detail = traceback.format_exc()

    if request and hasattr(request, 'id'):
        failure_result = LLMResult(
            request_id=request.id,
            success=False,
            error_type="worker_exception",
            error_message=f"Worker thread exception: {type(error).__name__}: {str(error)}",
            request=request
        )

        worker_pool._store_result(failure_result)

        try:
            worker_pool._emit_event(on_event, LLMEvent.FAILED, request_id=request.id)
        except Exception as e:
            worker_pool.logger.debug(f"Failed to emit FAILED event during worker crash: {e}")

        if on_result:
            try:
                on_result(failure_result)
            except Exception as e:
                worker_pool.logger.debug(f"Result handler failed during worker crash for {request.id}: {type(e).__name__}: {e}")

    worker_pool.logger.debug(
        f"CRITICAL: Worker thread crashed with unexpected error",
        error=str(error),
        error_type=type(error).__name__,
        request_id=request.id if request and hasattr(request, 'id') else None,
        traceback=error_detail
    )
