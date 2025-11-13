import traceback
from typing import Optional, Callable
from queue import PriorityQueue
import random
import time

from infra.llm.models import LLMRequest, LLMResult


def handle_success(
    worker_pool,
    result: LLMResult,
    request: LLMRequest,
    on_result: Optional[Callable]
):
    worker_pool.logger.debug(f"Worker HANDLING SUCCESS: {request.id}")

    with worker_pool.request_tracking_lock:
        if request.id in worker_pool.active_requests:
            worker_pool.active_requests.pop(request.id)

    worker_pool._store_result(result)

    worker_pool.logger.debug(f"Worker STORED RESULT: {request.id}")

    if on_result:
        try:
            on_result(result)
        except Exception as e:
            worker_pool.logger.error(
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
    on_result: Optional[Callable] = None
):
    if result.error_type == '429_rate_limit':
        worker_pool.rate_limiter.record_429(retry_after=result.retry_after)

    request._retry_count += 1

    # Check if we've exceeded max retries - convert to permanent failure
    if request._retry_count >= worker_pool.executor.max_retries:
        worker_pool.logger.error(
            f"✗ {request.id}: Max retries exceeded (attempt {request._retry_count}/{worker_pool.executor.max_retries})",
            request_id=request.id,
            retry_count=request._retry_count,
            max_retries=worker_pool.executor.max_retries,
            error_type=result.error_type,
            error_message=result.error_message,
            execution_time=result.execution_time_seconds
        )

        # Convert to permanent failure instead of infinite retry
        permanent_result = LLMResult(
            request_id=request.id,
            success=False,
            error_type=f"{result.error_type}_max_retries_exceeded",
            error_message=f"Max retries ({worker_pool.executor.max_retries}) exceeded. Last error: {result.error_message}",
            attempts=request._retry_count,
            execution_time_seconds=result.execution_time_seconds,
            request=request
        )
        handle_permanent_failure(worker_pool, permanent_result, request, on_result)
        return

    # Log every retry with full context
    worker_pool.logger.warning(
        f"⟳ {request.id}: Retry attempt {request._retry_count}/{worker_pool.executor.max_retries}",
        request_id=request.id,
        retry_count=request._retry_count,
        max_retries=worker_pool.executor.max_retries,
        error_type=result.error_type,
        error_message=result.error_message,
        execution_time=result.execution_time_seconds
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


def handle_permanent_failure(
    worker_pool,
    result: LLMResult,
    request: LLMRequest,
    on_result: Optional[Callable]
):
    # Remove from active requests tracking
    if request and hasattr(request, 'id'):
        with worker_pool.request_tracking_lock:
            if request.id in worker_pool.active_requests:
                worker_pool.active_requests.pop(request.id)

    # Always store result (contains error info)
    worker_pool._store_result(result)

    # Call result handler with additional error protection
    if on_result:
        try:
            on_result(result)
        except Exception as e:
            request_id = request.id if request and hasattr(request, 'id') else result.request_id
            worker_pool.logger.error(
                f"Result handler failed for {request_id} (original error: {result.error_type}): {type(e).__name__}: {e}",
                request_id=request_id,
                error_type=type(e).__name__,
                error_message=str(e),
                original_error_type=result.error_type
            )


def handle_worker_crash(
    worker_pool,
    error: Exception,
    request: Optional[LLMRequest],
    on_result: Optional[Callable]
):
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

        if on_result:
            try:
                on_result(failure_result)
            except Exception as e:
                worker_pool.logger.error(f"Result handler failed during worker crash for {request.id}: {type(e).__name__}: {e}")

    worker_pool.logger.debug(
        f"CRITICAL: Worker thread crashed with unexpected error",
        error=str(error),
        error_type=type(error).__name__,
        request_id=request.id if request and hasattr(request, 'id') else None,
        traceback=error_detail
    )
