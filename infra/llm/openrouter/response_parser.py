#!/usr/bin/env python3
"""
OpenRouter response parsing with defensive malformed response handling.

Extracts content, usage, tool calls from API responses.
Logs full malformed responses for debugging.
"""

import logging
import requests
from typing import Dict, Any, Tuple, Optional, List

logger = logging.getLogger(__name__)


class MalformedResponseError(requests.exceptions.HTTPError):
    """Raised when OpenRouter returns HTTP 200 but malformed JSON."""
    pass


class ResponseParser:
    """
    Parses OpenRouter API responses.

    Responsibility: Extract data from raw responses
    - Parse chat completions
    - Parse tool calling responses
    - Handle malformed responses defensively

    Does NOT handle:
    - HTTP requests (see transport.py)
    - Retries (see retry_policy.py)
    - Cost calculation (see pricing.py)
    """

    @staticmethod
    def parse_chat_completion(result: Dict[str, Any], model: str) -> Tuple[str, Dict[str, Any]]:
        """
        Extract content and usage from chat completion response.

        Args:
            result: Raw JSON response from OpenRouter
            model: Model name (for logging)

        Returns:
            Tuple of (content, usage)

        Raises:
            MalformedResponseError: If response missing required keys
        """
        try:
            content = result['choices'][0]['message']['content']
            usage = result.get('usage', {})
            return content, usage

        except (KeyError, IndexError, TypeError) as e:
            logger.error(
                "Malformed API response from OpenRouter (missing expected keys)",
                model=model,
                error_type=type(e).__name__,
                error=str(e),
                response_keys=list(result.keys()) if isinstance(result, dict) else type(result).__name__,
                has_choices='choices' in result if isinstance(result, dict) else False,
                full_response=result
            )

            # Create synthetic 502 error to trigger retry logic
            mock_response = type('MockResponse', (), {
                'status_code': 502,
                'text': f'Malformed API response: {type(e).__name__}',
                '_error_data_cache': None
            })()

            raise MalformedResponseError(
                f"502 Bad Gateway: Malformed API response (missing '{e.args[0] if e.args else 'expected key'}')",
                response=mock_response
            )

    @staticmethod
    def parse_tool_completion(
        result: Dict[str, Any],
        model: str
    ) -> Tuple[Optional[str], Dict[str, Any], Optional[List[Dict]], Optional[List[Dict]]]:
        """
        Extract content, usage, tool_calls, reasoning from tool calling response.

        Args:
            result: Raw JSON response from OpenRouter
            model: Model name (for logging)

        Returns:
            Tuple of (content, usage, tool_calls, reasoning_details)
            - content: Can be None if model only calls tools
            - tool_calls: None if no tools called
            - reasoning_details: None if no reasoning data

        Raises:
            MalformedResponseError: If response missing required keys
        """
        try:
            message = result['choices'][0]['message']
            content = message.get('content')  # Can be None if only tool calls
            tool_calls = message.get('tool_calls')  # None if no tools called
            reasoning_details = message.get('reasoning_details')  # None if no reasoning
            usage = result.get('usage', {})

            return content, usage, tool_calls, reasoning_details

        except (KeyError, IndexError, TypeError) as e:
            logger.error(
                "Malformed API response from OpenRouter (missing expected keys)",
                model=model,
                error_type=type(e).__name__,
                error=str(e),
                response_keys=list(result.keys()) if isinstance(result, dict) else type(result).__name__,
                has_choices='choices' in result if isinstance(result, dict) else False,
                full_response=result
            )

            # Create synthetic 502 error to trigger retry logic
            mock_response = type('MockResponse', (), {
                'status_code': 502,
                'text': f'Malformed API response: {type(e).__name__}',
                '_error_data_cache': None
            })()

            raise MalformedResponseError(
                f"502 Bad Gateway: Malformed API response (missing '{e.args[0] if e.args else 'expected key'}')",
                response=mock_response
            )
