import json
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional

from infra.config import Config

class PricingCache:
    def __init__(self, cache_dir: Path = None, cache_ttl_hours: int = 24):
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "scanshelf"

        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "openrouter_pricing.json"
        self.cache_ttl = timedelta(hours=cache_ttl_hours)

    def _is_cache_valid(self) -> bool:
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
        url = "https://openrouter.ai/api/v1/models"

        headers = {
            "Authorization": f"Bearer {Config.openrouter_api_key}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()

        pricing_map = {}

        for model in data.get('data', []):
            model_id = model.get('id')
            pricing = model.get('pricing', {})

            if model_id and pricing:
                pricing_map[model_id] = {
                    'prompt': float(pricing.get('prompt', '0')),
                    'completion': float(pricing.get('completion', '0')),
                    'request': float(pricing.get('request', '0')),
                    'image': float(pricing.get('image', '0')),
                }

        return pricing_map

    def _save_cache(self, pricing_map: Dict):
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'pricing': pricing_map
        }

        with open(self.cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)

    def _load_cache(self) -> Dict:
        with open(self.cache_file) as f:
            cache = json.load(f)

        return cache.get('pricing', {})

    def get_pricing(self, refresh: bool = False) -> Dict:
        if not refresh and self._is_cache_valid():
            return self._load_cache()

        pricing_map = self._fetch_from_api()
        self._save_cache(pricing_map)

        return pricing_map

    def get_model_pricing(self, model_id: str, refresh: bool = False) -> Optional[Dict]:
        pricing = self.get_pricing(refresh=refresh)
        return pricing.get(model_id)


class CostCalculator:
    def __init__(self, pricing_cache: PricingCache = None):
        self.pricing_cache = pricing_cache or PricingCache()

    def calculate_cost(
        self,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        num_requests: int = 1,
        num_images: int = 0
    ) -> float:
        pricing = self.pricing_cache.get_model_pricing(model_id)

        if not pricing:
            return 0.0

        prompt_cost = prompt_tokens * pricing['prompt']
        completion_cost = completion_tokens * pricing['completion']
        request_cost = num_requests * pricing['request']
        image_cost = num_images * pricing['image']

        return prompt_cost + completion_cost + request_cost + image_cost
