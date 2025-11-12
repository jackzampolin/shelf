import logging
import time
import uuid
from typing import List, Dict, Tuple, Optional

from infra.llm.openrouter import OpenRouterTransport, ResponseParser, RetryPolicy
from infra.llm.openrouter.pricing import CostCalculator
from infra.llm.openrouter.images import add_images_to_messages
from infra.llm.models import LLMResult


class LLMClient:
    def __init__(self, logger: Optional[logging.Logger] = None, site_url: Optional[str] = None, site_name: Optional[str] = None, max_retries: int = 3):
        self.logger = logger or logging.getLogger(__name__)
        self.transport = OpenRouterTransport(logger=self.logger, site_url=site_url, site_name=site_name)
        self.retry = RetryPolicy(logger=self.logger, max_retries=max_retries)
        self.parser = ResponseParser(logger=self.logger)
        self.cost_calculator = CostCalculator()

    def call(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        timeout: int = 120,
        response_format: Optional[Dict] = None,
        images: Optional[List] = None,
        request_id: Optional[str] = None,
        queue_time: float = 0.0,
        request: Optional[any] = None,
        **kwargs
    ) -> LLMResult:
        start_time = time.time()
        if request_id is None:
            request_id = str(uuid.uuid4())

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if response_format:
            payload["response_format"] = response_format

        if images:
            payload["messages"] = add_images_to_messages(messages, images, self.logger)

        def _make_call():
            result = self.transport.post(payload, timeout)
            return self.parser.parse_chat_completion(result, model)

        parsed, attempts = self.retry.execute_with_retry(_make_call, payload)

        execution_time = time.time() - start_time

        cost = self.cost_calculator.calculate_cost(
            model,
            parsed.prompt_tokens,
            parsed.completion_tokens,
            num_images=len(images) if images else 0
        )

        parsed_json = None
        if response_format and parsed.content:
            import json
            try:
                parsed_json = json.loads(parsed.content)
            except json.JSONDecodeError as e:
                # Structured response requested but got invalid JSON - treat as retryable error
                return LLMResult(
                    request_id=request_id,
                    success=False,
                    error_type="json_parse",
                    error_message=f"Failed to parse JSON response: {str(e)}",
                    attempts=attempts,
                    total_time_seconds=execution_time + queue_time,
                    queue_time_seconds=queue_time,
                    execution_time_seconds=execution_time,
                    prompt_tokens=parsed.prompt_tokens,
                    completion_tokens=parsed.completion_tokens,
                    total_tokens=parsed.total_tokens,
                    reasoning_tokens=parsed.reasoning_tokens,
                    cost_usd=cost,
                    provider=parsed.provider,
                    model_used=parsed.model_used,
                    request=request
                )

        return LLMResult(
            request_id=request_id,
            success=True,
            response=parsed.content,
            parsed_json=parsed_json,
            attempts=attempts,
            total_time_seconds=execution_time + queue_time,
            queue_time_seconds=queue_time,
            execution_time_seconds=execution_time,
            prompt_tokens=parsed.prompt_tokens,
            completion_tokens=parsed.completion_tokens,
            total_tokens=parsed.total_tokens,
            reasoning_tokens=parsed.reasoning_tokens,
            cost_usd=cost,
            provider=parsed.provider,
            model_used=parsed.model_used,
            request=request
        )

    def call_with_tools(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        timeout: int = 120,
        images: Optional[List] = None,
    ) -> LLMResult:
        start_time = time.time()
        request_id = str(uuid.uuid4())

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "tools": tools,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if images:
            payload["messages"] = add_images_to_messages(messages, images, self.logger)

        def _make_call():
            result = self.transport.post(payload, timeout)
            return self.parser.parse_tool_completion(result, model)

        parsed, attempts = self.retry.execute_with_retry(_make_call, payload)

        execution_time = time.time() - start_time

        cost = self.cost_calculator.calculate_cost(
            model,
            parsed.prompt_tokens,
            parsed.completion_tokens
        )

        return LLMResult(
            request_id=request_id,
            success=True,
            response=parsed.content,
            parsed_json=None,  # Tool calls don't use structured JSON responses
            attempts=attempts,
            total_time_seconds=execution_time,
            queue_time_seconds=0.0,  # No queue for direct calls
            execution_time_seconds=execution_time,
            prompt_tokens=parsed.prompt_tokens,
            completion_tokens=parsed.completion_tokens,
            total_tokens=parsed.total_tokens,
            reasoning_tokens=parsed.reasoning_tokens,
            cost_usd=cost,
            provider=parsed.provider,
            model_used=parsed.model_used,
            tool_calls=parsed.tool_calls,
            reasoning_details=parsed.reasoning_details
        )
