import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from .config import AgentBatchConfig
from .result import AgentBatchResult
from ..single import AgentClient
from ..schemas import AgentResult, AgentEvent
from .progress import MultiAgentProgressDisplay


class AgentBatchClient:

    def __init__(self, config: AgentBatchConfig):
        self.config = config
        self.tracker = config.tracker

        self.progress = MultiAgentProgressDisplay(
            total_agents=len(config.agent_configs),
            max_visible_agents=config.max_workers,  # Show as many as can run in parallel
            completed_agent_display_seconds=3  # Hardcoded: keep completed agents visible for 3s
        )

    def run(self) -> AgentBatchResult:
        start_time = time.time()

        for agent_config in self.config.agent_configs:
            self.progress.register_agent(
                agent_id=agent_config.agent_id,
                entry_index=0,
                entry_title=agent_config.agent_id,
                max_iterations=agent_config.max_iterations
            )

        results: List[AgentResult] = []

        def process_agent(agent_config) -> AgentResult:
            agent_id = agent_config.agent_id

            def on_event(event: AgentEvent):
                # Enrich agent_complete events with status for progress display
                if event.event_type == "agent_complete":
                    # Agent client fires agent_complete but doesn't include status
                    # We'll determine status after agent.run() completes
                    # For now, just mark it as "searching" which will be updated
                    if "status" not in event.data:
                        event.data["status"] = "searching"
                self.progress.on_event(agent_id, event)

            agent = AgentClient(agent_config)
            result = agent.run(verbose=False, on_event=on_event)

            # Agent already fired agent_complete event during run()
            # Now update the agent's status based on the final result
            # Use a separate event to avoid double-counting completions
            status = "found" if result.success else "not_found"
            self.progress.on_event(agent_id, AgentEvent(
                event_type="agent_status_final",
                iteration=result.iterations,
                timestamp=time.time(),
                data={
                    "status": status,
                    "total_cost": result.total_cost_usd
                }
            ))

            return result

        self.progress.__enter__()

        try:
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                futures = {
                    executor.submit(process_agent, cfg): cfg
                    for cfg in self.config.agent_configs
                }

                for future in as_completed(futures):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        cfg = futures[future]
                        results.append(AgentResult(
                            success=False,
                            iterations=0,
                            total_cost_usd=0.0,
                            total_prompt_tokens=0,
                            total_completion_tokens=0,
                            total_reasoning_tokens=0,
                            execution_time_seconds=0.0,
                            final_messages=[],
                            error_message=f"Agent {cfg.agent_id} failed: {str(e)}"
                        ))
        finally:
            self.progress.__exit__(None, None, None)

        total_time = time.time() - start_time

        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        total_cost = sum(r.total_cost_usd for r in results)
        total_prompt_tokens = sum(r.total_prompt_tokens for r in results)
        total_completion_tokens = sum(r.total_completion_tokens for r in results)
        total_reasoning_tokens = sum(r.total_reasoning_tokens for r in results)
        avg_iterations = sum(r.iterations for r in results) / len(results) if results else 0.0
        avg_cost = total_cost / len(results) if results else 0.0
        avg_time = total_time / len(results) if results else 0.0

        # NOTE: Don't record batch-level metrics here - would double-count!
        # Individual agents already record per-iteration metrics via their trackers.
        # The MetricsManager can aggregate those via get_cumulative_metrics(prefix=tracker.metrics_prefix)

        return AgentBatchResult(
            results=results,
            total_agents=len(self.config.agent_configs),
            successful=successful,
            failed=failed,
            total_cost_usd=total_cost,
            total_time_seconds=total_time,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            total_reasoning_tokens=total_reasoning_tokens,
            avg_iterations=avg_iterations,
            avg_cost_per_agent=avg_cost,
            avg_time_per_agent=avg_time
        )
