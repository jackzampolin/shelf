#!/usr/bin/env python3
import logging
import requests
from typing import Dict, Any, Tuple, Optional, List

logger = logging.getLogger(__name__)


class MalformedResponseError(Exception):
    """Raised when OpenRouter returns HTTP 200 but malformed JSON structure."""
    pass


class ResponseParser:
    @staticmethod
    def parse_chat_completion(result: Dict[str, Any], model: str) -> Tuple[str, Dict[str, Any]]:
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

            raise MalformedResponseError(
                f"Malformed API response from OpenRouter: missing '{e.args[0] if e.args else 'expected key'}'"
            )

    @staticmethod
    def parse_tool_completion(
        result: Dict[str, Any],
        model: str
    ) -> Tuple[Optional[str], Dict[str, Any], Optional[List[Dict]], Optional[List[Dict]]]:
        try:
            message = result['choices'][0]['message']
            content = message.get('content')
            tool_calls = message.get('tool_calls')
            reasoning_details = message.get('reasoning_details')
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

            raise MalformedResponseError(
                f"Malformed API response from OpenRouter: missing '{e.args[0] if e.args else 'expected key'}'"
            )
