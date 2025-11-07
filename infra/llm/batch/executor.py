#!/usr/bin/env python3
import time
import json
import logging
from typing import Optional, Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from infra.llm.models import LLMRequest, LLMResult, LLMEvent, EventData
from infra.llm.client import LLMClient

logger = logging.getLogger(__name__)


class RequestExecutor:
    def __init__(self, llm_client: LLMClient, max_retries: int = 5, logger=None):
        if logger is None:
            raise ValueError("RequestExecutor requires a logger instance")
        self.llm_client = llm_client
        self.max_retries = max_retries
        self.logger = logger

    def execute_request(
        self,
        request: LLMRequest,
        on_event: Optional[Callable[[EventData], None]] = None
    ) -> LLMResult:
        start_time = time.time()
        queue_time = start_time - request._queued_at

        self.logger.debug(f"Executor START: {request.id}")

        try:
            if not hasattr(request, '_router') or request._router is None:
                if request.fallback_models:
                    from infra.llm.router import ModelRouter
                    request._router = ModelRouter(
                        primary_model=request.model,
                        fallback_models=request.fallback_models
                    )

            current_model = request._router.get_current() if request._router else request.model

            self.logger.debug(f"Executor CALLING LLM: {request.id} (model={current_model})")

            # Hard timeout wrapper to catch hung requests
            # requests library timeout doesn't always fire, so we add a thread-based hard timeout
            hard_timeout = request.timeout + 30  # 30s grace period beyond request timeout

            def _llm_call():
                return self.llm_client.call(
                    model=current_model,
                    messages=request.messages,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    images=request.images,
                    response_format=request.response_format,
                    timeout=request.timeout,
                    max_retries=0,
                    stream=False
                )

            # Don't use context manager - manually manage executor to avoid shutdown blocking
            thread_executor = ThreadPoolExecutor(max_workers=1)
            future = thread_executor.submit(_llm_call)
            try:
                response_text, usage, cost = future.result(timeout=hard_timeout)
                thread_executor.shutdown(wait=False)  # Don't wait for thread cleanup
            except FuturesTimeoutError:
                # Hard timeout exceeded - LLM call hung
                # Abandon the hung thread - don't wait for it
                thread_executor.shutdown(wait=False)

                self.logger.error(
                    f"HARD TIMEOUT: LLM call hung for {request.id}",
                    request_id=request.id,
                    model=current_model,
                    hard_timeout=hard_timeout,
                    request_timeout=request.timeout
                )
                raise TimeoutError(f"LLM call exceeded hard timeout of {hard_timeout}s")

            self.logger.debug(f"Executor LLM RETURNED: {request.id} (response_len={len(response_text)}, cost=${cost:.4f})")

            parsed_json = json.loads(response_text)

            self.logger.debug(f"Executor JSON PARSED: {request.id}")

            if request._router:
                request._router.mark_success()

            execution_time = time.time() - start_time

            tokens_per_second = 0.0
            completion_tokens = usage.get('completion_tokens', 0)
            if execution_time > 0 and completion_tokens > 0:
                tokens_per_second = completion_tokens / execution_time

            provider = None
            if '/' in current_model:
                provider = current_model.split('/')[0]

            self.logger.debug(f"Executor RETURNING SUCCESS: {request.id} ({execution_time:.1f}s)")

            return LLMResult(
                request_id=request.id,
                success=True,
                response=response_text,
                parsed_json=parsed_json,
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                ttft_seconds=None,  # No TTFT without streaming
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
            execution_time = time.time() - start_time

            will_retry = request._retry_count < self.max_retries
            log_message = f"JSON parsing failed: {request.id}"
            if will_retry:
                log_message += f" (will retry, attempt {request._retry_count + 1}/{self.max_retries})"
            else:
                log_message += f" (final attempt)"

            response_preview = response_text if len(response_text) <= 1000 else f"{response_text[:500]}...{response_text[-500:]}"

            self.logger.error(
                log_message,
                request_id=request.id,
                error_type='json_parse',
                error=str(e),
                model=current_model,
                response_length=len(response_text),
                response_preview=response_preview,
                response_format=str(request.response_format),
                attempt=request._retry_count + 1,
                max_retries=self.max_retries,
                has_images=len(request.images) if request.images else 0,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time
            )
            self.logger.debug(f"Executor RETURNING ERROR (json_parse): {request.id}")

            return LLMResult(
                request_id=request.id,
                success=False,
                error_type="json_parse",
                error_message=f"JSON parsing failed: {str(e)}",
                attempts=request._retry_count + 1,
                total_time_seconds=execution_time + queue_time,
                queue_time_seconds=queue_time,
                execution_time_seconds=execution_time,
                request=request
            )

        except Exception as e:
            execution_time = time.time() - start_time
            error_type = self.classify_error(e)

            retry_after = None
            if error_type == '429_rate_limit':
                retry_after = self.extract_retry_after(e)

            will_retry = request._retry_count < self.max_retries and self.is_retryable(error_type)
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
                'model': current_model,
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
            self.logger.debug(f"Executor RETURNING ERROR ({error_type}): {request.id}")

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

    @staticmethod
    def classify_error(error: Exception) -> str:
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
    def extract_retry_after(error: Exception) -> Optional[int]:
        """Extract Retry-After header value from HTTPError exception.

        Returns:
            Seconds to wait (int), or None if header not present
        """
        try:
            import requests
            if isinstance(error, requests.exceptions.HTTPError):
                if hasattr(error, 'response') and error.response is not None:
                    retry_after = error.response.headers.get('Retry-After')
                    if retry_after:
                        # Retry-After can be either seconds (int) or HTTP date
                        # Try parsing as int first
                        try:
                            return int(retry_after)
                        except ValueError:
                            # Could be HTTP date format, but for now just return None
                            # Most APIs use seconds
                            return None
        except:
            pass
        return None

    @staticmethod
    def is_retryable(error_type: Optional[str]) -> bool:
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
