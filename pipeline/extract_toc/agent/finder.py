import json
import time
from typing import Optional, Tuple

from infra.storage.book_storage import BookStorage
from infra.llm.client import LLMClient
from infra.llm.agent_client import AgentClient, AgentEvent
from infra.pipeline.logger import PipelineLogger
from infra.config import Config
from ..schemas import PageRange

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

        log_dir = storage.stage('extract-toc').output_dir / 'logs' / 'toc_finder'
        self.agent_client = AgentClient(
            max_iterations=max_iterations,
            log_dir=log_dir,
            logger=logger,
            verbose=verbose
        )

        self.tools = TocFinderTools(storage=storage, agent_client=self.agent_client)

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

        def on_event(event: AgentEvent):
            if not self.verbose:
                return

            if event.event_type == "iteration_start":
                print(f"   Iteration {event.iteration}/{self.max_iterations}...")

            elif event.event_type == "tool_call":
                tool_name = event.data['tool_name']
                args = event.data['arguments']
                exec_time = event.data['execution_time']

                if tool_name == "get_frontmatter_grep_report":
                    print(f"   🔧 {tool_name}() - generating keyword search report")
                elif tool_name == "add_page_images_to_context":
                    pages = args.get('page_nums', [])
                    print(f"   🔧 {tool_name}({pages}) - loading images")
                elif tool_name == "write_toc_result":
                    print(f"   ✅ {tool_name}() - finalizing result")
                else:
                    args_str = json.dumps(args) if args else "(no args)"
                    print(f"   🔧 {tool_name}({args_str})")

                if tool_name != "write_toc_result":
                    print(f"      (executed in {exec_time:.1f}s)")

        agent_result = self.agent_client.run(
            llm_client=self.llm_client,
            model=Config.text_model_expensive,
            initial_messages=initial_messages,
            tools=self.tools.get_tools(),
            execute_tool=self.tools.execute_tool,
            is_complete=is_complete,
            on_event=on_event,
            temperature=0.0
        )

        if agent_result.success and self.tools._pending_result:
            final_result = self.tools._pending_result
            final_result.total_cost_usd = agent_result.total_cost_usd
            final_result.pages_checked = len(self.agent_client.images)
        else:
            final_result = TocFinderResult(
                toc_found=False,
                toc_page_range=None,
                confidence=0.0,
                search_strategy_used="agent_error" if not agent_result.success else "max_iterations",
                pages_checked=len(self.agent_client.images),
                total_cost_usd=agent_result.total_cost_usd,
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
) -> Tuple[Optional[PageRange], float]:
    agent = TocFinderAgent(
        storage=storage,
        logger=logger,
        max_iterations=max_iterations,
        verbose=verbose
    )

    result = agent.search()

    if result.toc_found and result.toc_page_range:
        return result.toc_page_range, result.total_cost_usd
    else:
        return None, result.total_cost_usd
