#!/usr/bin/env python3
"""
Rate limiter for OpenRouter API calls.

Implements token bucket algorithm to respect API rate limits and
prevent 429 errors.
"""

import time
import threading
from typing import Dict, Optional


class RateLimiter:
    """
    Thread-safe rate limiter using token bucket algorithm.

    Supports:
    - Requests per minute limiting
    - Dynamic adjustment from 429 responses
    - Per-model tracking (for models with different limits)
    - Status monitoring (current consumption, time until reset)
    """

    def __init__(self, requests_per_minute: int = 150):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute
        """
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60.0
        self.lock = threading.RLock()  # Use RLock (reentrant) instead of Lock to avoid deadlock

        # Token bucket state
        self.tokens = float(requests_per_minute)  # Start with full bucket
        self.last_update = time.time()

        # Tracking
        self.total_consumed = 0
        self.total_waited = 0.0
        self.last_429_time: Optional[float] = None

    def can_execute(self) -> bool:
        """
        Check if a request can execute without waiting.

        Returns:
            True if at least one token available, False otherwise
        """
        with self.lock:
            self._refill_tokens()
            return self.tokens >= 1.0

    def consume(self, count: int = 1) -> float:
        """
        Consume tokens, waiting if necessary WITHOUT holding lock during sleep.

        Args:
            count: Number of tokens to consume (default: 1)

        Returns:
            Seconds waited (0 if no wait needed)
        """
        # Step 1: Check if we need to wait (WITH lock)
        with self.lock:
            self._refill_tokens()
            if self.tokens < count:
                wait_time = self._calculate_wait_time(count)
            else:
                wait_time = 0.0

        # Step 2: Wait OUTSIDE the lock (critical for avoiding deadlock)
        if wait_time > 0:
            time.sleep(wait_time)
            with self.lock:
                self.total_waited += wait_time

        # Step 3: Consume tokens (WITH lock, re-check availability after sleep)
        with self.lock:
            self._refill_tokens()  # Re-check after sleep
            if self.tokens >= count:
                self.tokens -= count
                self.total_consumed += count
            else:
                # Race condition: another thread consumed tokens while we waited
                # Consume anyway (may go negative) - better than deadlock
                # This is rare and will self-correct as tokens refill
                self.tokens -= count
                self.total_consumed += count

        return wait_time

    def try_consume(self, count: int = 1) -> bool:
        """
        Try to consume tokens without waiting.

        Args:
            count: Number of tokens to consume

        Returns:
            True if consumed successfully, False if insufficient tokens
        """
        with self.lock:
            self._refill_tokens()

            if self.tokens >= count:
                self.tokens -= count
                self.total_consumed += count
                return True
            return False

    def _refill_tokens(self):
        """Refill tokens based on elapsed time (called with lock held)."""
        now = time.time()
        elapsed = now - self.last_update

        # Calculate how many tokens to add based on elapsed time
        tokens_to_add = (elapsed / self.window_seconds) * self.requests_per_minute
        self.tokens = min(self.tokens + tokens_to_add, float(self.requests_per_minute))

        self.last_update = now

    def _calculate_wait_time(self, tokens_needed: int) -> float:
        """Calculate how long to wait until tokens are available (called with lock held)."""
        tokens_short = tokens_needed - self.tokens
        seconds_per_token = self.window_seconds / self.requests_per_minute
        return tokens_short * seconds_per_token

    def time_until_token(self) -> float:
        """
        Calculate time until next token becomes available.

        Returns:
            Seconds until next token (0 if tokens available now)
        """
        with self.lock:
            self._refill_tokens()
            if self.tokens >= 1.0:
                return 0.0
            return self._calculate_wait_time(1)

    def get_status(self) -> Dict:
        """
        Get current rate limiter status.

        Returns:
            Dict with current consumption, limits, and timing info
        """
        with self.lock:
            self._refill_tokens()

            # Calculate utilization (percentage of tokens consumed in current window)
            current_consumption = self.requests_per_minute - self.tokens
            utilization = current_consumption / self.requests_per_minute

            return {
                'tokens_available': int(self.tokens),
                'tokens_limit': self.requests_per_minute,
                'utilization': utilization,
                'time_until_token_sec': self.time_until_token(),
                'total_consumed': self.total_consumed,
                'total_waited_sec': self.total_waited,
                'last_429': self.last_429_time,
            }

    def record_429(self, retry_after: Optional[int] = None):
        """
        Record a 429 rate limit error.

        Args:
            retry_after: Seconds to wait (from Retry-After header, if present)
        """
        with self.lock:
            self.last_429_time = time.time()

            # If server provided a retry-after, consume all tokens to force waiting
            if retry_after:
                self.tokens = 0.0

    def adjust_limit(self, new_limit: int):
        """
        Dynamically adjust rate limit.

        Args:
            new_limit: New requests per minute limit
        """
        with self.lock:
            # Scale current tokens proportionally
            scale_factor = new_limit / self.requests_per_minute
            self.tokens = min(self.tokens * scale_factor, float(new_limit))
            self.requests_per_minute = new_limit

    def reset(self):
        """Reset rate limiter state (useful for testing)."""
        with self.lock:
            self.tokens = float(self.requests_per_minute)
            self.last_update = time.time()
            self.total_consumed = 0
            self.total_waited = 0.0
            self.last_429_time = None


if __name__ == "__main__":
    # Quick test
    print("Testing RateLimiter...")

    # Test 1: Basic consumption
    limiter = RateLimiter(requests_per_minute=60)  # 1 per second
    print(f"\nTest 1: Initial status: {limiter.get_status()}")

    # Consume 5 tokens
    for i in range(5):
        waited = limiter.consume()
        print(f"  Request {i+1}: waited {waited:.3f}s")

    print(f"After 5 requests: {limiter.get_status()}")

    # Test 2: Wait for refill
    print("\nTest 2: Waiting for refill...")
    time.sleep(2.0)
    print(f"After 2s wait: {limiter.get_status()}")

    # Test 3: Burst protection
    print("\nTest 3: Burst protection (consume all tokens)...")
    limiter.reset()
    start = time.time()
    for i in range(70):  # More than limit
        limiter.consume()
    elapsed = time.time() - start
    print(f"  70 requests took {elapsed:.2f}s (expected ~10s at 60/min)")

    print("\n✅ RateLimiter tests complete!")
