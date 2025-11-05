import json
import time
from typing import Optional

from infra.storage.book_storage import BookStorage
from infra.llm.client import LLMClient
from infra.llm.agent import AgentClient, AgentProgressDisplay
from infra.pipeline.logger import PipelineLogger
from infra.config import Config
from ..schemas import PageRange
from ..storage import FindTocStageStorage

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

        stage_storage = storage.stage('find-toc')
        log_dir = stage_storage.output_dir / 'logs' / 'toc_finder'
        self.agent_client = AgentClient(
            max_iterations=max_iterations,
            log_dir=log_dir,
            logger=logger,
            metrics_manager=stage_storage.metrics_manager,
            metrics_key_prefix="toc_finder_",
            verbose=verbose
        )

        self.stage_storage_helper = FindTocStageStorage(stage_name='find-toc')
        self.tools = TocFinderTools(
            storage=storage,
            agent_client=self.agent_client,
            stage_storage=self.stage_storage_helper
        )

    def search(self) -> TocFinderResult:
        start_time = time.time()

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

        progress = AgentProgressDisplay(
            max_iterations=self.max_iterations,
            agent_name="ToC finder"
        ) if self.verbose else None

        # Run agent with or without progress display
        if progress:
            progress.__enter__()
            try:
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
            finally:
                # Don't exit yet - we want to update the result name first
                pass
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

        # Update progress display with result-specific name
        if progress:
            if final_result.toc_found:
                range_str = f"{final_result.toc_page_range.start_page}-{final_result.toc_page_range.end_page}"
                progress.set_result_name(f"ToC found: pages {range_str}")
            else:
                progress.set_result_name(f"ToC search failed")

            # Now exit the progress display
            progress.__exit__(None, None, None)

        # Print failure reason if not found
        if self.verbose and not final_result.toc_found:
            print(f"⊘ No ToC found: {final_result.reasoning}")

        if self.logger:
            self.logger.info("ToC search complete",
                           toc_found=final_result.toc_found,
                           strategy=final_result.search_strategy_used,
                           cost=f"${final_result.total_cost_usd:.4f}",
                           iterations=agent_result.iterations,
                           elapsed=f"{elapsed:.1f}s",
                           run_log=str(agent_result.run_log_path) if agent_result.run_log_path else None)

        return final_result
