"""Key-value metrics storage for cost/time/token tracking"""

import json
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

class MetricsManager:

    def __init__(self, metrics_file: Path):

        self.metrics_file = Path(metrics_file)
        self._lock = threading.Lock()
        self._state = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "metrics": {}
        }

        self._load()

    def record(
        self,
        key: str,
        cost_usd: float = 0.0,
        time_seconds: float = 0.0,
        tokens: Optional[int] = None,
        custom_metrics: Optional[Dict[str, Any]] = None,
        accumulate: bool = False
    ) -> None:
        """
        Record metrics for a key.

        Note: Prefer passing everything in custom_metrics for consistency.
        See issue #91 for schema validation work.

        Args:
            key: Metric key (e.g., "page_0001")
            cost_usd: Cost in USD
            time_seconds: Time in seconds
            tokens: Token count
            custom_metrics: Additional metrics dict
            accumulate: If True, add to existing values; if False, replace
        """
        with self._lock:
            metrics_entry = self._state["metrics"].get(key, {}) if accumulate else {}

            if accumulate:
                metrics_entry["cost_usd"] = metrics_entry.get("cost_usd", 0.0) + cost_usd
                metrics_entry["time_seconds"] = metrics_entry.get("time_seconds", 0.0) + time_seconds
                if tokens is not None:
                    metrics_entry["tokens"] = metrics_entry.get("tokens", 0) + tokens
            else:
                metrics_entry["cost_usd"] = cost_usd
                metrics_entry["time_seconds"] = time_seconds
                if tokens is not None:
                    metrics_entry["tokens"] = tokens

            if custom_metrics:
                if accumulate:
                    for k, v in custom_metrics.items():
                        if k in metrics_entry and isinstance(v, (int, float)) and isinstance(metrics_entry[k], (int, float)):
                            metrics_entry[k] = metrics_entry[k] + v
                        else:
                            metrics_entry[k] = v
                else:
                    metrics_entry.update(custom_metrics)

            metrics_entry["updated_at"] = datetime.now().isoformat()

            self._state["metrics"][key] = metrics_entry
            self._state["updated_at"] = datetime.now().isoformat()
            self._save()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._state["metrics"].get(key)

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._state["metrics"])

    def get_total_cost(self) -> float:
        with self._lock:
            return sum(
                entry.get("cost_usd", 0.0)
                for entry in self._state["metrics"].values()
            )

    def get_total_time(self) -> float:
        with self._lock:
            return sum(
                entry.get("time_seconds", 0.0)
                for entry in self._state["metrics"].values()
            )

    def get_total_tokens(self) -> int:
        with self._lock:
            return sum(
                entry.get("tokens", 0)
                for entry in self._state["metrics"].values()
            )

    def keys(self) -> list:
        with self._lock:
            return list(self._state["metrics"].keys())

    def reset(self) -> None:
        with self._lock:
            self._state = {
                "version": "1.0",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "metrics": {}
            }
            self._save()

    def _load(self) -> None:
        if not self.metrics_file.exists():
            return

        try:
            with open(self.metrics_file, 'r') as f:
                loaded = json.load(f)

            if not isinstance(loaded, dict) or "metrics" not in loaded:
                return

            self._state = loaded

        except (json.JSONDecodeError, IOError):
            pass

    def _save(self) -> None:
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

        temp_file = self.metrics_file.with_suffix('.tmp')
        try:
            with open(temp_file, 'w') as f:
                json.dump(self._state, f, indent=2)

            temp_file.replace(self.metrics_file)

        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise
