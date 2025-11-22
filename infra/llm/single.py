import time
from dataclasses import dataclass
from typing import List, Dict, Optional, Any, Callable

from rich.text import Text
from rich.console import Console

from infra.llm.client import LLMClient
from infra.llm.models import LLMRequest, LLMResult
from infra.llm.display_format import format_token_string
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
        text = Text()

        if result.success:
            text.append("✅ ", style="green")
        else:
            text.append("❌ ", style="red")

        description = f"{self.call_name}"
        text.append(f"{description:<45}", style="")

        text.append(f" ({elapsed:4.1f}s)", style="dim")

        token_str = format_token_string(
            result.prompt_tokens,
            result.completion_tokens,
            result.reasoning_tokens
        )
        text.append(f" {token_str:>22}", style="cyan")

        cost_cents = result.cost_usd * 100
        text.append(f" {cost_cents:5.2f}¢", style="yellow")

        console = Console()
        console.print(text)
