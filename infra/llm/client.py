#!/usr/bin/env python3
from typing import List, Dict, Tuple, Optional

from infra.llm.openrouter import OpenRouterTransport, ResponseParser, RetryPolicy
from infra.llm.openrouter.pricing import CostCalculator
from infra.llm.openrouter.images import add_images_to_messages


class LLMClient:
    def __init__(self, site_url: Optional[str] = None, site_name: Optional[str] = None, max_retries: int = 3):
        self.transport = OpenRouterTransport(site_url=site_url, site_name=site_name)
        self.retry = RetryPolicy(max_retries=max_retries)
        self.parser = ResponseParser()
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
        **kwargs
    ) -> Tuple[str, Dict, float]:
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
            payload["messages"] = add_images_to_messages(messages, images)

        def _make_call():
            result = self.transport.post(payload, timeout)
            return self.parser.parse_chat_completion(result, model)

        content, usage = self.retry.execute_with_retry(_make_call, payload)

        cost = self.cost_calculator.calculate_cost(
            model,
            usage.get('prompt_tokens', 0),
            usage.get('completion_tokens', 0),
            num_images=len(images) if images else 0
        )

        return content, usage, cost
