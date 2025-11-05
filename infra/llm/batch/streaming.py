#!/usr/bin/env python3
"""
SSE streaming execution for LLM requests.

Handles:
- Streaming API requests with Server-Sent Events (SSE)
- Real-time token counting and progress tracking
- Time-to-first-token (TTFT) measurement
- Event emission for progress updates
- Usage data extraction and cost calculation
"""

import time
import json
import uuid
import logging
from typing import Dict, Tuple, Optional, Callable, Any

from infra.llm.models import LLMRequest, LLMEvent, EventData
from infra.llm.client import CHARS_PER_TOKEN_ESTIMATE

logger = logging.getLogger(__name__)


class StreamingExecutor:
    """
    Executes streaming LLM requests with SSE parsing and telemetry.

    Provides:
    - Real-time token counting during streaming
    - Time-to-first-token (TTFT) tracking
    - Throttled progress events
    - Usage data extraction from SSE stream
    - Cost calculation

    All requests are streamed for full telemetry, even if caller doesn't
    need streaming output.
    """

    # Throttle interval for streaming events (seconds between events)
    STREAMING_THROTTLE_INTERVAL = 0.2

    # Stream stall timeout (seconds) - fail if no chunks received
    STREAM_STALL_TIMEOUT = 30.0

    def __init__(
        self,
        llm_client: 'LLMClient',
        session_manager: 'ThreadLocalSessionManager',
        verbose: bool = False
    ):
        """
        Initialize streaming executor.

        Args:
            llm_client: LLM client for API calls and cost calculation
            session_manager: Thread-local HTTP session manager
            verbose: Enable per-request streaming events
        """
        self.llm_client = llm_client
        self.session_manager = session_manager
        self.verbose = verbose

    def execute_streaming_request(
        self,
        request: LLMRequest,
        model: str,
        on_event: Optional[Callable[[EventData], None]],
        start_time: float
    ) -> Tuple[str, Dict, float, Optional[float]]:
        """
        Execute streaming LLM request with SSE parsing.

        Args:
            request: LLM request to execute
            model: Model to use (from router if fallback active)
            on_event: Event callback (if None, no events emitted)
            start_time: Request start timestamp (for elapsed calculation)

        Returns:
            Tuple of (response_text, usage_dict, cost_usd, ttft_seconds)

        Raises:
            TimeoutError: If stream stalls (no chunks for STREAM_STALL_TIMEOUT)
            json.JSONDecodeError: If response is not valid JSON
            Exception: Other HTTP/API errors
        """
        # Build API request
        headers = self._build_headers()
        payload = self._build_payload(request, model)

        # Get thread-local HTTP session
        session = self.session_manager.get_session()

        # Make streaming request
        response = None
        try:
            response = session.post(
                self.llm_client.base_url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=request.timeout
            )
            response.raise_for_status()

            # Process SSE stream
            return self._process_sse_stream(response, request, on_event, start_time)

        finally:
            # Ensure HTTP response is always closed to prevent resource leaks
            if response is not None:
                response.close()

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers for OpenRouter API."""
        return {
            "Authorization": f"Bearer {self.llm_client.api_key}",
            "Content-Type": "application/json"
        }

    def _build_payload(self, request: LLMRequest, model: str) -> Dict[str, Any]:
        """
        Build API request payload with cache-busting nonce.

        Each retry gets a fresh nonce to force API to treat it as a new request,
        preventing cached error responses.

        Args:
            request: LLM request
            model: Model name to use

        Returns:
            API request payload dict
        """
        # Generate unique nonce for cache-busting
        request_nonce = uuid.uuid4().hex[:16]

        # Add nonce to messages to ensure it's part of request hash
        messages_with_nonce = self._add_nonce_to_messages(request.messages, request_nonce)

        payload = {
            "model": model,
            "messages": messages_with_nonce,
            "temperature": request.temperature,
            "stream": True
        }

        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        if request.response_format:
            payload["response_format"] = request.response_format

        # Add images if present (multimodal)
        if request.images:
            messages_with_images = self.llm_client._add_images_to_messages(
                messages_with_nonce, request.images
            )
            payload["messages"] = messages_with_images

        return payload

    def _add_nonce_to_messages(self, messages: list, nonce: str) -> list:
        """
        Add nonce to last message to prevent cache collisions.

        Args:
            messages: Original messages list
            nonce: Unique nonce string

        Returns:
            Messages with nonce appended
        """
        messages_copy = messages.copy()
        if not messages_copy:
            return messages_copy

        # Append nonce to last message (least intrusive location)
        last_msg = messages_copy[-1].copy()
        content = last_msg.get('content', '')

        if isinstance(content, str):
            # Simple text message
            last_msg['content'] = f"{content}\n<!-- request_id: {nonce} -->"
        elif isinstance(content, list):
            # Multipart message (text + images) - add nonce to text part
            content_copy = []
            for item in content:
                item_copy = item.copy()
                if item_copy.get('type') == 'text':
                    item_copy['text'] = f"{item_copy.get('text', '')}\n<!-- request_id: {nonce} -->"
                content_copy.append(item_copy)
            last_msg['content'] = content_copy

        messages_copy[-1] = last_msg
        return messages_copy

    def _process_sse_stream(
        self,
        response: 'requests.Response',
        request: LLMRequest,
        on_event: Optional[Callable[[EventData], None]],
        start_time: float
    ) -> Tuple[str, Dict, float, Optional[float]]:
        """
        Parse SSE stream and extract response text, usage, cost, TTFT.

        Args:
            response: Streaming HTTP response
            request: Original request
            on_event: Event callback
            start_time: Request start time

        Returns:
            Tuple of (response_text, usage_dict, cost_usd, ttft_seconds)

        Raises:
            TimeoutError: If stream stalls
            ValueError: If too many parse errors
        """
        # Initialize streaming state
        state = self._init_streaming_state(start_time, request)

        # Parse SSE stream
        for line in response.iter_lines():
            # Check for stream stall
            self._check_stream_stall(state)

            if not line:
                continue

            # Update last chunk time
            state['last_chunk_time'] = time.time()

            line = line.decode('utf-8')
            if not line.startswith('data: '):
                continue

            data_str = line[6:]
            if data_str == '[DONE]':
                break

            # Parse chunk
            self._parse_sse_chunk(data_str, state, request, on_event, start_time)

        # Emit final streaming event (show complete state)
        if on_event and state['tokens_so_far'] > 0:
            self._emit_streaming_event(
                on_event, request, state, start_time, is_final=True
            )

        # Build final response
        return self._finalize_streaming_response(state, request)

    def _init_streaming_state(self, start_time: float, request: LLMRequest) -> Dict:
        """Initialize streaming state dict."""
        # Estimate input tokens for ETA calculation (chars / 3 ≈ tokens)
        input_chars = sum(len(str(m.get('content', ''))) for m in request.messages)
        input_tokens = input_chars // 3

        return {
            'start_time': start_time,
            'last_emit': start_time,
            'tokens_so_far': 0,
            'full_content': [],
            'actual_usage': None,  # Will be populated from final chunk
            'parse_errors': 0,
            'input_tokens': input_tokens,
            'first_token_time': None,
            'first_token_emitted': False,
            'last_chunk_time': start_time
        }

    def _check_stream_stall(self, state: Dict):
        """Check if stream has stalled (no data for too long)."""
        now = time.time()
        if now - state['last_chunk_time'] > self.STREAM_STALL_TIMEOUT:
            raise TimeoutError(
                f"Stream stalled: no data received for {self.STREAM_STALL_TIMEOUT}s. "
                f"Possible stale connection."
            )

    def _parse_sse_chunk(
        self,
        data_str: str,
        state: Dict,
        request: LLMRequest,
        on_event: Optional[Callable],
        start_time: float
    ):
        """Parse a single SSE chunk and update state."""
        try:
            chunk = json.loads(data_str)

            # Extract usage data from final chunk
            if 'usage' in chunk:
                self._extract_usage(chunk['usage'], state)

            # Extract content delta
            if 'choices' in chunk and len(chunk['choices']) > 0:
                delta = chunk['choices'][0].get('delta', {})
                content = delta.get('content', '')

                if content:
                    self._process_content_delta(
                        content, state, request, on_event, start_time
                    )

        except json.JSONDecodeError as e:
            state['parse_errors'] += 1

            # Log first error for debugging
            if state['parse_errors'] == 1:
                logger.warning(
                    f"SSE chunk parse error for {request.id}",
                    extra={
                        'request_id': request.id,
                        'chunk_preview': data_str[:200],
                        'error': str(e)
                    }
                )

            # If too many parse errors, stream may be corrupted
            if state['parse_errors'] > 10:
                raise ValueError(
                    f"Too many SSE parse errors ({state['parse_errors']}) "
                    f"for request {request.id} - stream may be corrupted"
                )

    def _extract_usage(self, usage_data: Any, state: Dict):
        """Extract and validate usage data from SSE chunk."""
        # Validate usage structure before using
        if (isinstance(usage_data, dict) and
            'prompt_tokens' in usage_data and
            'completion_tokens' in usage_data):
            state['actual_usage'] = usage_data
        else:
            # Malformed usage data - log warning
            logger.warning(
                f"Malformed usage data in SSE chunk",
                extra={
                    'usage_data': usage_data,
                    'expected_keys': ['prompt_tokens', 'completion_tokens']
                }
            )

    def _process_content_delta(
        self,
        content: str,
        state: Dict,
        request: LLMRequest,
        on_event: Optional[Callable],
        start_time: float
    ):
        """Process content delta from SSE chunk."""
        # Track time to first token
        if state['first_token_time'] is None:
            state['first_token_time'] = time.time()
            ttft = state['first_token_time'] - start_time

            # Emit FIRST_TOKEN event (once)
            if not state['first_token_emitted']:
                page_id = request.id.replace('page_', 'p')
                self._emit_event(
                    on_event,
                    LLMEvent.FIRST_TOKEN,
                    request_id=request.id,
                    eta_seconds=ttft,  # Reuse field for TTFT
                    message=f"{page_id}: Streaming started (TTFT: {ttft:.2f}s)"
                )
                state['first_token_emitted'] = True

        # Accumulate content
        state['full_content'].append(content)

        # Estimate tokens from character count
        total_chars = len(''.join(state['full_content']))
        state['tokens_so_far'] = total_chars // CHARS_PER_TOKEN_ESTIMATE

        # Emit throttled STREAMING event
        now = time.time()
        if now - state['last_emit'] >= self.STREAMING_THROTTLE_INTERVAL:
            self._emit_streaming_event(on_event, request, state, start_time)
            state['last_emit'] = now

    def _emit_event(
        self,
        callback: Optional[Callable],
        event_type: LLMEvent,
        request_id: str,
        **kwargs
    ):
        """Emit event if callback provided and verbose mode."""
        if not callback:
            return
        if not self.verbose:
            return

        event = EventData(
            event_type=event_type,
            request_id=request_id,
            timestamp=time.time(),
            **kwargs
        )
        callback(event)

    def _emit_streaming_event(
        self,
        on_event: Optional[Callable],
        request: LLMRequest,
        state: Dict,
        start_time: float,
        is_final: bool = False
    ):
        """Emit streaming progress event with ETA calculation."""
        if not on_event:
            return
        if not self.verbose and not is_final:
            return

        tokens = state['tokens_so_far']
        elapsed = time.time() - start_time

        # Calculate rate and ETA (defensive against division by zero)
        if elapsed < 0.01:
            tokens_per_second = 0.0
        else:
            tokens_per_second = tokens / elapsed

        # Estimate total output tokens based on OCR input size
        # Data analysis: corrected output is 73% of OCR input (±11% stdev)
        ocr_tokens = request.metadata.get('ocr_tokens') if request.metadata else None
        if ocr_tokens and ocr_tokens > 0:
            estimated_total = int(ocr_tokens * 0.73)
        else:
            # Fallback if OCR tokens not available (median from analysis)
            estimated_total = request.max_tokens or 1200
        remaining_tokens = max(0, estimated_total - tokens)

        if tokens_per_second > 0:
            eta_seconds = remaining_tokens / tokens_per_second
        else:
            eta_seconds = None

        # Final event should show ETA = 0
        if is_final:
            eta_seconds = 0.0

        # Build display message
        page_id = request.id.replace('page_', 'p')
        if eta_seconds is not None:
            message = f"{page_id}: {tokens} tokens, {tokens_per_second:.0f} tok/s, ETA {eta_seconds:.1f}s"
        else:
            message = f"{page_id}: {tokens} tokens, {tokens_per_second:.0f} tok/s"

        # Extract stage from request metadata (if present)
        stage = request.metadata.get('stage') if request.metadata else None

        self._emit_event(
            on_event,
            LLMEvent.STREAMING,
            request_id=request.id,
            tokens_received=tokens,
            tokens_per_second=tokens_per_second,
            eta_seconds=eta_seconds,
            retry_count=request._retry_count,
            stage=stage,
            message=message
        )

    def _finalize_streaming_response(
        self,
        state: Dict,
        request: LLMRequest
    ) -> Tuple[str, Dict, float, Optional[float]]:
        """Build final response from streaming state."""
        complete_response = ''.join(state['full_content'])

        # Use actual usage if available, otherwise estimate
        if state['actual_usage']:
            usage = state['actual_usage']
        else:
            # Fallback to char-based estimate
            prompt_chars = sum(len(m.get('content', '')) for m in request.messages)
            completion_chars = len(complete_response)

            usage = {
                'prompt_tokens': prompt_chars // CHARS_PER_TOKEN_ESTIMATE,
                'completion_tokens': completion_chars // CHARS_PER_TOKEN_ESTIMATE,
                '_estimated': True  # Flag that this is an estimate
            }

            # Log warning that we're using estimates
            logger.warning(
                f"No usage data in SSE stream for request {request.id}, using estimate. "
                f"Cost tracking may be inaccurate.",
                extra={
                    'request_id': request.id,
                    'estimated_tokens': usage
                }
            )

        # Calculate cost
        cost = self.llm_client.cost_calculator.calculate_cost(
            request.model,  # Use original model for cost calc
            usage['prompt_tokens'],
            usage['completion_tokens'],
            num_images=len(request.images) if request.images else 0
        )

        # Calculate TTFT if first token was received
        ttft = None
        if state['first_token_time'] is not None:
            ttft = state['first_token_time'] - state['start_time']

        return complete_response, usage, cost, ttft
