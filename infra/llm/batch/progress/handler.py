import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infra.llm.batch.worker import WorkerPool
    from infra.llm.rate_limiter import RateLimiter

from .rollups import aggregate_batch_stats
from infra.llm.display_format import format_token_string


def create_progress_handler(
    progress_bar,
    progress_task,
    worker_pool: 'WorkerPool',
    rate_limiter: 'RateLimiter',
    metrics_manager,
    total_requests: int,
    start_time: float,
    batch_start_time: float,
    metric_prefix: str = None
):

    def handle_progress():
        batch_stats = aggregate_batch_stats(
            metrics_manager=metrics_manager,
            active_requests=worker_pool.get_active_requests(),
            total_requests=total_requests,
            rate_limit_status=rate_limiter.get_status(),
            batch_start_time=batch_start_time,
            metric_prefix=metric_prefix
        )

        elapsed = time.time() - start_time
        elapsed_mins = int(elapsed // 60)
        elapsed_secs = int(elapsed % 60)
        elapsed_str = f"{elapsed_mins}:{elapsed_secs:02d}"

        parts = [f"{batch_stats.completed}/{total_requests}"]

        # Throughput
        if batch_stats.requests_per_second > 0:
            parts.append(f"{batch_stats.requests_per_second:.1f}/s")

        # Time and ETA
        remaining = total_requests - batch_stats.completed
        if batch_stats.requests_per_second > 0 and remaining > 0:
            eta_seconds = remaining / batch_stats.requests_per_second
            eta_mins = int(eta_seconds // 60)
            eta_secs = int(eta_seconds % 60)
            parts.append(f"{elapsed_str} (ETA {eta_mins}:{eta_secs:02d})")
        else:
            parts.append(elapsed_str)

        # Tokens: in->out+r format with colors
        if batch_stats.total_prompt_tokens > 0 or batch_stats.total_completion_tokens > 0:
            token_str = format_token_string(
                batch_stats.total_prompt_tokens,
                batch_stats.total_completion_tokens,
                batch_stats.total_reasoning_tokens,
                colored=True
            )
            parts.append(token_str)

        # Cost
        parts.append(f"${batch_stats.total_cost_usd:.2f}")

        suffix = " • ".join(parts)
        progress_bar.update(progress_task, completed=batch_stats.completed, suffix=suffix)

    return handle_progress
