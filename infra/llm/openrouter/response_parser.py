#!/usr/bin/env python3
import logging
from typing import Dict, Any, Tuple, Optional, List
from dataclasses import dataclass

from .errors import MalformedResponseError


@dataclass
class ParsedResponse:
    """
    Intermediate structure for parsed OpenRouter API responses.

    Provider-specific ResponseParser extracts raw API fields and maps them
    to this normalized structure. LLMClient then creates LLMResult from this.
    """
    content: Optional[str]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int
    model_used: str
    provider: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    reasoning_details: Optional[List[Dict]] = None

class ResponseParser:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    def parse_chat_completion(self, result: Dict[str, Any], model: str) -> ParsedResponse:
        try:
            content = result['choices'][0]['message']['content']
            usage = result.get('usage', {})

            # Extract and flatten token fields (normalize provider format)
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', 0)
            reasoning_tokens = usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)

            # Extract provider from model string (e.g., "openai/gpt-4" -> "openai")
            provider = model.split('/')[0] if '/' in model else None

            self.logger.debug(
                f"Parsed chat completion",
                model=model,
                provider=provider,
                content_length=len(content) if content else 0,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                reasoning_tokens=reasoning_tokens
            )

            return ParsedResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                reasoning_tokens=reasoning_tokens,
                model_used=model,
                provider=provider
            )

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
    ) -> ParsedResponse:
        try:
            message = result['choices'][0]['message']
            content = message.get('content')
            tool_calls = message.get('tool_calls')
            reasoning_details = message.get('reasoning_details')
            usage = result.get('usage', {})

            # Extract and flatten token fields (normalize provider format)
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', 0)
            reasoning_tokens = usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)

            # Extract provider from model string (e.g., "openai/gpt-4" -> "openai")
            provider = model.split('/')[0] if '/' in model else None

            self.logger.debug(
                f"Parsed tool completion",
                model=model,
                provider=provider,
                has_content=content is not None,
                content_length=len(content) if content else 0,
                num_tool_calls=len(tool_calls) if tool_calls else 0,
                has_reasoning=reasoning_details is not None,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                reasoning_tokens=reasoning_tokens
            )

            return ParsedResponse(
                content=content,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                reasoning_tokens=reasoning_tokens,
                model_used=model,
                provider=provider,
                tool_calls=tool_calls,
                reasoning_details=reasoning_details
            )

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
