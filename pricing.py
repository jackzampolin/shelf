#!/usr/bin/env python3
"""
Dynamic model pricing fetcher for OpenRouter API.

Fetches current pricing data from OpenRouter's models API endpoint
and provides utilities for calculating costs from token usage.
"""

import os
import json
import requests
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv()


class PricingCache:
    """
    Cache for model pricing data with automatic refresh.

    Caches pricing data to avoid excessive API calls while ensuring
    we stay up-to-date (default: 24 hour cache).
    """

    def __init__(self, cache_dir: Path = None, cache_ttl_hours: int = 24):
        """
        Initialize pricing cache.

        Args:
            cache_dir: Directory to store cache file (default: ~/.cache/ar-research)
            cache_ttl_hours: Hours before cache expires (default: 24)
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "ar-research"

        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "openrouter_pricing.json"
        self.cache_ttl = timedelta(hours=cache_ttl_hours)

        # Get API key
        self.api_key = os.getenv('OPEN_ROUTER_API_KEY') or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("OPEN_ROUTER_API_KEY or OPENROUTER_API_KEY not found in environment")

    def _is_cache_valid(self) -> bool:
        """Check if cache exists and is not expired."""
        if not self.cache_file.exists():
            return False

        try:
            with open(self.cache_file) as f:
                cache = json.load(f)

            cached_time = datetime.fromisoformat(cache.get('cached_at', ''))
            age = datetime.now() - cached_time

            return age < self.cache_ttl
        except (json.JSONDecodeError, ValueError, KeyError):
            return False

    def _fetch_from_api(self) -> Dict:
        """Fetch current pricing from OpenRouter API."""
        url = "https://openrouter.ai/api/v1/models"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()

        # Extract pricing into a simpler format
        pricing_map = {}

        for model in data.get('data', []):
            model_id = model.get('id')
            pricing = model.get('pricing', {})

            if model_id and pricing:
                pricing_map[model_id] = {
                    'prompt': float(pricing.get('prompt', '0')),  # USD per token
                    'completion': float(pricing.get('completion', '0')),  # USD per token
                    'request': float(pricing.get('request', '0')),  # USD per request
                    'image': float(pricing.get('image', '0')),  # USD per image
                }

        return pricing_map

    def _save_cache(self, pricing_map: Dict):
        """Save pricing data to cache file."""
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'pricing': pricing_map
        }

        with open(self.cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)

    def _load_cache(self) -> Dict:
        """Load pricing data from cache file."""
        with open(self.cache_file) as f:
            cache = json.load(f)

        return cache.get('pricing', {})

    def get_pricing(self, refresh: bool = False) -> Dict:
        """
        Get current model pricing.

        Args:
            refresh: Force refresh from API even if cache is valid

        Returns:
            Dictionary mapping model IDs to pricing info
        """
        if not refresh and self._is_cache_valid():
            return self._load_cache()

        # Fetch from API
        pricing_map = self._fetch_from_api()
        self._save_cache(pricing_map)

        return pricing_map

    def get_model_pricing(self, model_id: str, refresh: bool = False) -> Optional[Dict]:
        """
        Get pricing for a specific model.

        Args:
            model_id: OpenRouter model ID (e.g., 'openai/gpt-4o-mini')
            refresh: Force refresh from API

        Returns:
            Pricing dict with 'prompt', 'completion', 'request', 'image' keys
            or None if model not found
        """
        pricing = self.get_pricing(refresh=refresh)
        return pricing.get(model_id)


class CostCalculator:
    """Utility for calculating costs from token usage."""

    def __init__(self, pricing_cache: PricingCache = None):
        """
        Initialize cost calculator.

        Args:
            pricing_cache: PricingCache instance (creates new one if None)
        """
        self.pricing_cache = pricing_cache or PricingCache()

    def calculate_cost(
        self,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        num_requests: int = 1,
        num_images: int = 0
    ) -> float:
        """
        Calculate cost for a given usage.

        Args:
            model_id: OpenRouter model ID
            prompt_tokens: Number of input tokens
            completion_tokens: Number of output tokens
            num_requests: Number of API requests (default: 1)
            num_images: Number of images processed (default: 0)

        Returns:
            Cost in USD
        """
        pricing = self.pricing_cache.get_model_pricing(model_id)

        if not pricing:
            # Fallback: return 0 if pricing not found (with warning)
            print(f"⚠️  Warning: Pricing not found for model '{model_id}', cost will be $0.00")
            return 0.0

        # Calculate component costs
        prompt_cost = prompt_tokens * pricing['prompt']
        completion_cost = completion_tokens * pricing['completion']
        request_cost = num_requests * pricing['request']
        image_cost = num_images * pricing['image']

        return prompt_cost + completion_cost + request_cost + image_cost

    def format_cost_breakdown(
        self,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        num_requests: int = 1,
        num_images: int = 0
    ) -> str:
        """
        Get detailed cost breakdown as formatted string.

        Returns:
            Multi-line string with cost breakdown
        """
        pricing = self.pricing_cache.get_model_pricing(model_id)

        if not pricing:
            return f"Pricing not available for {model_id}"

        prompt_cost = prompt_tokens * pricing['prompt']
        completion_cost = completion_tokens * pricing['completion']
        request_cost = num_requests * pricing['request']
        image_cost = num_images * pricing['image']
        total = prompt_cost + completion_cost + request_cost + image_cost

        lines = [
            f"Cost Breakdown for {model_id}:",
            f"  Prompt tokens:     {prompt_tokens:,} × ${pricing['prompt']:.6f} = ${prompt_cost:.4f}",
            f"  Completion tokens: {completion_tokens:,} × ${pricing['completion']:.6f} = ${completion_cost:.4f}",
        ]

        if num_requests > 1:
            lines.append(f"  Requests:          {num_requests} × ${pricing['request']:.6f} = ${request_cost:.4f}")

        if num_images > 0:
            lines.append(f"  Images:            {num_images} × ${pricing['image']:.6f} = ${image_cost:.4f}")

        lines.append(f"  Total:             ${total:.4f}")

        return "\n".join(lines)


# Convenience functions for common use cases

def get_pricing_for_model(model_id: str, refresh: bool = False) -> Optional[Dict]:
    """
    Get current pricing for a model.

    Args:
        model_id: OpenRouter model ID
        refresh: Force API refresh

    Returns:
        Pricing dict or None
    """
    cache = PricingCache()
    return cache.get_model_pricing(model_id, refresh=refresh)


def calculate_cost(
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    num_requests: int = 1,
    num_images: int = 0
) -> float:
    """
    Calculate cost for given usage (convenience function).

    Args:
        model_id: OpenRouter model ID
        prompt_tokens: Input tokens
        completion_tokens: Output tokens
        num_requests: Number of requests
        num_images: Number of images

    Returns:
        Cost in USD
    """
    calculator = CostCalculator()
    return calculator.calculate_cost(
        model_id,
        prompt_tokens,
        completion_tokens,
        num_requests,
        num_images
    )


if __name__ == "__main__":
    """CLI for testing pricing functionality."""
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python pricing.py list                          # List all models")
        print("  python pricing.py <model-id>                    # Show pricing for model")
        print("  python pricing.py refresh                       # Force refresh cache")
        print()
        print("Examples:")
        print("  python pricing.py openai/gpt-4o-mini")
        print("  python pricing.py anthropic/claude-sonnet-4.5")
        sys.exit(1)

    command = sys.argv[1]

    cache = PricingCache()

    if command == "list":
        pricing = cache.get_pricing()
        print(f"\n📊 Available Models ({len(pricing)} total):\n")

        for model_id in sorted(pricing.keys()):
            p = pricing[model_id]
            print(f"  {model_id}")
            print(f"    Prompt:     ${p['prompt']:.8f}/token")
            print(f"    Completion: ${p['completion']:.8f}/token")
            if p['request'] > 0:
                print(f"    Request:    ${p['request']:.8f}/request")
            if p['image'] > 0:
                print(f"    Image:      ${p['image']:.8f}/image")
            print()

    elif command == "refresh":
        print("🔄 Refreshing pricing cache from OpenRouter API...")
        pricing = cache.get_pricing(refresh=True)
        print(f"✅ Cached {len(pricing)} models")
        print(f"   Cache location: {cache.cache_file}")

    else:
        # Assume it's a model ID
        model_id = command
        pricing = cache.get_model_pricing(model_id)

        if not pricing:
            print(f"❌ Model '{model_id}' not found")
            print("\nRun 'python pricing.py list' to see available models")
            sys.exit(1)

        print(f"\n💰 Pricing for {model_id}:")
        print(f"   Prompt:     ${pricing['prompt']:.8f} per token (${pricing['prompt'] * 1_000_000:.2f}/M)")
        print(f"   Completion: ${pricing['completion']:.8f} per token (${pricing['completion'] * 1_000_000:.2f}/M)")

        if pricing['request'] > 0:
            print(f"   Request:    ${pricing['request']:.6f} per request")

        if pricing['image'] > 0:
            print(f"   Image:      ${pricing['image']:.6f} per image")

        # Example calculation
        print(f"\n📝 Example (100K prompt, 10K completion):")
        calc = CostCalculator(cache)
        cost = calc.calculate_cost(model_id, 100_000, 10_000)
        print(f"   Total cost: ${cost:.4f}")
