import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn

from .config import AgentBatchConfig
from .result import AgentBatchResult
from ..single import AgentClient
from ..schemas import AgentResult
from infra.llm.display import DisplayStats, print_phase_complete


def is_headless():
    """Check if running in headless mode (no Rich displays)."""
    return os.environ.get('SHELF_HEADLESS', '').lower() in ('1', 'true', 'yes')


class AgentBatchClient:

    def __init__(self, config: AgentBatchConfig):
        self.config = config
        self.tracker = config.tracker

    def run(self) -> AgentBatchResult:
        start_time = time.time()
        results: List[AgentResult] = []
        completed_count = 0

        total_agents = len(self.config.agent_configs)

        def process_agent(agent_config) -> AgentResult:
            agent = AgentClient(agent_config)
            return agent.run(verbose=False, on_event=None)

        if is_headless():
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                futures = {
                    executor.submit(process_agent, cfg): cfg
                    for cfg in self.config.agent_configs
                }

                for future in as_completed(futures):
                    cfg = futures[future]
                    try:
                        result = future.result()
                        results.append(result)
                    except KeyboardInterrupt:
                        self.tracker.logger.warning(
                            f"Agent batch interrupted by user",
                            agent_id=cfg.agent_id
                        )
                        raise
                    except MemoryError as e:
                        self.tracker.logger.error(
                            f"Agent {cfg.agent_id} ran out of memory",
                            agent_id=cfg.agent_id,
                            error=str(e),
                            exc_info=True
                        )
                        raise
                    except Exception as e:
                        self.tracker.logger.error(
                            f"Agent {cfg.agent_id} failed",
                            agent_id=cfg.agent_id,
                            error_type=type(e).__name__,
                            error=str(e),
                            exc_info=True
                        )
                        results.append(AgentResult(
                            success=False,
                            iterations=0,
                            total_cost_usd=0.0,
                            total_prompt_tokens=0,
                            total_completion_tokens=0,
                            total_reasoning_tokens=0,
                            execution_time_seconds=0.0,
                            final_messages=[],
                            error_message=f"Agent {cfg.agent_id} failed: {type(e).__name__}: {str(e)}"
                        ))
        else:
            progress = Progress(
                TextColumn(f"⏳ {self.config.batch_name}"),
                BarColumn(bar_width=40),
                TaskProgressColumn(),
                TextColumn("{task.fields[suffix]}", justify="right"),
                transient=True
            )

            with progress:
                task = progress.add_task("", total=total_agents, suffix=f"0/{total_agents}")

                with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                    futures = {
                        executor.submit(process_agent, cfg): cfg
                        for cfg in self.config.agent_configs
                    }

                    for future in as_completed(futures):
                        cfg = futures[future]
                        try:
                            result = future.result()
                            results.append(result)
                            completed_count += 1

                            # Build progress suffix matching LLM batch format
                            elapsed = time.time() - start_time
                            elapsed_mins = int(elapsed // 60)
                            elapsed_secs = int(elapsed % 60)
                            elapsed_str = f"{elapsed_mins}:{elapsed_secs:02d}"

                            parts = [f"{completed_count}/{total_agents}"]

                            # Throughput
                            if elapsed > 0:
                                throughput = completed_count / elapsed
                                if throughput > 0:
                                    parts.append(f"{throughput:.1f}/s")

                            # Time and ETA
                            remaining = total_agents - completed_count
                            if elapsed > 0 and remaining > 0:
                                eta_seconds = remaining / (completed_count / elapsed)
                                eta_mins = int(eta_seconds // 60)
                                eta_secs = int(eta_seconds % 60)
                                parts.append(f"{elapsed_str} (ETA {eta_mins}:{eta_secs:02d})")
                            else:
                                parts.append(elapsed_str)

                            # Tokens
                            prompt_so_far = sum(r.total_prompt_tokens for r in results)
                            completion_so_far = sum(r.total_completion_tokens for r in results)
                            reasoning_so_far = sum(r.total_reasoning_tokens for r in results)
                            if prompt_so_far > 0 or completion_so_far > 0:
                                from infra.llm.display_format import format_token_string
                                token_str = format_token_string(prompt_so_far, completion_so_far, reasoning_so_far)
                                parts.append(token_str)

                            # Cost
                            cost_so_far = sum(r.total_cost_usd for r in results)
                            parts.append(f"${cost_so_far:.2f}")

                            progress.update(task, completed=completed_count, suffix=" • ".join(parts))
                        except KeyboardInterrupt:
                            self.tracker.logger.warning(
                                f"Agent batch interrupted by user",
                                agent_id=cfg.agent_id
                            )
                            raise
                        except MemoryError as e:
                            self.tracker.logger.error(
                                f"Agent {cfg.agent_id} ran out of memory",
                                agent_id=cfg.agent_id,
                                error=str(e),
                                exc_info=True
                            )
                            raise
                        except Exception as e:
                            self.tracker.logger.error(
                                f"Agent {cfg.agent_id} failed",
                                agent_id=cfg.agent_id,
                                error_type=type(e).__name__,
                                error=str(e),
                                exc_info=True
                            )
                            results.append(AgentResult(
                                success=False,
                                iterations=0,
                                total_cost_usd=0.0,
                                total_prompt_tokens=0,
                                total_completion_tokens=0,
                                total_reasoning_tokens=0,
                                execution_time_seconds=0.0,
                                final_messages=[],
                                error_message=f"Agent {cfg.agent_id} failed: {type(e).__name__}: {str(e)}"
                            ))
                            completed_count += 1
                            progress.update(task, completed=completed_count)

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

        print_phase_complete(self.config.batch_name, DisplayStats(
            completed=successful,
            total=total_agents,
            time_seconds=total_time,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            reasoning_tokens=total_reasoning_tokens,
            cost_usd=total_cost,
        ))

        self.tracker.logger.info(
            f"{self.config.batch_name} complete: {successful}/{total_agents} successful, "
            f"{failed} failed, ${total_cost:.4f}"
        )

        return AgentBatchResult(
            results=results,
            total_agents=total_agents,
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
