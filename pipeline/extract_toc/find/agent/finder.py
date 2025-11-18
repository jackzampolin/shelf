import time
from typing import Optional

from infra.pipeline.storage.book_storage import BookStorage
from infra.llm.agent import AgentConfig, AgentClient
from infra.pipeline.logger import PipelineLogger
from infra.config import Config

from .tools import TocFinderTools, TocFinderResult
from .prompts import SYSTEM_PROMPT, build_user_prompt


class TocFinderAgent:
    def __init__(
        self,
        storage: BookStorage,
        tracker,  # PhaseStatusTracker
        logger: Optional[PipelineLogger] = None,
        max_iterations: int = 15,
        verbose: bool = True
    ):
        self.storage = storage
        self.tracker = tracker
        self.logger = logger
        self.max_iterations = max_iterations
        self.verbose = verbose

        self.metadata = storage.load_metadata()
        self.scan_id = storage.scan_id
        self.total_pages = self.metadata.get('total_pages', 0)

        self.tools = TocFinderTools(storage=storage)

        initial_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(self.scan_id, self.total_pages)}
        ]

        self.config = AgentConfig(
            tracker=tracker,  # Pass tracker directly
            model=Config.vision_model_primary,
            initial_messages=initial_messages,
            tools=self.tools,
            agent_id="toc-finder",
            max_iterations=max_iterations,
            temperature=0.0
        )

        self.agent_client = AgentClient(self.config)

    def search(self) -> TocFinderResult:
        start_time = time.time()

        if self.logger:
            self.logger.info("Starting grep-informed ToC finder",
                           scan_id=self.scan_id,
                           total_pages=self.total_pages)

        agent_result = self.agent_client.run(verbose=self.verbose)

        if agent_result.success and self.tools._pending_result:
            final_result = self.tools._pending_result
            final_result.total_cost_usd = agent_result.total_cost_usd
            final_result.execution_time_seconds = agent_result.execution_time_seconds
            final_result.iterations = agent_result.iterations
            final_result.total_prompt_tokens = agent_result.total_prompt_tokens
            final_result.total_completion_tokens = agent_result.total_completion_tokens
            final_result.total_reasoning_tokens = agent_result.total_reasoning_tokens
            final_result.pages_checked = len(self.tools._page_observations) + (1 if self.tools._current_page_num else 0)
        else:
            final_result = TocFinderResult(
                toc_found=False,
                toc_page_range=None,
                confidence=0.0,
                search_strategy_used="agent_error" if not agent_result.success else "max_iterations",
                pages_checked=len(self.tools._page_observations) + (1 if self.tools._current_page_num else 0),
                total_cost_usd=agent_result.total_cost_usd,
                execution_time_seconds=agent_result.execution_time_seconds,
                iterations=agent_result.iterations,
                total_prompt_tokens=agent_result.total_prompt_tokens,
                total_completion_tokens=agent_result.total_completion_tokens,
                total_reasoning_tokens=agent_result.total_reasoning_tokens,
                reasoning=agent_result.error_message or "Search incomplete"
            )

        if self.verbose and not final_result.toc_found:
            print(f"⊘ No ToC found: {final_result.reasoning}")

        elapsed = time.time() - start_time

        if self.logger:
            self.logger.info("ToC search complete",
                           toc_found=final_result.toc_found,
                           strategy=final_result.search_strategy_used,
                           cost=f"${final_result.total_cost_usd:.4f}",
                           iterations=agent_result.iterations,
                           elapsed=f"{elapsed:.1f}s",
                           run_log=str(agent_result.run_log_path) if agent_result.run_log_path else None)

        # Save finder result
        from ..schemas import FinderResult
        finder_result = FinderResult(
            toc_found=final_result.toc_found,
            toc_page_range=final_result.toc_page_range,
            confidence=final_result.confidence,
            search_strategy_used=final_result.search_strategy_used,
            pages_checked=final_result.pages_checked,
            reasoning=final_result.reasoning,
            structure_notes=final_result.structure_notes,
            structure_summary=final_result.structure_summary,
        )

        stage_storage = self.storage.stage('extract-toc')
        stage_storage.save_file("finder_result.json", finder_result.model_dump())

        if self.logger:
            self.logger.info("Saved finder_result.json")

        # Return success or failure based on agent result
        if not agent_result.success:
            return {
                "status": "error",
                "error": agent_result.error_message or "Agent search failed"
            }

        return {"status": "success"}
