import json
import threading
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

class MetricsManager:
    def __init__(self, metrics_file: Path):
        self.metrics_file = Path(metrics_file)
        self._lock = threading.RLock()
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

    def get_metrics_by_prefix(self, prefix: str) -> Dict[str, Dict[str, Any]]:
        """
        Get individual metric records matching a prefix.

        Returns dict of {key: metric_record} for all keys starting with prefix.
        """
        with self._lock:
            return {
                key: entry
                for key, entry in self._state["metrics"].items()
                if key.startswith(prefix)
            }

    def get_cumulative_metrics(self, prefix: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            # Filter metrics based on prefix pattern
            # If prefix provided: "margin/page_" -> match "margin/page_0001", "margin/page_0002"
            # If no prefix: match "page_0001" or any key with "_page_" or "/page_"
            if prefix:
                page_metrics = {
                    key: entry
                    for key, entry in self._state["metrics"].items()
                    if key.startswith(prefix)
                }
            else:
                # Backward compatibility: match traditional patterns
                page_metrics = {
                    key: entry
                    for key, entry in self._state["metrics"].items()
                    if key.startswith("page_") or "_page_" in key or "/page_" in key
                }

            return {
                "total_requests": len(page_metrics),
                "total_cost_usd": sum(entry.get("cost_usd", 0.0) for entry in page_metrics.values()),
                "total_time_seconds": sum(entry.get("time_seconds", 0.0) for entry in page_metrics.values()),
                "total_prompt_tokens": sum(entry.get("prompt_tokens", 0) for entry in page_metrics.values()),
                "total_completion_tokens": sum(entry.get("completion_tokens", 0) for entry in page_metrics.values()),
                "total_reasoning_tokens": sum(entry.get("reasoning_tokens", 0) for entry in page_metrics.values()),
            }

    def get_aggregated(self) -> Dict[str, Any]:
        with self._lock:
            all_entries = list(self._state["metrics"].values())

            stage_runtime = self._state["metrics"].get("stage_runtime", {})

            total_input = sum(entry.get("input_tokens", 0) for entry in all_entries)
            total_output = sum(entry.get("output_tokens", 0) for entry in all_entries)
            total_reasoning = sum(entry.get("reasoning_tokens", 0) for entry in all_entries)

            result = {
                "total_cost_usd": self.get_total_cost(),
                "total_time_seconds": self.get_total_time(),
            }

            if stage_runtime:
                result["stage_runtime_seconds"] = stage_runtime.get("time_seconds", 0)

            if total_input > 0:
                result["total_input_tokens"] = total_input
            if total_output > 0:
                result["total_output_tokens"] = total_output
            if total_reasoning > 0:
                result["total_reasoning_tokens"] = total_reasoning

            return result

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
