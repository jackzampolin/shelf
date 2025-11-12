import time
import threading
from typing import Dict, Optional


class RateLimiter:
    def __init__(self, requests_per_minute: Optional[int] = None):
        self.requests_per_minute = requests_per_minute if requests_per_minute is not None else 150
        self.window_seconds = 60.0
        self.lock = threading.RLock()  # Use RLock (reentrant) instead of Lock to avoid deadlock

        self.tokens = float(self.requests_per_minute)  # Start with full bucket
        self.last_update = time.time()

        self.total_consumed = 0
        self.total_waited = 0.0
        self.last_429_time: Optional[float] = None

    def can_execute(self) -> bool:
        with self.lock:
            self._refill_tokens()
            return self.tokens >= 1.0

    def consume(self, count: int = 1) -> float:
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
        with self.lock:
            self._refill_tokens()

            if self.tokens >= count:
                self.tokens -= count
                self.total_consumed += count
                return True
            return False

    def _refill_tokens(self):
        now = time.time()
        elapsed = now - self.last_update

        tokens_to_add = (elapsed / self.window_seconds) * self.requests_per_minute
        self.tokens = min(self.tokens + tokens_to_add, float(self.requests_per_minute))

        self.last_update = now

    def _calculate_wait_time(self, tokens_needed: int) -> float:
        tokens_short = tokens_needed - self.tokens
        seconds_per_token = self.window_seconds / self.requests_per_minute
        return tokens_short * seconds_per_token

    def time_until_token(self) -> float:
        with self.lock:
            self._refill_tokens()
            if self.tokens >= 1.0:
                return 0.0
            return self._calculate_wait_time(1)

    def get_status(self) -> Dict:
        with self.lock:
            self._refill_tokens()

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
        with self.lock:
            self.last_429_time = time.time()

            if retry_after:
                self.tokens = 0.0

    def adjust_limit(self, new_limit: int):
        with self.lock:
            scale_factor = new_limit / self.requests_per_minute
            self.tokens = min(self.tokens * scale_factor, float(new_limit))
            self.requests_per_minute = new_limit

    def reset(self):
        with self.lock:
            self.tokens = float(self.requests_per_minute)
            self.last_update = time.time()
            self.total_consumed = 0
            self.total_waited = 0.0
            self.last_429_time = None