#!/usr/bin/env python3
import logging
import requests
from typing import Dict, Any, Optional

from infra.config import Config

class OpenRouterTransport:
    def __init__(self, logger: Optional[logging.Logger] = None, site_url: str = None, site_name: str = None):
        self.logger = logger or logging.getLogger(__name__)
        self.api_key = Config.openrouter_api_key
        self.site_url = site_url or Config.openrouter_site_url
        self.site_name = site_name or Config.openrouter_site_name
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def post(self, payload: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
        model = payload.get('model', 'unknown')
        has_images = any(
            isinstance(msg.get('content'), list) and
            any(c.get('type') == 'image_url' for c in msg['content'])
            for msg in payload.get('messages', [])
        )

        self.logger.debug(
            f"OpenRouter API request",
            model=model,
            timeout=timeout,
            has_tools='tools' in payload,
            has_images=has_images,
            num_messages=len(payload.get('messages', []))
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name
        }

        response = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=timeout
        )

        self.logger.debug(
            f"OpenRouter API response",
            model=model,
            status_code=response.status_code,
            ok=response.ok
        )

        if not response.ok:
            try:
                response._error_data_cache = response.json()
                self.logger.debug(
                    f"Cached error response data for retry logic",
                    model=model,
                    status_code=response.status_code
                )
            except:
                response._error_data_cache = None

        response.raise_for_status()

        return response.json()
