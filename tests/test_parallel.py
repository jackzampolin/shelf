"""
Tests for parallel processing utilities.

Tests ParallelProcessor and RateLimiter without mocks - real concurrency tests.
"""

import pytest
import time
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.parallel import ParallelProcessor, RateLimiter


def test_rate_limiter():
    """Test that rate limiter enforces call frequency."""
    limiter = RateLimiter(calls_per_minute=60)  # 1 call per second

    # First call should be immediate
    start = time.time()
    limiter.wait()
    first_duration = time.time() - start
    assert first_duration < 0.1, "First call should be immediate"

    # Second call should wait ~1 second
    start = time.time()
    limiter.wait()
    second_duration = time.time() - start
    assert 0.9 < second_duration < 1.2, f"Second call should wait ~1s, waited {second_duration}s"


def test_parallel_processor_basic():
    """Test basic parallel processing with mock worker."""
    def worker(item):
        """Simple worker that doubles a number."""
        return {'result': item * 2, 'cost': 0.01}

    processor = ParallelProcessor(
        max_workers=4,
        description="Test processing"
    )

    items = list(range(10))
    results = processor.process(
        items=items,
        worker_func=worker,
        progress_interval=5
    )

    assert len(results) == 10, "Should process all items"
    assert all('result' in r for r in results), "All results should have 'result' key"

    # Results might be out of order due to parallel execution
    result_values = sorted([r['result'] for r in results])
    expected_values = [i * 2 for i in range(10)]
    assert result_values == expected_values, "Results should be correct"

    # Check stats
    assert processor.stats['processed'] == 10
    assert processor.stats['succeeded'] == 10
    assert processor.stats['failed'] == 0
    assert processor.stats['total_cost'] == pytest.approx(0.10, abs=0.01)


def test_parallel_processor_with_errors():
    """Test that ParallelProcessor handles errors gracefully."""
    def worker(item):
        """Worker that fails on even numbers."""
        if item % 2 == 0:
            raise ValueError(f"Item {item} is even")
        return {'result': item * 2, 'cost': 0.01}

    processor = ParallelProcessor(
        max_workers=4,
        description="Test with errors"
    )

    items = list(range(10))
    results = processor.process(
        items=items,
        worker_func=worker,
        progress_interval=5
    )

    # Should have 5 successful results (odd numbers)
    assert len(results) == 5, "Should have 5 successful results"

    # Check stats
    assert processor.stats['processed'] == 10
    assert processor.stats['succeeded'] == 5
    assert processor.stats['failed'] == 5


def test_parallel_processor_with_rate_limit():
    """Test ParallelProcessor with rate limiting."""
    call_times = []

    def worker(item):
        """Worker that records call time."""
        call_times.append(time.time())
        return {'result': item}

    processor = ParallelProcessor(
        max_workers=10,  # High workers
        rate_limit=60,   # But rate limit to 60/min (1/sec)
        description="Test with rate limiting"
    )

    items = list(range(5))
    start = time.time()
    results = processor.process(
        items=items,
        worker_func=worker,
        progress_interval=1
    )
    duration = time.time() - start

    assert len(results) == 5

    # With rate limit of 1/sec, 5 items should take ~4-5 seconds
    # (first is immediate, then 1s wait between each)
    assert 3.5 < duration < 6.0, f"Should take ~4-5s with rate limit, took {duration}s"


def test_parallel_processor_empty_items():
    """Test ParallelProcessor with empty item list."""
    def worker(item):
        return {'result': item}

    processor = ParallelProcessor(
        max_workers=4,
        description="Test empty"
    )

    results = processor.process(
        items=[],
        worker_func=worker
    )

    assert results == []
    assert processor.stats['processed'] == 0


def test_parallel_processor_progress_reporting():
    """Test that progress is reported at correct intervals."""
    processed_counts = []

    class MockLogger:
        def info(self, msg):
            """Capture progress messages."""
            if "Progress:" in msg:
                # Extract count from "Progress: X/Y items processed"
                parts = msg.split()
                count = int(parts[1].split('/')[0])
                processed_counts.append(count)

    def worker(item):
        time.sleep(0.01)  # Small delay to ensure sequential processing
        return {'result': item}

    processor = ParallelProcessor(
        max_workers=2,
        logger=MockLogger(),
        description="Test progress"
    )

    # Process 25 items with progress_interval=10
    results = processor.process(
        items=list(range(25)),
        worker_func=worker,
        progress_interval=10
    )

    assert len(results) == 25
    # Should log at 10 and 20 (not 30 since we only have 25 items)
    assert 10 in processed_counts
    assert 20 in processed_counts
    assert 30 not in processed_counts
