"""
Tests for infra/pipeline/storage/metrics.py

Key behaviors to verify:
1. Record metrics with cost, time, tokens
2. Accumulate metrics (incremental updates)
3. Persistence - reload from disk
4. Aggregation methods
5. Thread safety (basic)
"""

import json
import pytest
from pathlib import Path

from infra.pipeline.storage.metrics import MetricsManager


class TestMetricsManagerBasics:
    """Test basic MetricsManager operations."""

    def test_record_creates_file(self, metrics_file):
        """Recording a metric should create the metrics file."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", cost_usd=0.01, time_seconds=1.5)

        assert metrics_file.exists()

    def test_record_and_get(self, metrics_file):
        """Should be able to record and retrieve metrics."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", cost_usd=0.01, time_seconds=1.5, tokens=100)

        result = mm.get("page_0001")

        assert result["cost_usd"] == 0.01
        assert result["time_seconds"] == 1.5
        assert result["tokens"] == 100

    def test_get_nonexistent_key(self, metrics_file):
        """Getting a nonexistent key should return None."""
        mm = MetricsManager(metrics_file)

        result = mm.get("nonexistent")

        assert result is None

    def test_record_overwrites_by_default(self, metrics_file):
        """Recording same key twice should overwrite."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", cost_usd=0.01)
        mm.record("page_0001", cost_usd=0.05)

        result = mm.get("page_0001")
        assert result["cost_usd"] == 0.05


class TestMetricsManagerAccumulate:
    """Test accumulation mode."""

    def test_accumulate_adds_values(self, metrics_file):
        """accumulate=True should add to existing values."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", cost_usd=0.01, time_seconds=1.0)
        mm.record("page_0001", cost_usd=0.02, time_seconds=2.0, accumulate=True)

        result = mm.get("page_0001")
        assert result["cost_usd"] == 0.03
        assert result["time_seconds"] == 3.0

    def test_accumulate_tokens(self, metrics_file):
        """Token accumulation should work."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", tokens=100)
        mm.record("page_0001", tokens=50, accumulate=True)

        result = mm.get("page_0001")
        assert result["tokens"] == 150

    def test_accumulate_custom_metrics(self, metrics_file):
        """Custom numeric metrics should accumulate."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", custom_metrics={"prompt_tokens": 100})
        mm.record("page_0001", custom_metrics={"prompt_tokens": 50}, accumulate=True)

        result = mm.get("page_0001")
        assert result["prompt_tokens"] == 150


class TestMetricsManagerPersistence:
    """Test that metrics persist across instances."""

    def test_metrics_persist_to_disk(self, metrics_file):
        """Metrics should be readable by a new instance."""
        mm1 = MetricsManager(metrics_file)
        mm1.record("page_0001", cost_usd=0.01, time_seconds=1.0)

        # Create new instance pointing to same file
        mm2 = MetricsManager(metrics_file)

        result = mm2.get("page_0001")
        assert result["cost_usd"] == 0.01

    def test_get_all_returns_all_metrics(self, metrics_file):
        """get_all should return all recorded metrics."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", cost_usd=0.01)
        mm.record("page_0002", cost_usd=0.02)
        mm.record("page_0003", cost_usd=0.03)

        all_metrics = mm.get_all()

        assert len(all_metrics) == 3
        assert "page_0001" in all_metrics
        assert "page_0002" in all_metrics
        assert "page_0003" in all_metrics


class TestMetricsManagerAggregation:
    """Test aggregation methods."""

    def test_get_total_cost(self, metrics_file):
        """get_total_cost should sum all cost_usd values."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", cost_usd=0.01)
        mm.record("page_0002", cost_usd=0.02)
        mm.record("page_0003", cost_usd=0.03)

        total = mm.get_total_cost()
        assert abs(total - 0.06) < 0.0001

    def test_get_total_time(self, metrics_file):
        """get_total_time should sum all time_seconds values."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", time_seconds=1.0)
        mm.record("page_0002", time_seconds=2.0)
        mm.record("page_0003", time_seconds=3.0)

        total = mm.get_total_time()
        assert total == 6.0

    def test_get_metrics_by_prefix(self, metrics_file):
        """get_metrics_by_prefix should filter by key prefix."""
        mm = MetricsManager(metrics_file)

        mm.record("ocr/page_0001", cost_usd=0.01)
        mm.record("ocr/page_0002", cost_usd=0.02)
        mm.record("fix/page_0001", cost_usd=0.05)

        ocr_metrics = mm.get_metrics_by_prefix("ocr/")

        assert len(ocr_metrics) == 2
        assert "ocr/page_0001" in ocr_metrics
        assert "fix/page_0001" not in ocr_metrics

    def test_get_cumulative_metrics(self, metrics_file):
        """get_cumulative_metrics should aggregate page metrics."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", cost_usd=0.01, time_seconds=1.0)
        mm.record("page_0002", cost_usd=0.02, time_seconds=2.0)

        cumulative = mm.get_cumulative_metrics()

        assert cumulative["total_requests"] == 2
        assert abs(cumulative["total_cost_usd"] - 0.03) < 0.0001
        assert cumulative["total_time_seconds"] == 3.0

    def test_get_aggregated_includes_stage_runtime(self, metrics_file):
        """get_aggregated should include stage_runtime if present."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", cost_usd=0.01)
        mm.record("stage_runtime", time_seconds=60.0)

        agg = mm.get_aggregated()

        assert agg["stage_runtime_seconds"] == 60.0


class TestMetricsManagerReset:
    """Test reset functionality."""

    def test_reset_clears_all_metrics(self, metrics_file):
        """reset should clear all metrics."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", cost_usd=0.01)
        mm.record("page_0002", cost_usd=0.02)

        mm.reset()

        assert mm.get_all() == {}
        assert mm.get_total_cost() == 0.0


class TestMetricsManagerEdgeCases:
    """Test edge cases and error handling."""

    def test_load_nonexistent_file(self, tmp_path):
        """Loading from nonexistent file should create empty state."""
        metrics_file = tmp_path / "nonexistent" / "metrics.json"

        mm = MetricsManager(metrics_file)

        assert mm.get_all() == {}

    def test_load_corrupted_file(self, tmp_path):
        """Loading corrupted JSON should not crash."""
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text("not valid json {{{")

        mm = MetricsManager(metrics_file)

        # Should have empty state
        assert mm.get_all() == {}

    def test_custom_metrics_override_on_non_accumulate(self, metrics_file):
        """Custom metrics should be overwritten without accumulate."""
        mm = MetricsManager(metrics_file)

        mm.record("page_0001", custom_metrics={"model": "gpt-4"})
        mm.record("page_0001", custom_metrics={"model": "gpt-3.5"})

        result = mm.get("page_0001")
        assert result["model"] == "gpt-3.5"
