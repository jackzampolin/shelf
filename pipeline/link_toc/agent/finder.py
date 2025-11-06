import time
from typing import Dict, Optional

from infra.storage.book_storage import BookStorage
from infra.llm.client import LLMClient
from infra.llm.agent import AgentClient, AgentProgressDisplay
from infra.pipeline.logger import PipelineLogger

from ..schemas import AgentResult
from .finder_tools import TocEntryFinderTools
from .prompts import FINDER_SYSTEM_PROMPT, build_finder_user_prompt


class TocEntryFinderAgent:
    """Agent that searches for a single ToC entry in the book."""

    def __init__(
        self,
        toc_entry: Dict,
        toc_entry_index: int,
        storage: BookStorage,
        logger: Optional[PipelineLogger],
        model: str,
        max_iterations: int = 15,
        verbose: bool = False
    ):
        self.toc_entry = toc_entry
        self.toc_entry_index = toc_entry_index
        self.storage = storage
        self.logger = logger
        self.model = model
        self.max_iterations = max_iterations
        self.verbose = verbose

        self.llm_client = LLMClient()

        metadata = storage.load_metadata()
        self.total_pages = metadata.get('total_pages', 0)

        stage_storage = storage.stage('link-toc')
        log_dir = stage_storage.output_dir / 'logs' / 'entry_finders'
        self.agent_client = AgentClient(
            max_iterations=max_iterations,
            log_dir=log_dir,
            logger=logger,
            metrics_manager=stage_storage.metrics_manager,
            metrics_key_prefix=f"entry_{toc_entry_index:03d}_",
            verbose=verbose
        )

        self.tools = TocEntryFinderTools(
            storage=storage,
            agent_client=self.agent_client,
            toc_entry=toc_entry,
            total_pages=self.total_pages
        )

    def search(self) -> AgentResult:
        """Execute search for this ToC entry."""
        start_time = time.time()

        toc_title = self.toc_entry['title']

        if self.verbose and self.logger:
            self.logger.info(f"Searching for: {toc_title}")

        initial_messages = [
            {"role": "system", "content": FINDER_SYSTEM_PROMPT},
            {"role": "user", "content": build_finder_user_prompt(self.toc_entry, self.toc_entry_index, self.total_pages)}
        ]

        def is_complete(messages):
            return self.tools._pending_result is not None

        progress = AgentProgressDisplay(
            max_iterations=self.max_iterations,
            agent_name=f"Entry {self.toc_entry_index}"
        ) if self.verbose else None

        # Run agent
        if progress:
            progress.__enter__()
            try:
                agent_result = self.agent_client.run(
                    llm_client=self.llm_client,
                    model=self.model,
                    initial_messages=initial_messages,
                    tools=self.tools.get_tools(),
                    execute_tool=self.tools.execute_tool,
                    is_complete=is_complete,
                    on_event=progress.on_event,
                    temperature=0.0
                )
            finally:
                pass
        else:
            agent_result = self.agent_client.run(
                llm_client=self.llm_client,
                model=self.model,
                initial_messages=initial_messages,
                tools=self.tools.get_tools(),
                execute_tool=self.tools.execute_tool,
                is_complete=is_complete,
                on_event=None,
                temperature=0.0
            )

        # Build AgentResult
        if agent_result.success and self.tools._pending_result:
            result_data = self.tools._pending_result

            # Add notes from page observations if any
            notes = None
            if self.tools._page_observations:
                notes = f"Viewed {len(self.tools._page_observations)} pages: " + "; ".join(
                    [f"p{obs['page_num']}: {obs['observations'][:50]}..." for obs in self.tools._page_observations[:3]]
                )

            final_result = AgentResult(
                toc_entry_index=self.toc_entry_index,
                toc_title=toc_title,
                printed_page_number=self.toc_entry.get('printed_page_number') or self.toc_entry.get('page_number'),
                found=result_data["found"],
                scan_page=result_data["scan_page"],
                confidence=result_data["confidence"],
                search_strategy=result_data["search_strategy"],
                reasoning=result_data["reasoning"],
                iterations_used=agent_result.iterations,
                candidates_checked=self.tools._candidates_checked,
                notes=notes
            )
        else:
            # Agent failed or hit max iterations without writing result
            final_result = AgentResult(
                toc_entry_index=self.toc_entry_index,
                toc_title=toc_title,
                printed_page_number=self.toc_entry.get('printed_page_number') or self.toc_entry.get('page_number'),
                found=False,
                scan_page=None,
                confidence=0.0,
                search_strategy="agent_error" if not agent_result.success else "max_iterations_reached",
                reasoning=agent_result.error_message or "Agent did not complete search",
                iterations_used=agent_result.iterations,
                candidates_checked=self.tools._candidates_checked,
                notes=None
            )

        # Update progress display
        if progress:
            if final_result.found:
                progress.set_result_name(f"Entry {self.toc_entry_index}: found at page {final_result.scan_page}")
            else:
                progress.set_result_name(f"Entry {self.toc_entry_index}: not found")
            progress.__exit__(None, None, None)

        elapsed = time.time() - start_time

        if self.verbose and self.logger:
            self.logger.info(
                f"Search complete: {toc_title}",
                found=final_result.found,
                scan_page=final_result.scan_page,
                confidence=final_result.confidence,
                iterations=final_result.iterations_used,
                elapsed=f"{elapsed:.1f}s"
            )

        return final_result
