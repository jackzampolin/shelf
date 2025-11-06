from rich.console import Console, Group
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich.live import Live
from rich.text import Text
from rich.table import Table
from rich.panel import Panel
import threading
import time
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from infra.llm.display_format import format_token_string
from ..schemas import AgentEvent


@dataclass
class AgentState:
    agent_id: str
    entry_index: int
    entry_title: str
    status: str
    current_iteration: int = 0
    max_iterations: int = 15
    last_tool: str = ""
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_cost: float = 0.0
    elapsed_time: float = 0.0
    start_time: float = field(default_factory=time.time)
    completion_time: Optional[float] = None


class MultiAgentProgressDisplay:

    def __init__(
        self,
        total_agents: int,
        max_visible_agents: int = 10,
        completed_agent_display_seconds: float = 5.0,
        console: Console = None
    ):
        self.total_agents = total_agents
        self.max_visible_agents = max_visible_agents
        self.completed_agent_display_seconds = completed_agent_display_seconds
        self.console = console or Console()

        self.agents: Dict[str, AgentState] = {}
        self.completed_count = 0
        self.found_count = 0
        self.not_found_count = 0

        self.total_cost = 0.0
        self.total_time = 0.0
        self.start_time = time.time()

        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console,
            transient=False
        )
        self.main_task = self.progress.add_task("", total=total_agents)

        self.lock = threading.RLock()
        self.live = None

    def register_agent(self, agent_id: str, entry_index: int, entry_title: str, max_iterations: int = 15):
        with self.lock:
            self.agents[agent_id] = AgentState(
                agent_id=agent_id,
                entry_index=entry_index,
                entry_title=entry_title,
                status="searching",
                max_iterations=max_iterations
            )

    def on_event(self, agent_id: str, event: AgentEvent):
        with self.lock:
            if agent_id not in self.agents:
                return

            agent = self.agents[agent_id]

            if event.event_type == "iteration_start":
                agent.current_iteration = event.iteration

            elif event.event_type == "tool_call":
                tool_name = event.data.get("tool_name", "unknown")
                arguments = event.data.get("arguments", {})

                if not arguments:
                    args_str = "()"
                elif len(arguments) == 1:
                    key, value = list(arguments.items())[0]
                    if isinstance(value, (int, str)) and len(str(value)) < 20:
                        args_str = f"({value})"
                    else:
                        args_str = "(...)"
                else:
                    args_str = "(...)"

                agent.last_tool = f"{tool_name}{args_str}"

            elif event.event_type == "iteration_complete":
                agent.total_cost = event.data.get("total_cost", 0)
                agent.total_prompt_tokens += event.data.get("prompt_tokens", 0)
                agent.total_completion_tokens += event.data.get("completion_tokens", 0)
                agent.total_reasoning_tokens += event.data.get("reasoning_tokens", 0)

            elif event.event_type == "agent_complete":
                agent.status = event.data.get("status", "searching")
                agent.completion_time = time.time()
                agent.elapsed_time = agent.completion_time - agent.start_time
                agent.total_cost = event.data.get("total_cost", 0)

                self.completed_count += 1
                self.total_cost += agent.total_cost

            elif event.event_type == "agent_status_final":
                # Update final status without double-counting completion
                agent.status = event.data.get("status", "found")
                agent.total_cost = event.data.get("total_cost", 0)

                if agent.status == "found":
                    self.found_count += 1
                else:
                    self.not_found_count += 1

        if self.live:
            self.live.update(self._render())

    def _render(self):
        with self.lock:
            elapsed = time.time() - self.start_time

            if self.completed_count > 0:
                avg_time_per_agent = elapsed / self.completed_count
                remaining_agents = self.total_agents - self.completed_count
                time_remaining = remaining_agents * avg_time_per_agent
            else:
                time_remaining = 0

            elapsed_str = self._format_time(elapsed)
            remaining_str = self._format_time(time_remaining) if time_remaining > 0 else "calculating..."

            progress_desc = (
                f"[bold blue]{self.completed_count}/{self.total_agents} agents[/bold blue]    "
                f"[yellow]${self.total_cost:.4f}[/yellow]  "
                f"[cyan]{elapsed_str} elapsed[/cyan]  "
                f"[dim]~{remaining_str} remaining[/dim]"
            )

            self.progress.update(
                self.main_task,
                completed=self.completed_count,
                description=progress_desc
            )

            metrics_lines = []
            if self.completed_count > 0:
                avg_iterations = sum(a.current_iteration for a in self.agents.values() if a.completion_time) / self.completed_count
                avg_cost = self.total_cost / self.completed_count
                avg_time = elapsed / self.completed_count

                metrics_lines.append(Text.from_markup(
                    f"  Avg per agent: [cyan]{avg_iterations:.1f} iterations[/cyan], "
                    f"[yellow]${avg_cost:.4f}[/yellow], "
                    f"[dim]{avg_time:.1f}s[/dim]"
                ))

                found_pct = (self.found_count / self.total_agents) * 100 if self.total_agents > 0 else 0.0
                metrics_lines.append(Text.from_markup(
                    f"  Found: [green]{self.found_count}/{self.total_agents}[/green] "
                    f"[dim]({found_pct:.1f}%)[/dim]"
                ))

            visible_agents = self._get_visible_agents()

            agent_lines = []
            if visible_agents:
                agent_lines.append(Text.from_markup("\n[bold]Running agents:[/bold]"))
                for agent in visible_agents:
                    agent_lines.append(self._format_agent_line(agent))

            components = [self.progress]
            if metrics_lines:
                components.append(Text.from_markup("\n[bold]Overall metrics:[/bold]"))
                components.extend(metrics_lines)
            components.extend(agent_lines)

            return Group(*components)

    def _get_visible_agents(self) -> List[AgentState]:
        now = time.time()
        visible = []

        for agent in self.agents.values():
            if agent.status == "searching":
                visible.append(agent)
            elif agent.completion_time and (now - agent.completion_time) < self.completed_agent_display_seconds:
                visible.append(agent)

        visible.sort(key=lambda a: (
            0 if a.status == "searching" else 1,
            a.completion_time if a.completion_time else 0
        ))

        return visible[:self.max_visible_agents]

    def _format_agent_line(self, agent: AgentState) -> Text:
        text = Text()

        if agent.status == "searching":
            emoji = "🔍"
            style = ""
        elif agent.status == "found":
            emoji = "✅"
            style = "green"
        else:
            emoji = "❌"
            style = "red"

        text.append(f"  {emoji} ", style=style)

        text.append(f"{agent.agent_id:<12}", style="bold" if agent.status == "searching" else "dim")

        text.append(f" ({agent.current_iteration}/{agent.max_iterations})", style="dim")

        if agent.status == "searching":
            tool_display = agent.last_tool if agent.last_tool else "starting..."
            text.append(f" {tool_display:<35}", style="")
        elif agent.status == "found":
            text.append(f" [found]                             ", style="green")
        else:
            text.append(f" [not found]                         ", style="red")

        token_str = format_token_string(
            agent.total_prompt_tokens,
            agent.total_completion_tokens,
            agent.total_reasoning_tokens
        )
        text.append(f" {token_str:>20}", style="cyan")

        elapsed = agent.elapsed_time if agent.completion_time else (time.time() - agent.start_time)
        text.append(f" ({elapsed:5.1f}s)", style="dim")

        cost_cents = agent.total_cost * 100
        text.append(f" {cost_cents:5.2f}¢", style="yellow")

        return text

    def _format_time(self, seconds: float) -> str:
        if seconds >= 60:
            return f"{seconds/60:.1f}m"
        else:
            return f"{seconds:.0f}s"

    def __enter__(self):
        self.live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=2,
            transient=False
        )
        self.live.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.live:
            self.live.__exit__(exc_type, exc_val, exc_tb)
