from typing import Dict

from infra.pipeline.storage.book_storage import BookStorage
from infra.llm.agent import AgentConfig, AgentClient

from ..schemas import AgentResult
from .finder_tools import TocEntryFinderTools
from .prompts import FINDER_SYSTEM_PROMPT, build_finder_user_prompt


class TocEntryFinderAgent:

    def __init__(
        self,
        toc_entry: Dict,
        toc_entry_index: int,
        storage: BookStorage,
        model: str,
        max_iterations: int = 15
    ):
        self.toc_entry = toc_entry
        self.toc_entry_index = toc_entry_index
        self.storage = storage
        self.model = model
        self.max_iterations = max_iterations

        metadata = storage.load_metadata()
        self.total_pages = metadata.get('total_pages', 0)

        self.agent_id = f"entry_{toc_entry_index:03d}"

        self.tools = TocEntryFinderTools(
            storage=storage,
            toc_entry=toc_entry,
            total_pages=self.total_pages
        )

        initial_messages = [
            {"role": "system", "content": FINDER_SYSTEM_PROMPT},
            {"role": "user", "content": build_finder_user_prompt(self.toc_entry, self.toc_entry_index, self.total_pages)}
        ]

        self.config = AgentConfig(
            model=model,
            initial_messages=initial_messages,
            tools=self.tools,
            stage_storage=storage.stage('link-toc'),
            agent_id=self.agent_id,
            max_iterations=max_iterations
        )

        self.agent_client = AgentClient(self.config)

    def search(self, on_event=None) -> AgentResult:
        toc_title = self.toc_entry['title']

        agent_result = self.agent_client.run(on_event=on_event)

        if agent_result.success and self.tools._pending_result:
            result_data = self.tools._pending_result

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

        return final_result
