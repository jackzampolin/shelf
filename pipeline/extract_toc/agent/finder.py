import json
import time
from typing import Optional, Tuple, Dict, Any

from infra.storage.book_storage import BookStorage
from infra.llm.client import LLMClient
from infra.llm.agent import AgentClient, AgentEvent, AgentProgressDisplay
from infra.pipeline.logger import PipelineLogger
from infra.config import Config
from ..schemas import PageRange
from ..storage import ExtractTocStageStorage

from .tools import TocFinderTools, TocFinderResult
from .prompts import SYSTEM_PROMPT, build_user_prompt


class TocFinderAgent:

    def __init__(
        self,
        storage: BookStorage,
        logger: Optional[PipelineLogger] = None,
        max_iterations: int = 15,
        verbose: bool = True
    ):
        self.storage = storage
        self.logger = logger
        self.max_iterations = max_iterations
        self.verbose = verbose

        self.llm_client = LLMClient()

        self.metadata = storage.load_metadata()
        self.scan_id = storage.scan_id
        self.total_pages = self.metadata.get('total_pages', 0)

        stage_storage = storage.stage('extract-toc')
        log_dir = stage_storage.output_dir / 'logs' / 'toc_finder'
        self.agent_client = AgentClient(
            max_iterations=max_iterations,
            log_dir=log_dir,
            logger=logger,
            metrics_manager=stage_storage.metrics_manager,
            metrics_key_prefix="phase1_",
            verbose=verbose
        )

        self.stage_storage_helper = ExtractTocStageStorage(stage_name='extract-toc')
        self.tools = TocFinderTools(
            storage=storage,
            agent_client=self.agent_client,
            stage_storage=self.stage_storage_helper
        )

    def search(self) -> TocFinderResult:
        start_time = time.time()

        if self.verbose:
            print(f"\n🔍 Searching for Table of Contents in '{self.scan_id}'...")

        if self.logger:
            self.logger.info("Starting grep-informed ToC finder",
                           scan_id=self.scan_id,
                           total_pages=self.total_pages)

        initial_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(self.scan_id, self.total_pages)}
        ]

        def is_complete(messages):
            return self.tools._pending_result is not None

        progress = AgentProgressDisplay(max_iterations=self.max_iterations) if self.verbose else None

        if progress:
            with progress:
                agent_result = self.agent_client.run(
                    llm_client=self.llm_client,
                    model=Config.text_model_expensive,
                    initial_messages=initial_messages,
                    tools=self.tools.get_tools(),
                    execute_tool=self.tools.execute_tool,
                    is_complete=is_complete,
                    on_event=progress.on_event,
                    temperature=0.0
                )
        else:
            agent_result = self.agent_client.run(
                llm_client=self.llm_client,
                model=Config.text_model_expensive,
                initial_messages=initial_messages,
                tools=self.tools.get_tools(),
                execute_tool=self.tools.execute_tool,
                is_complete=is_complete,
                on_event=None,
                temperature=0.0
            )

        if progress and agent_result.success:
            elapsed = time.time() - start_time
            progress.total_prompt_tokens = agent_result.total_prompt_tokens
            progress.total_completion_tokens = agent_result.total_completion_tokens
            progress.total_reasoning_tokens = agent_result.total_reasoning_tokens
            print()
            print(progress.render_summary(elapsed))

        if agent_result.success and self.tools._pending_result:
            final_result = self.tools._pending_result
            final_result.total_cost_usd = agent_result.total_cost_usd
            final_result.execution_time_seconds = agent_result.execution_time_seconds
            final_result.iterations = agent_result.iterations
            final_result.total_prompt_tokens = agent_result.total_prompt_tokens
            final_result.total_completion_tokens = agent_result.total_completion_tokens
            final_result.total_reasoning_tokens = agent_result.total_reasoning_tokens
            final_result.pages_checked = len(self.agent_client.images)
        else:
            final_result = TocFinderResult(
                toc_found=False,
                toc_page_range=None,
                confidence=0.0,
                search_strategy_used="agent_error" if not agent_result.success else "max_iterations",
                pages_checked=len(self.agent_client.images),
                total_cost_usd=agent_result.total_cost_usd,
                execution_time_seconds=agent_result.execution_time_seconds,
                iterations=agent_result.iterations,
                total_prompt_tokens=agent_result.total_prompt_tokens,
                total_completion_tokens=agent_result.total_completion_tokens,
                total_reasoning_tokens=agent_result.total_reasoning_tokens,
                reasoning=agent_result.error_message or "Search incomplete"
            )

        elapsed = time.time() - start_time

        if self.verbose:
            if final_result.toc_found:
                range_str = f"{final_result.toc_page_range.start_page}-{final_result.toc_page_range.end_page}"
                print(f"\n   ✅ ToC found: pages {range_str}")
                print(f"      Strategy: {final_result.search_strategy_used}")
                print(f"      Confidence: {final_result.confidence:.2f}")
            else:
                print(f"\n   ⊘ No ToC found")
                print(f"      Reason: {final_result.reasoning}")

            print(f"      Cost: ${final_result.total_cost_usd:.4f}")
            print(f"      Time: {elapsed:.1f}s")
            print(f"      Iterations: {agent_result.iterations}")
            if agent_result.run_log_path:
                print(f"      Agent log: {agent_result.run_log_path}")

        if self.logger:
            self.logger.info("ToC search complete",
                           toc_found=final_result.toc_found,
                           strategy=final_result.search_strategy_used,
                           cost=f"${final_result.total_cost_usd:.4f}",
                           iterations=agent_result.iterations,
                           elapsed=f"{elapsed:.1f}s",
                           run_log=str(agent_result.run_log_path) if agent_result.run_log_path else None)

        return final_result


def find_toc_pages(
    storage: BookStorage,
    logger: Optional[PipelineLogger] = None,
    max_iterations: int = 15,
    verbose: bool = True
) -> Tuple[Optional[PageRange], Dict[str, Any]]:
    """
    Find ToC pages using grep-informed vision agent.

    Returns:
        Tuple of (toc_range, metrics) where metrics contains:
        - cost_usd: Total cost across all iterations
        - time_seconds: Total execution time
        - iterations: Number of agent iterations
        - prompt_tokens: Total prompt tokens across all iterations
        - completion_tokens: Total completion tokens across all iterations
        - reasoning_tokens: Total reasoning tokens (Grok only)
    """
    agent = TocFinderAgent(
        storage=storage,
        logger=logger,
        max_iterations=max_iterations,
        verbose=verbose
    )

    result = agent.search()

    metrics = {
        'cost_usd': result.total_cost_usd,
        'time_seconds': result.execution_time_seconds,
        'iterations': result.iterations,
        'prompt_tokens': result.total_prompt_tokens,
        'completion_tokens': result.total_completion_tokens,
        'reasoning_tokens': result.total_reasoning_tokens,
    }

    if result.toc_found and result.toc_page_range:
        return result.toc_page_range, metrics
    else:
        return None, metrics
