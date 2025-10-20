#!/usr/bin/env python3
"""
Unified LLM Client for OpenRouter API

Provides a consistent interface for all LLM calls across the pipeline with:
- Automatic retries with exponential backoff
- Optional streaming with progress tracking
- Vision model support (images)
- Cost tracking with dynamic pricing
- Configurable timeouts
- Thread-safe for parallel execution
"""

import os
import time
import json
import base64
import logging
import requests
from typing import List, Dict, Tuple, Optional, Union
from pathlib import Path
from dotenv import load_dotenv
from infra.llm.pricing import CostCalculator


# Token estimation constant
# Empirically derived average for character-to-token conversion when actual usage unavailable
CHARS_PER_TOKEN_ESTIMATE = 4


class LLMClient:
    """
    Unified client for OpenRouter API calls.

    Features:
    - Automatic retry logic with exponential backoff
    - Streaming support for long responses
    - Vision model support with image inputs
    - Cost tracking with dynamic pricing
    - Thread-safe for parallel execution
    """

    def __init__(self,
                 site_url: str = "https://github.com/jackzampolin/scanshelf",
                 site_name: str = "Scanshelf"):
        """
        Initialize LLM client.

        Args:
            site_url: Site URL for OpenRouter tracking
            site_name: Site name for OpenRouter tracking
        """
        # Load API key
        load_dotenv()
        self.api_key = os.getenv('OPEN_ROUTER_API_KEY') or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("No OpenRouter API key found in environment")

        # OpenRouter config
        self.site_url = site_url
        self.site_name = site_name
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

        # Cost calculator (supports dynamic pricing from OpenRouter)
        self.cost_calculator = CostCalculator()

    def call(self,
             model: str,
             messages: List[Dict[str, str]],
             temperature: float = 0.0,
             max_tokens: Optional[int] = None,
             timeout: int = 120,
             max_retries: int = 3,
             stream: bool = False,
             images: Optional[List[Union[bytes, str, Path]]] = None,
             response_format: Optional[Dict] = None) -> Tuple[str, Dict, float]:
        """
        Make LLM API call with automatic retries and cost tracking.

        Args:
            model: OpenRouter model name (e.g., "anthropic/claude-sonnet-4.5")
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate (None = no limit)
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts for server errors
            stream: Enable streaming response (shows progress)
            images: Optional list of images for vision models
                    Can be bytes, base64 strings, or file paths
            response_format: Optional structured output schema
                           Use {"type": "json_schema", "json_schema": {...}} for guaranteed JSON

        Returns:
            Tuple of (response_text, usage_dict, cost_usd)

        Raises:
            requests.exceptions.RequestException: On non-retryable errors
        """
        # Handle vision models with images
        if images:
            messages = self._add_images_to_messages(messages, images)

        # Build request payload
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream
        }

        if max_tokens:
            payload["max_tokens"] = max_tokens

        if response_format:
            payload["response_format"] = response_format

        # Retry loop for server errors
        for attempt in range(max_retries):
            try:
                if stream:
                    return self._call_streaming(headers, payload, model, images)
                else:
                    return self._call_non_streaming(headers, payload, model, timeout, images)

            except requests.exceptions.HTTPError as e:
                # Check for retryable errors
                should_retry = False
                error_type = "error"
                error_msg = ""

                # Always retry 5xx server errors
                if e.response.status_code >= 500:
                    should_retry = True
                    error_type = f"{e.response.status_code} server error"

                # Retry all 422 errors (xAI provider deserialization issues are transient)
                elif e.response.status_code == 422:
                    should_retry = True
                    error_type = "422 unprocessable entity"
                    # Use cached error data for logging (response body already consumed)
                    error_data = getattr(e.response, '_error_data_cache', None)
                    if error_data:
                        error_msg = error_data.get('error', {}).get('message', '')
                        # Truncate long error messages
                        if len(error_msg) > 80:
                            error_msg = error_msg[:80] + "..."

                if should_retry and attempt < max_retries - 1:
                    delay = (2 ** attempt) * 2  # Exponential backoff: 2s, 4s, 8s
                    # Suppress retry messages - stage-level logging will show final errors
                    time.sleep(delay)
                    continue
                elif should_retry:
                    # Final retry failed - let exception propagate to stage-level handler
                    raise
                else:
                    # Non-retryable client errors (4xx) - let exception propagate
                    raise

            except requests.exceptions.Timeout:
                if attempt < max_retries - 1:
                    delay = (2 ** attempt) * 2  # Exponential backoff: 2s, 4s, 8s
                    # Suppress retry messages - stage-level logging will show final errors
                    time.sleep(delay)
                    continue
                else:
                    # Let exception propagate to stage-level handler
                    raise

    def _call_non_streaming(self,
                           headers: Dict,
                           payload: Dict,
                           model: str,
                           timeout: int,
                           images: Optional[List] = None) -> Tuple[str, Dict, float]:
        """Make non-streaming API call."""
        response = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=timeout
        )

        # Cache error data on response object for retry logic (no printing here)
        if not response.ok:
            try:
                error_data = response.json()
                response._error_data_cache = error_data  # Cache for retry logic
            except:
                response._error_data_cache = None

        response.raise_for_status()

        result = response.json()

        # Extract response and usage
        content = result['choices'][0]['message']['content']
        usage = result.get('usage', {})

        # Calculate cost
        cost = self.cost_calculator.calculate_cost(
            model,
            usage.get('prompt_tokens', 0),
            usage.get('completion_tokens', 0),
            num_images=len(images) if images else 0
        )

        return content, usage, cost

    def _call_streaming(self,
                       headers: Dict,
                       payload: Dict,
                       model: str,
                       images: Optional[List] = None) -> Tuple[str, Dict, float]:
        """Make streaming API call with progress tracking."""
        response = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            stream=True
        )
        response.raise_for_status()

        full_content = []
        tokens_received = 0
        actual_usage = None  # Will be populated from final chunk

        print("📊 Streaming response:")

        for line in response.iter_lines():
            if not line:
                continue

            line = line.decode('utf-8')
            if line.startswith('data: '):
                data_str = line[6:]

                if data_str == '[DONE]':
                    break

                try:
                    chunk = json.loads(data_str)

                    # Check for usage data in final chunk (before [DONE])
                    if 'usage' in chunk:
                        usage_data = chunk['usage']

                        # Validate usage structure
                        if (isinstance(usage_data, dict) and
                            'prompt_tokens' in usage_data and
                            'completion_tokens' in usage_data):
                            actual_usage = usage_data
                        else:
                            # Malformed - log and skip
                            logger = logging.getLogger(__name__)
                            logger.warning(
                                f"Malformed usage data in SSE chunk",
                                extra={
                                    'model': model,
                                    'usage_data': usage_data,
                                    'expected_keys': ['prompt_tokens', 'completion_tokens']
                                }
                            )

                    if 'choices' in chunk and len(chunk['choices']) > 0:
                        delta = chunk['choices'][0].get('delta', {})
                        content = delta.get('content', '')

                        if content:
                            full_content.append(content)
                            tokens_received += 1

                            # Update progress every 100 tokens
                            if tokens_received % 100 == 0:
                                print(f"\r   Tokens: {tokens_received:,}...", end='', flush=True)
                except json.JSONDecodeError:
                    continue

        print(f"\r   Tokens: {tokens_received:,} ✓")

        complete_response = ''.join(full_content)

        # Use actual usage if available, otherwise fall back to estimate
        if actual_usage:
            usage = actual_usage
        else:
            # Fallback to char-based estimate
            prompt_chars = sum(len(m.get('content', '')) for m in payload['messages'])
            completion_chars = len(complete_response)

            usage = {
                'prompt_tokens': prompt_chars // CHARS_PER_TOKEN_ESTIMATE,
                'completion_tokens': completion_chars // CHARS_PER_TOKEN_ESTIMATE,
                '_estimated': True
            }

            # Log warning
            logger = logging.getLogger(__name__)
            logger.warning(
                f"No usage data in SSE stream, using char-based estimate. "
                f"Cost tracking may be inaccurate.",
                extra={'model': model, 'estimated_tokens': usage}
            )

        # Calculate cost
        cost = self.cost_calculator.calculate_cost(
            model,
            usage['prompt_tokens'],
            usage['completion_tokens'],
            num_images=len(images) if images else 0
        )

        return complete_response, usage, cost

    def _add_images_to_messages(self,
                                messages: List[Dict],
                                images: List[Union[bytes, str, Path]]) -> List[Dict]:
        """
        Add images to the last user message for vision models.

        Args:
            messages: Original message list
            images: List of images (bytes, base64 strings, PIL Images, or file paths)

        Returns:
            Modified messages with images embedded
        """
        # Find last user message
        user_msg_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]['role'] == 'user':
                user_msg_idx = i
                break

        if user_msg_idx is None:
            raise ValueError("No user message found to attach images to")

        # Convert message content to multipart format
        original_content = messages[user_msg_idx]['content']

        # Build content array with text + images
        content = [{"type": "text", "text": original_content}]

        for img in images:
            # Convert to base64 if needed
            if isinstance(img, bytes):
                img_b64 = base64.b64encode(img).decode('utf-8')
            elif isinstance(img, Path) or (isinstance(img, str) and os.path.exists(img)):
                with open(img, 'rb') as f:
                    img_b64 = base64.b64encode(f.read()).decode('utf-8')
            elif hasattr(img, 'save'):  # PIL Image object
                # Convert PIL Image to bytes then base64
                # Use JPEG for efficiency (quality=75 balances size vs readability for text)
                import io
                logger = logging.getLogger(__name__)

                buffered = io.BytesIO()
                img.save(buffered, format="JPEG", quality=75)
                img_bytes = buffered.getvalue()
                img_b64 = base64.b64encode(img_bytes).decode('utf-8')

                # Log payload size for debugging
                jpeg_kb = len(img_bytes) / 1024
                payload_kb = len(img_b64) / 1024
                logger.debug(f"Encoding image: {img.size[0]}×{img.size[1]} → {jpeg_kb:.0f}KB JPEG, {payload_kb:.0f}KB base64")
            else:
                # Assume it's already base64
                img_b64 = img

            # Use JPEG MIME type for PIL Image objects, PNG for others
            mime_type = "image/jpeg" if hasattr(img, 'save') else "image/png"

            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{img_b64}"
                }
            })

        # Update message
        messages[user_msg_idx]['content'] = content

        return messages

    def simple_call(self,
                   model: str,
                   system_prompt: str,
                   user_prompt: str,
                   temperature: float = 0.0,
                   **kwargs) -> Tuple[str, Dict, float]:
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


# Convenience function for quick one-off calls
# NOTE: Currently unused in codebase (not exported in __all__).
# Kept for potential use in scripts, notebooks, or future convenience.
# Consider: Instantiate LLMClient() and use simple_call() instead for better performance.
def call_llm(model: str,
            system_prompt: str,
            user_prompt: str,
            temperature: float = 0.0,
            **kwargs) -> Tuple[str, Dict, float]:
    """
    Quick convenience function for simple LLM calls.

    NOTE: This function creates a new LLMClient instance for each call.
    For better performance with multiple calls, instantiate LLMClient once
    and call simple_call() directly.

    Args:
        model: OpenRouter model name
        system_prompt: System message content
        user_prompt: User message content
        temperature: Sampling temperature
        **kwargs: Additional arguments (timeout, stream, images, etc.)

    Returns:
        Tuple of (response_text, usage_dict, cost_usd)

    Example:
        response, usage, cost = call_llm(
            "openai/gpt-4o-mini",
            "You are a helpful assistant.",
            "What is 2+2?",
            temperature=0.0
        )
    """
    client = LLMClient()
    return client.simple_call(model, system_prompt, user_prompt, temperature, **kwargs)


if __name__ == "__main__":
    # Test the client
    print("Testing LLMClient...")

    client = LLMClient()

    # Test 1: Simple call
    print("\n1. Simple call:")
    response, usage, cost = client.simple_call(
        "openai/gpt-4o-mini",
        "You are a helpful assistant.",
        "What is 2+2?",
        temperature=0.0
    )
    print(f"Response: {response}")
    print(f"Tokens: {usage.get('prompt_tokens', 0)} in, {usage.get('completion_tokens', 0)} out")
    print(f"Cost: ${cost:.6f}")

    # Test 2: Streaming call
    print("\n2. Streaming call:")
    response, usage, cost = client.simple_call(
        "openai/gpt-4o-mini",
        "You are a helpful assistant.",
        "Count from 1 to 10 and explain why each number is interesting.",
        temperature=0.0,
        stream=True
    )
    print(f"\nCost: ${cost:.6f}")

    print("\n✅ LLMClient tests complete!")
