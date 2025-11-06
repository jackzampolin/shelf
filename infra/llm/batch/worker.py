#!/usr/bin/env python3
import logging
import time
import random
import threading
import sys
import traceback
from queue import PriorityQueue, Empty
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Callable, Dict, Set

from infra.llm.models import LLMRequest, LLMResult, LLMEvent, EventData
from .schemas import RequestPhase, RequestStatus
from infra.llm.rate_limiter import RateLimiter
from .executor import RequestExecutor

logger = logging.getLogger(__name__)


class WorkerPool:
    def __init__(
        self,
        executor: RequestExecutor,
        rate_limiter: RateLimiter,
        max_workers: int,
        logger=None,
        retry_jitter: tuple = (1.0, 3.0),
        progress_interval: float = 1.0,
    ):
        self.executor = executor
        self.rate_limiter = rate_limiter
        self.max_workers = max_workers
        self.logger = logger
        self.retry_jitter = retry_jitter
        self.progress_interval = progress_interval

        self.results: Dict[str, LLMResult] = {}
        self.results_lock = threading.Lock()

        self.request_tracking_lock = threading.Lock()
        self.active_requests: Dict[str, RequestStatus] = {}

    def process_batch(
        self,
        requests: list,
        on_event: Optional[Callable[[EventData], None]] = None,
        on_result: Optional[Callable[[LLMResult], None]] = None
    ) -> Dict[str, LLMResult]:
        if not requests:
            return {}

        queue = PriorityQueue()

        for req in requests:
            req._queued_at = time.time()
            queue.put(req)

            with self.request_tracking_lock:
                self.active_requests[req.id] = RequestStatus(
                    request_id=req.id,
                    phase=RequestPhase.QUEUED,
                    queued_at=req._queued_at,
                    phase_entered_at=req._queued_at,
                    retry_count=0
                )

            self._emit_event(on_event, LLMEvent.QUEUED, request_id=req.id)

        expected_ids = {req.id for req in requests}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for _ in range(min(self.max_workers, len(requests))):
                future = executor.submit(
                    self._worker_loop,
                    queue,
                    on_event,
                    on_result,
                    expected_ids
                )
                futures.append(future)

            for future in futures:
                future.result()

        with self.results_lock:
            return self.results.copy()

    def _worker_loop(
        self,
        queue: PriorityQueue,
        on_event: Optional[Callable[[EventData], None]],
        on_result: Optional[Callable[[LLMResult], None]],
        expected_ids: Set[str]
    ):
        worker_id = threading.current_thread().name
        if self.logger:
            self.logger.debug(f"Worker {worker_id} started")

        while True:
            try:
                if self._all_done(expected_ids):
                    if self.logger:
                        self.logger.debug(f"Worker {worker_id} exiting (all done)")
                    break

                request = self._get_next_request(queue, expected_ids)
                if request is None:
                    continue

                if not self._check_rate_limit(request, queue, on_event):
                    continue

                self.rate_limiter.consume()
                if self.logger:
                    self.logger.debug(f"Worker {worker_id} executing {request.id}")

                self._update_request_phase(request.id, RequestPhase.DEQUEUED)

                self._emit_event(on_event, LLMEvent.DEQUEUED, request_id=request.id)
                self._emit_event(on_event, LLMEvent.EXECUTING, request_id=request.id)
                result = self.executor.execute_request(request, on_event)

                if self.logger:
                    if result.success:
                        self.logger.debug(f"Worker {worker_id} ✓ {request.id} ({result.execution_time_seconds:.1f}s)")
                    else:
                        self.logger.debug(
                            f"Worker {worker_id} ✗ {request.id} ({result.execution_time_seconds:.1f}s)",
                            error_type=result.error_type,
                            error=result.error_message
                        )

                self._handle_result(result, request, queue, on_event, on_result)

            except Exception as e:
                self._handle_worker_crash(e, request if 'request' in locals() else None, on_event, on_result)
                continue  # Keep worker alive

    def _all_done(self, expected_ids: Set[str]) -> bool:
        with self.results_lock:
            return len(self.results) >= len(expected_ids)

    def _get_next_request(
        self,
        queue: PriorityQueue,
        expected_ids: Set[str]
    ) -> Optional[LLMRequest]:
        try:
            return queue.get(timeout=0.5)
        except Empty:
            if self._all_done(expected_ids):
                return None
            return None

    def _check_rate_limit(
        self,
        request: LLMRequest,
        queue: PriorityQueue,
        on_event: Optional[Callable]
    ) -> bool:
        if not self.rate_limiter.can_execute():
            wait_time = self.rate_limiter.time_until_token()

            # Ensure we wait at least a minimum time to avoid tight loops
            # This handles cases where time_until_token() returns very small values
            min_wait = 0.1  # 100ms minimum
            actual_wait = max(wait_time, min_wait)

            with self.request_tracking_lock:
                if request.id in self.active_requests:
                    status = self.active_requests[request.id]
                    status.phase = RequestPhase.RATE_LIMITED
                    status.phase_entered_at = time.time()
                    status.rate_limit_eta = actual_wait

            self._emit_event(
                on_event,
                LLMEvent.RATE_LIMITED,
                request_id=request.id,
                eta_seconds=actual_wait
            )
            # Sleep full wait_time (no busy-wait loop)
            time.sleep(actual_wait)
            queue.put(request)
            return False

        return True

    def _update_request_phase(self, request_id: str, phase: RequestPhase):
        with self.request_tracking_lock:
            if request_id in self.active_requests:
                status = self.active_requests[request_id]
                status.phase = phase
                status.phase_entered_at = time.time()

    def _handle_result(
        self,
        result: LLMResult,
        request: LLMRequest,
        queue: PriorityQueue,
        on_event: Optional[Callable],
        on_result: Optional[Callable]
    ):

        if result.success:
            self._handle_success(result, request, on_event, on_result)
        elif self.executor.is_retryable(result.error_type):
            self._handle_retry(result, request, queue, on_event)
        else:
            self._handle_permanent_failure(result, request, on_event, on_result)

    def _handle_success(
        self,
        result: LLMResult,
        request: LLMRequest,
        on_event: Optional[Callable],
        on_result: Optional[Callable]
    ):
        with self.request_tracking_lock:
            if request.id in self.active_requests:
                self.active_requests.pop(request.id)

        self._emit_event(on_event, LLMEvent.COMPLETED, request_id=request.id)
        self._store_result(result)
        if on_result:
            on_result(result)

    def _handle_retry(
        self,
        result: LLMResult,
        request: LLMRequest,
        queue: PriorityQueue,
        on_event: Optional[Callable]
    ):
        # Record 429 rate limit in rate limiter
        if result.error_type == '429_rate_limit':
            self.rate_limiter.record_429(retry_after=result.retry_after)

        request._retry_count += 1
        jitter = random.uniform(*self.retry_jitter)
        time.sleep(jitter)
        queue.put(request)

        with self.request_tracking_lock:
            if request.id in self.active_requests:
                status = self.active_requests[request.id]
                status.phase = RequestPhase.QUEUED
                status.phase_entered_at = time.time()
                status.retry_count = request._retry_count

        self._emit_event(
            on_event,
            LLMEvent.RETRY_QUEUED,
            request_id=request.id,
            retry_count=request._retry_count,
            queue_position=queue.qsize()
        )

    def _handle_permanent_failure(
        self,
        result: LLMResult,
        request: LLMRequest,
        on_event: Optional[Callable],
        on_result: Optional[Callable]
    ):
        with self.request_tracking_lock:
            if request.id in self.active_requests:
                self.active_requests.pop(request.id)

        self._emit_event(on_event, LLMEvent.FAILED, request_id=request.id)
        self._store_result(result)
        if on_result:
            on_result(result)

    def _handle_worker_crash(
        self,
        error: Exception,
        request: Optional[LLMRequest],
        on_event: Optional[Callable],
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

            self._store_result(failure_result)

            try:
                self._emit_event(on_event, LLMEvent.FAILED, request_id=request.id)
            except Exception:
                pass  # Don't propagate emit errors

            if on_result:
                try:
                    on_result(failure_result)
                except Exception:
                    pass

        error_msg = (
            f"❌ CRITICAL: Worker thread crashed with unexpected error:\n"
            f"   Error: {error}\n"
            f"   Type: {type(error).__name__}\n"
        )
        if request and hasattr(request, 'id'):
            error_msg += f"   Request ID: {request.id}\n"
        error_msg += f"   Full traceback:\n{error_detail}"

        print(error_msg, file=sys.stderr, flush=True)

    def _store_result(self, result: LLMResult):
        with self.results_lock:
            self.results[result.request_id] = result

    def _emit_event(
        self,
        callback: Optional[Callable[[EventData], None]],
        event_type: LLMEvent,
        request_id: Optional[str] = None,
        **kwargs
    ):
        if not callback:
            return

        event = EventData(
            event_type=event_type,
            request_id=request_id,
            timestamp=time.time(),
            **kwargs
        )
        callback(event)

    def get_active_requests(self) -> Dict[str, RequestStatus]:
        with self.request_tracking_lock:
            return {
                req_id: RequestStatus(
                    request_id=status.request_id,
                    phase=status.phase,
                    queued_at=status.queued_at,
                    phase_entered_at=status.phase_entered_at,
                    retry_count=status.retry_count,
                    rate_limit_eta=status.rate_limit_eta
                )
                for req_id, status in self.active_requests.items()
            }

