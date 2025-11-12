#!/usr/bin/env python3
from typing import List, Dict, Tuple, Optional

from infra.llm.openrouter import OpenRouterTransport, ResponseParser, RetryPolicy
from infra.llm.openrouter.pricing import CostCalculator
from infra.llm.openrouter.images import add_images_to_messages


def call_with_tools(
    transport: OpenRouterTransport,
    parser: ResponseParser,
    retry: RetryPolicy,
    cost_calculator: CostCalculator,
    model: str,
    messages: List[Dict[str, str]],
    tools: List[Dict],
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,
    timeout: int = 120,
    images: Optional[List] = None,
) -> Tuple[Optional[str], Dict, float, Optional[List[Dict]], Optional[List[Dict]]]:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "tools": tools,
    }

    if max_tokens:
        payload["max_tokens"] = max_tokens

    if images:
        payload["messages"] = add_images_to_messages(messages, images)

    def _make_call():
        result = transport.post(payload, timeout)
        return parser.parse_tool_completion(result, model)

    content, usage, tool_calls, reasoning_details = retry.execute_with_retry(_make_call, payload)

    cost = cost_calculator.calculate_cost(
        model,
        usage.get('prompt_tokens', 0),
        usage.get('completion_tokens', 0)
    )

    return content, usage, cost, tool_calls, reasoning_details
