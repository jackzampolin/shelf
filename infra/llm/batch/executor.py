import time
import logging

from infra.llm.models import LLMRequest, LLMResult
from infra.llm.client import LLMClient
from .retry import classify_error, extract_retry_after

logger = logging.getLogger(__name__)


class RequestExecutor:
    def __init__(self, llm_client: LLMClient, model: str, max_retries: int = 5, logger=None):
        if logger is None:
            raise ValueError("RequestExecutor requires a logger instance")
        self.llm_client = llm_client
        self.model = model
        self.max_retries = max_retries
        self.logger = logger

    def execute_request(self, request: LLMRequest) -> LLMResult:
        start_time = time.time()
        queue_time = start_time - request._queued_at

        self.logger.debug(f"Executor START: {request.id}")

        try:
            self.logger.debug(f"Executor CALLING LLM: {request.id} (model={self.model})")

            result = self.llm_client.call(
                model=self.model,
                messages=request.messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                images=request.images,
                response_format=request.response_format,
                timeout=request.timeout,
                request_id=request.id,
                queue_time=queue_time,
                request=request
            )

            self.logger.debug(f"Executor LLM RETURNED: {request.id} (response_len={len(result.response or '')}, cost=${result.cost_usd:.4f})")
            self.logger.debug(f"Executor RETURNING SUCCESS: {request.id} ({result.execution_time_seconds:.1f}s)")

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            error_type = classify_error(e)

            retry_after = None
            if error_type == '429_rate_limit':
                retry_after = extract_retry_after(e)

            will_retry = request._retry_count < self.max_retries
            log_message = f"LLM request failed: {request.id}"
            if will_retry:
                log_message += f" (will retry, attempt {request._retry_count + 1}/{self.max_retries})"
            else:
                log_message += f" (final attempt)"

            error_context = {
                'request_id': request.id,
                'error_type': error_type,
                'error': str(e),
                'attempt': request._retry_count + 1,
                'max_retries': self.max_retries,
                'model': self.model,
                'temperature': request.temperature,
                'max_tokens': request.max_tokens,
                'timeout': request.timeout,
                'has_images': len(request.images) if request.images else 0,
                'queue_time_seconds': queue_time,
                'execution_time_seconds': execution_time,
            }

            if request.messages:
                if len(request.messages) == 1:
                    error_context['messages_preview'] = f"[{request.messages[0]['role']}]"
                else:
                    error_context['messages_preview'] = f"[{request.messages[0]['role']}] ... [{request.messages[-1]['role']}] ({len(request.messages)} total)"

            if request.response_format:
                error_context['response_format'] = request.response_format.get('type', 'unknown')

            self.logger.error(log_message, **error_context)

            return LLMResult(
                request_id=request.id,
                success=False,
                error_type=error_type,
                error_message=str(e),
                retry_after=retry_after,
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                request=request
            )
