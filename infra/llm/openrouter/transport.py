#!/usr/bin/env python3
import requests
from typing import Dict, Any

from infra.config import Config


class OpenRouterTransport:
    def __init__(self, site_url: str = None, site_name: str = None):
        self.api_key = Config.openrouter_api_key
        self.site_url = site_url or Config.openrouter_site_url
        self.site_name = site_name or Config.openrouter_site_name
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"

    def post(self, payload: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
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

        # Cache error data for retry logic (consumed by retry_policy.py)
        if not response.ok:
            try:
                response._error_data_cache = response.json()
            except:
                response._error_data_cache = None

        response.raise_for_status()

        return response.json()
