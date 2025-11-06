from rich.console import Console, Group
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree
from rich.padding import Padding
import threading

from infra.llm.display_format import format_token_string, format_batch_summary
from .schemas import AgentEvent


class AgentProgressDisplay:

    def __init__(self, max_iterations: int, console: Console = None, agent_name: str = "Agent search"):
        self.console = console or Console()
        self.max_iterations = max_iterations
        self.agent_name = agent_name

        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            TimeElapsedColumn(),
            console=self.console,
            transient=False
        )

        self.main_task = None
        self.live = None
        self.total_cost = 0.0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_reasoning_tokens = 0
        self.execution_time = 0.0
        self.total_iterations = 0

        self.iteration_lines = []
        self.lock = threading.RLock()
        self.collapsed = False

    def _render(self):
        with self.lock:
            if self.collapsed:
                summary = format_batch_summary(
                    batch_name=self.agent_name,
                    completed=self.total_iterations,
                    total=self.total_iterations,
                    time_seconds=self.execution_time,
                    prompt_tokens=self.total_prompt_tokens,
                    completion_tokens=self.total_completion_tokens,
                    reasoning_tokens=self.total_reasoning_tokens,
                    cost_usd=self.total_cost,
                    unit="iterations"
                )
                return summary

            components = [self.progress]
            if self.iteration_lines:
                from rich.text import Text
                lines_group = []
                for i, line in enumerate(self.iteration_lines):
                    if i == len(self.iteration_lines) - 1:
                        prefix = "  └── "
                    else:
                        prefix = "  ├── "
                    lines_group.append(Text.from_markup(prefix + line))
                components.extend(lines_group)

            return Group(*components)

    def on_event(self, event: AgentEvent):
        with self.lock:
            if event.event_type == "iteration_start":
                if self.main_task is None:
                    self.main_task = self.progress.add_task(
                        f"Agent Progress (0/{self.max_iterations})",
                        total=self.max_iterations
                    )
                self.progress.update(
                    self.main_task,
                    completed=event.iteration - 1,
                    description=f"Agent Progress ({event.iteration}/{self.max_iterations})"
                )

            elif event.event_type == "tool_call":
                tool_name = event.data.get("tool_name", "unknown")
                arguments = event.data.get("arguments", {})

                if not arguments:
                    args_str = "()"
                elif len(arguments) == 1:
                    key, value = list(arguments.items())[0]
                    if isinstance(value, list) and len(value) <= 3:
                        args_str = f"({value})"
                    elif isinstance(value, (int, str)) and len(str(value)) < 20:
                        args_str = f"({value})"
                    else:
                        args_str = "({...})"
                else:
                    args_str = "({...})"

                tool_display = f"{tool_name}{args_str}"
                self.iteration_lines.append(f"[dim]🔧[/dim] {tool_display:<45}")

            elif event.event_type == "iteration_complete":
                self.total_cost = event.data.get("total_cost", 0)
                cost = event.data.get("cost", 0)
                cost_cents = cost * 100

                prompt_tokens = event.data.get("prompt_tokens", 0)
                completion_tokens = event.data.get("completion_tokens", 0)
                reasoning_tokens = event.data.get("reasoning_tokens", 0)
                iteration_time = event.data.get("iteration_time", 0)
                tool_time = event.data.get("tool_time", 0)
                llm_time = iteration_time - tool_time

                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                self.total_reasoning_tokens += reasoning_tokens

                token_str = format_token_string(prompt_tokens, completion_tokens, reasoning_tokens)

                time_str = f"({llm_time:4.1f}s)"
                cost_str = f"{cost_cents:5.2f}¢"

                if self.iteration_lines:
                    self.iteration_lines[-1] += f" [dim]{time_str:>7}[/dim] [cyan]{token_str:>18}[/cyan] [yellow]{cost_str:>7}[/yellow]"

                self.progress.update(
                    self.main_task,
                    completed=event.iteration,
                    description=f"Agent Progress ({event.iteration}/{self.max_iterations})"
                )

            elif event.event_type == "agent_complete":
                self.total_cost = event.data.get("total_cost", 0)
                self.execution_time = event.data.get("execution_time", 0)
                self.total_iterations = event.data.get("iterations", 0)

                self.collapsed = True

                self.progress.update(
                    self.main_task,
                    completed=self.max_iterations,
                    description=f"[bold green]Agent Complete ({self.total_iterations}/{self.max_iterations})[/bold green]"
                )

        if self.live:
            self.live.update(self._render())

    def set_result_name(self, result_name: str):
        with self.lock:
            self.agent_name = result_name
            if self.live and self.collapsed:
                self.live.update(self._render())

    def render_summary(self, execution_time: float) -> Panel:
        summary_text = Text()
        summary_text.append(f"Cost: ${self.total_cost:.4f}  ", style="yellow")
        summary_text.append(f"Tokens: {self.total_prompt_tokens + self.total_completion_tokens + self.total_reasoning_tokens} ", style="cyan")
        summary_text.append(f"({self.total_prompt_tokens}→{self.total_completion_tokens}", style="dim")
        if self.total_reasoning_tokens > 0:
            summary_text.append(f"+{self.total_reasoning_tokens}r", style="dim")
        summary_text.append(")  ", style="dim")
        summary_text.append(f"Time: {execution_time:.1f}s", style="magenta")

        return Panel(summary_text, title="[bold green]Agent Complete[/bold green]", border_style="green")

    def __enter__(self):
        self.live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=4,
            transient=False
        )
        self.live.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.live:
            self.live.__exit__(exc_type, exc_val, exc_tb)
