#!/usr/bin/env python3
import time
from typing import List, Optional, Callable

from infra.llm.models import LLMRequest, LLMResult
from infra.llm.client import LLMClient
from infra.llm.rate_limiter import RateLimiter
from infra.config import Config

from .executor import RequestExecutor
from .worker import WorkerPool


class LLMBatchClient:
    def __init__(
        self,
        model: str,
        max_workers: Optional[int] = None,
        rate_limit: Optional[int] = None,
        max_retries: int = 5,
        retry_jitter: tuple = (1.0, 3.0),
        logger=None,
    ):
        if logger is None:
            raise ValueError("LLMBatchClient requires a logger instance")
        self.model = model
        self.max_workers = max_workers if max_workers is not None else Config.max_workers
        self.rate_limit = rate_limit if rate_limit is not None else Config.rate_limit_requests_per_minute
        self.max_retries = max_retries
        self.retry_jitter = retry_jitter
        self.logger = logger

        self.llm_client = LLMClient(logger=self.logger)
        self.rate_limiter = RateLimiter(requests_per_minute=self.rate_limit)

        self.request_executor = RequestExecutor(
            llm_client=self.llm_client,
            model=self.model,  # Pass model to executor
            max_retries=self.max_retries,
            logger=self.logger
        )

        self.worker_pool = WorkerPool(
            executor=self.request_executor,
            rate_limiter=self.rate_limiter,
            max_workers=self.max_workers,
            logger=self.logger,
            retry_jitter=self.retry_jitter,
        )

        self.batch_start_time: Optional[float] = None

    def process_batch(
        self,
        requests: List[LLMRequest],
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

        self.batch_start_time = time.time()

        results_dict = self.worker_pool.process_batch(
            requests,
            on_result=on_result
        )

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
