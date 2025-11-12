#!/usr/bin/env python3
import logging
from typing import Dict, Any, Tuple, Optional, List

from .errors import MalformedResponseError

class ResponseParser:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    def parse_chat_completion(self, result: Dict[str, Any], model: str) -> Tuple[str, Dict[str, Any]]:
        try:
            content = result['choices'][0]['message']['content']
            usage = result.get('usage', {})

            self.logger.debug(
                f"Parsed chat completion",
                model=model,
                content_length=len(content) if content else 0,
                prompt_tokens=usage.get('prompt_tokens', 0),
                completion_tokens=usage.get('completion_tokens', 0),
                reasoning_tokens=usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)
            )

            return content, usage

        except (KeyError, IndexError, TypeError) as e:
            self.logger.error(
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

    def parse_tool_completion(
        self,
        result: Dict[str, Any],
        model: str
    ) -> Tuple[Optional[str], Dict[str, Any], Optional[List[Dict]], Optional[List[Dict]]]:
        try:
            message = result['choices'][0]['message']
            content = message.get('content')
            tool_calls = message.get('tool_calls')
            reasoning_details = message.get('reasoning_details')
            usage = result.get('usage', {})

            self.logger.debug(
                f"Parsed tool completion",
                model=model,
                has_content=content is not None,
                content_length=len(content) if content else 0,
                num_tool_calls=len(tool_calls) if tool_calls else 0,
                has_reasoning=reasoning_details is not None,
                prompt_tokens=usage.get('prompt_tokens', 0),
                completion_tokens=usage.get('completion_tokens', 0),
                reasoning_tokens=usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)
            )

            return content, usage, tool_calls, reasoning_details

        except (KeyError, IndexError, TypeError) as e:
            self.logger.error(
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
