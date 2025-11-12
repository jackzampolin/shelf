#!/usr/bin/env python3
from typing import List, Dict, Tuple, Optional

from infra.config import Config
from infra.llm.pricing import CostCalculator
from infra.llm.openrouter import OpenRouterTransport, ResponseParser, RetryPolicy


class LLMClient:
    def __init__(self, site_url: Optional[str] = None, site_name: Optional[str] = None):
        self.transport = OpenRouterTransport(site_url=site_url, site_name=site_name)
        self.retry = RetryPolicy(max_retries=3)
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
            payload["messages"] = self._add_images_to_messages(messages, images)

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

    def call_with_tools(
        self,
        model: str,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        timeout: int = 120,
        images: Optional[List] = None,
        **kwargs
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
            payload["messages"] = self._add_images_to_messages(messages, images)

        def _make_call():
            result = self.transport.post(payload, timeout)
            return self.parser.parse_tool_completion(result, model)

        content, usage, tool_calls, reasoning_details = self.retry.execute_with_retry(_make_call, payload)

        cost = self.cost_calculator.calculate_cost(
            model,
            usage.get('prompt_tokens', 0),
            usage.get('completion_tokens', 0)
        )

        return content, usage, cost, tool_calls, reasoning_details

    def simple_call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        **kwargs
    ) -> Tuple[str, Dict, float]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        return self.call(model, messages, temperature=temperature, **kwargs)

    def _add_images_to_messages(self, messages: List[Dict], images: List) -> List[Dict]:
        import base64
        import io

        user_msg_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]['role'] == 'user':
                user_msg_idx = i
                break

        if user_msg_idx is None:
            raise ValueError("No user message found to attach images to")

        original_content = messages[user_msg_idx]['content']

        if isinstance(original_content, list):
            content = original_content.copy()
        else:
            content = [{"type": "text", "text": original_content}]

        for img in images:
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=75)
            img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}"
                }
            })

        messages = messages.copy()
        messages[user_msg_idx] = messages[user_msg_idx].copy()
        messages[user_msg_idx]['content'] = content

        return messages
