#!/usr/bin/env python3
import time
from typing import List, Optional, Callable

from infra.llm.models import LLMRequest, LLMResult, LLMEvent, EventData
from infra.llm.client import LLMClient
from infra.llm.rate_limiter import RateLimiter
from infra.config import Config

from .stats import BatchStatsTracker, BatchStats
from .executor import RequestExecutor
from .worker import WorkerPool
from .callbacks import wrap_with_stats_tracking, wrap_with_progress_monitoring


class LLMBatchClient:
    def __init__(
        self,
        max_workers: Optional[int] = None,
        rate_limit: Optional[int] = None,
        max_retries: int = 5,
        retry_jitter: tuple = (1.0, 3.0),
        progress_interval: float = 1.0,
        logger=None,
    ):
        self.max_workers = max_workers if max_workers is not None else Config.max_workers
        self.rate_limit = rate_limit if rate_limit is not None else Config.rate_limit_requests_per_minute
        self.max_retries = max_retries
        self.retry_jitter = retry_jitter
        self.progress_interval = progress_interval
        self.logger = logger

        self.llm_client = LLMClient()
        self.rate_limiter = RateLimiter(requests_per_minute=self.rate_limit)

        self.request_executor = RequestExecutor(
            llm_client=self.llm_client,
            max_retries=self.max_retries
        )

        self.worker_pool = WorkerPool(
            executor=self.request_executor,
            rate_limiter=self.rate_limiter,
            max_workers=self.max_workers,
            logger=self.logger,
            retry_jitter=self.retry_jitter,
            progress_interval=self.progress_interval,
        )

        self.stats_tracker: Optional[BatchStatsTracker] = None
        self.batch_start_time: Optional[float] = None

    def process_batch(
        self,
        requests: List[LLMRequest],
        on_event: Optional[Callable[[EventData], None]] = None,
        on_result: Optional[Callable[[LLMResult], None]] = None,
    ) -> List[LLMResult]:
        if not requests:
            return []

        for req in requests:
            if not req.response_format:
                raise ValueError(
                    f"Request {req.id} missing response_format. "
                    "All requests must use structured JSON output."
                )

        # Initialize stats tracking
        self.batch_start_time = time.time()
        self.stats_tracker = BatchStatsTracker(batch_start_time=self.batch_start_time)

        # Wrap callbacks for stats tracking and progress monitoring
        wrapped_result = wrap_with_stats_tracking(on_result, self.stats_tracker)
        wrapped_event = wrap_with_progress_monitoring(
            on_event,
            self.stats_tracker,
            self.worker_pool,
            self.rate_limiter,
            len(requests),
            self.progress_interval
        )

        # Execute via worker pool
        results_dict = self.worker_pool.process_batch(
            requests,
            on_event=wrapped_event,
            on_result=wrapped_result
        )

        # Convert dict to ordered list
        result_list = []
        for req in requests:
            result = results_dict.get(req.id)
            if result:
                result_list.append(result)
            else:
                result_list.append(LLMResult(
                    request_id=req.id,
                    success=False,
                    error_type="missing",
                    error_message="Result not found after processing",
                    request=req
                ))

        return result_list

    def get_batch_stats(self, total_requests: int = None) -> BatchStats:
        if not self.stats_tracker:
            return BatchStats(
                total_requests=0, completed=0, failed=0, in_progress=0, queued=0,
                avg_time_per_request=0.0, min_time=0.0, max_time=0.0,
                total_cost_usd=0.0, avg_cost_per_request=0.0,
                total_prompt_tokens=0, total_tokens=0, total_reasoning_tokens=0,
                avg_tokens_per_request=0.0, requests_per_second=0.0,
                rate_limit_utilization=0.0, rate_limit_tokens_available=0
            )

        return self.stats_tracker.get_batch_stats(
            total_requests=total_requests or len(self.worker_pool.results),
            completed_results=self.worker_pool.results,
            in_progress_count=len(self.worker_pool.get_active_requests()),
            rate_limit_status=self.rate_limiter.get_status()
        )

    def get_stats(self) -> dict:
        if not self.stats_tracker:
            return {
                'requests_completed': 0, 'requests_failed': 0,
                'total_cost_usd': 0.0, 'total_prompt_tokens': 0,
                'total_tokens': 0, 'total_reasoning_tokens': 0, 'retry_count': 0,
                'rate_limit_status': self.rate_limiter.get_status()
            }

        stats = self.stats_tracker.get_stats()
        stats['rate_limit_status'] = self.rate_limiter.get_status()
        return stats

    def get_rate_limit_status(self) -> dict:
        return self.rate_limiter.get_status()

    def get_active_requests(self) -> dict:
        return self.worker_pool.get_active_requests()
