import time
from dataclasses import dataclass
from typing import List, Dict, Optional

from infra.llm.client import LLMClient
from infra.llm.models import LLMResult
from infra.llm.display import DisplayStats, print_phase_complete, print_phase_error, SingleCallSpinner
from infra.pipeline.status import PhaseStatusTracker


@dataclass
class LLMSingleCallConfig:
    """Configuration for a single LLM call with automatic metrics and display."""
    tracker: PhaseStatusTracker
    model: str
    call_name: str
    metric_key: str
    show_display: bool = True  # Set to False to suppress console output


class LLMSingleCall:
    """Execute a single LLM call with automatic metrics tracking and console output.

    Mirrors LLMBatchProcessor but for single calls:
    - Takes PhaseStatusTracker for logging, metrics, storage access
    - Automatically records metrics
    - Prints nice console output when done
    """

    def __init__(self, config: LLMSingleCallConfig):
        self.config = config
        self.tracker = config.tracker
        self.logger = config.tracker.logger
        self.metrics_manager = config.tracker.metrics_manager
        self.model = config.model
        self.call_name = config.call_name
        self.metric_key = config.metric_key

        self.client = LLMClient(logger=self.logger)

    def call(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict] = None,
        images: Optional[List] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        timeout: int = 120,
    ) -> LLMResult:
        """Execute the LLM call with automatic metrics and display."""
        start_time = time.time()

        # Show spinner while waiting for response
        if self.config.show_display:
            with SingleCallSpinner(self.call_name):
                result = self.client.call(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    response_format=response_format,
                    images=images,
                )
        else:
            result = self.client.call(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                response_format=response_format,
                images=images,
            )

        elapsed = time.time() - start_time

        # Record metrics automatically
        result.record_to_metrics(
            metrics_manager=self.metrics_manager,
            key=self.metric_key,
            accumulate=True
        )

        # Display summary (if enabled)
        if self.config.show_display:
            self._display_summary(result, elapsed)

        return result

    def _display_summary(self, result: LLMResult, elapsed: float):
        """Display summary line matching batch format."""
        if result.success:
            print_phase_complete(self.call_name, DisplayStats(
                completed=1,
                total=1,
                time_seconds=elapsed,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                reasoning_tokens=result.reasoning_tokens,
                cost_usd=result.cost_usd,
            ))
        else:
            print_phase_error(self.call_name, result.error_message or "Unknown error")
