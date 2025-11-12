#!/usr/bin/env python3
"""
Unified LLM Client for OpenRouter API.

Orchestrates transport, retry, parsing, and cost tracking layers.

Simplified architecture:
- No streaming support (removed)
- No image encoding (handled by SourceStorage)
- Clean composition of focused components
"""

from typing import List, Dict, Tuple, Optional

from infra.config import Config
from infra.llm.pricing import CostCalculator
from infra.llm.openrouter import OpenRouterTransport, ResponseParser, RetryPolicy


class LLMClient:
    """
    Orchestrates OpenRouter API calls with retry, parsing, and cost tracking.

    Responsibilities:
    - Build request payloads
    - Coordinate transport + retry + parsing layers
    - Calculate costs

    Components:
    - OpenRouterTransport: HTTP requests
    - RetryPolicy: Retry logic with backoff and nonce
    - ResponseParser: Response extraction and malformed handling
    - CostCalculator: Dynamic pricing from OpenRouter

    Note:
        Images should be preprocessed by SourceStorage.load_page_image(downsample=True)
        before passing to this client. This client does NOT handle image encoding.
    """

    def __init__(self, site_url: Optional[str] = None, site_name: Optional[str] = None):
        """
        Initialize LLM client.

        Args:
            site_url: Site URL for OpenRouter tracking (default: Config.openrouter_site_url)
            site_name: Site name for OpenRouter tracking (default: Config.openrouter_site_name)
        """
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
        **kwargs  # Absorb unused legacy params (stream, max_retries, etc.)
    ) -> Tuple[str, Dict, float]:
        """
        Make LLM API call with automatic retries and cost tracking.

        Args:
            model: OpenRouter model name (e.g., "anthropic/claude-sonnet-4.5")
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate (None = no limit)
            timeout: Request timeout in seconds
            response_format: Optional structured output schema
                           Use {"type": "json_schema", "json_schema": {...}} for guaranteed JSON
            images: Optional list of PIL Image objects (preprocessed by SourceStorage)
                    IMPORTANT: Images should be downsampled before passing here

        Returns:
            Tuple of (response_text, usage_dict, cost_usd)

        Raises:
            requests.exceptions.RequestException: On non-retryable errors

        Note:
            Reasoning models (Grok-4-fast, o1/o4) use extended reasoning by default.
            Usage dict includes 'completion_tokens_details': {'reasoning_tokens': N}
        """
        # Build payload
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if response_format:
            payload["response_format"] = response_format

        # Handle images (if provided - should be preprocessed by SourceStorage)
        if images:
            payload["messages"] = self._add_images_to_messages(messages, images)

        # Execute with retry
        def _make_call():
            result = self.transport.post(payload, timeout)
            return self.parser.parse_chat_completion(result, model)

        content, usage = self.retry.execute_with_retry(_make_call, payload)

        # Calculate cost
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
        **kwargs  # Absorb unused legacy params (max_retries, etc.)
    ) -> Tuple[Optional[str], Dict, float, Optional[List[Dict]], Optional[List[Dict]]]:
        """
        Make LLM API call with tool calling support.

        Args:
            model: OpenRouter model name (e.g., "anthropic/claude-sonnet-4.5")
            messages: List of message dicts with 'role' and 'content'
            tools: List of tool definitions in OpenRouter format
                   [{"type": "function", "function": {"name": "...", "parameters": {...}}}]
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate (None = no limit)
            timeout: Request timeout in seconds
            images: Optional list of PIL Image objects (preprocessed by SourceStorage)

        Returns:
            Tuple of (response_text, usage_dict, cost_usd, tool_calls, reasoning_details)
            - response_text: Can be None if model only calls tools
            - tool_calls: None if no tools called, otherwise list of:
              [{"id": "call_xxx", "type": "function", "function": {"name": "...", "arguments": "..."}}]
            - reasoning_details: None if no reasoning, otherwise list of reasoning blocks

        Raises:
            requests.exceptions.RequestException: On non-retryable errors
        """
        # Build payload
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "tools": tools,
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        # Handle images (if provided - should be preprocessed by SourceStorage)
        if images:
            payload["messages"] = self._add_images_to_messages(messages, images)

        # Execute with retry
        def _make_call():
            result = self.transport.post(payload, timeout)
            return self.parser.parse_tool_completion(result, model)

        content, usage, tool_calls, reasoning_details = self.retry.execute_with_retry(_make_call, payload)

        # Calculate cost
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
        """
        Simplified call with system + user prompts (common pattern).

        Args:
            model: OpenRouter model name
            system_prompt: System message content
            user_prompt: User message content
            temperature: Sampling temperature
            **kwargs: Additional arguments passed to call()

        Returns:
            Tuple of (response_text, usage_dict, cost_usd)
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        return self.call(model, messages, temperature=temperature, **kwargs)

    def _add_images_to_messages(self, messages: List[Dict], images: List) -> List[Dict]:
        """
        Add PIL Images to the last user message in multipart format.

        IMPORTANT: Images should be preprocessed by SourceStorage.load_page_image(downsample=True)
        before passing here. This method only converts PIL Images to base64 - it does NOT
        handle resizing, compression, or optimization.

        Args:
            messages: Original message list
            images: List of PIL Image objects (already downsampled)

        Returns:
            Modified messages with images embedded
        """
        import base64
        import io

        # Find last user message
        user_msg_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]['role'] == 'user':
                user_msg_idx = i
                break

        if user_msg_idx is None:
            raise ValueError("No user message found to attach images to")

        # Convert message to multipart format
        original_content = messages[user_msg_idx]['content']

        if isinstance(original_content, list):
            # Already multipart (from retry with nonce)
            content = original_content.copy()
        else:
            # Build new content array
            content = [{"type": "text", "text": original_content}]

        # Add images (assume PIL Image objects)
        for img in images:
            # Convert PIL Image to JPEG base64
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG", quality=75)
            img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{img_b64}"
                }
            })

        # Update message
        messages = messages.copy()
        messages[user_msg_idx] = messages[user_msg_idx].copy()
        messages[user_msg_idx]['content'] = content

        return messages
