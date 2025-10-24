"""
Agent client for tool-calling LLM agents.

Provides reusable infrastructure for agents that use iterative tool calling:
- Agent loop (LLM call → execute tools → update conversation)
- Tool call logging to JSONL
- Iteration/cost tracking
- Event-driven progress callbacks
- Error handling

Similar to LLMBatchClient but for sequential agent workflows instead of parallel batches.
"""

import json
import time
from typing import List, Dict, Optional, Callable, Any, Tuple
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

from infra.llm.client import LLMClient
from infra.pipeline.logger import PipelineLogger


@dataclass
class AgentResult:
    """Result from agent execution."""
    success: bool
    iterations: int
    total_cost_usd: float
    execution_time_seconds: float
    final_messages: List[Dict]
    tool_calls_log_path: Optional[Path] = None
    error_message: Optional[str] = None


@dataclass
class AgentEvent:
    """Event emitted during agent execution."""
    event_type: str  # "iteration_start", "tool_call", "iteration_complete", "agent_complete", "agent_error"
    iteration: int
    timestamp: float
    data: Dict[str, Any]


class AgentClient:
    """
    Reusable client for tool-calling agents.

    Handles the boilerplate of agent loops:
    - Calling LLM with tools
    - Executing tool calls
    - Logging tool calls to JSONL
    - Tracking iterations and costs
    - Event callbacks for progress

    Agents provide:
    - Tool definitions
    - Tool execution function
    - Completion check function
    - Progress callbacks (optional)
    """

    def __init__(
        self,
        max_iterations: int = 25,
        log_dir: Optional[Path] = None,
        logger: Optional[PipelineLogger] = None,
        verbose: bool = True
    ):
        """
        Initialize agent client.

        Args:
            max_iterations: Maximum agent loop iterations
            log_dir: Directory to save tool call logs (JSONL)
            logger: Optional pipeline logger
            verbose: Show progress output
        """
        self.max_iterations = max_iterations
        self.log_dir = log_dir
        self.logger = logger
        self.verbose = verbose

        # Tracking
        self.iteration_count = 0
        self.total_cost = 0.0
        self.start_time = None
        self.tool_calls_log = []

    def run(
        self,
        llm_client: LLMClient,
        model: str,
        initial_messages: List[Dict],
        tools: List[Dict],
        execute_tool: Callable[[str, Dict], str],
        is_complete: Callable[[List[Dict]], bool],
        on_event: Optional[Callable[[AgentEvent], None]] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None
    ) -> AgentResult:
        """
        Run agent loop until completion or max iterations.

        Args:
            llm_client: LLMClient instance
            model: Model name (e.g., "anthropic/claude-sonnet-4")
            initial_messages: Starting conversation (system + user prompts)
            tools: Tool definitions for LLM
            execute_tool: Function(tool_name, arguments) -> result_string
            is_complete: Function(messages) -> bool (check if agent is done)
            on_event: Optional callback for progress events
            temperature: LLM temperature
            max_tokens: Max tokens per LLM call

        Returns:
            AgentResult with execution details
        """
        self.start_time = time.time()
        messages = initial_messages.copy()

        # Emit start event
        self._emit_event(on_event, "agent_start", 0, {
            "model": model,
            "max_iterations": self.max_iterations
        })

        try:
            for iteration in range(1, self.max_iterations + 1):
                self.iteration_count = iteration

                # Emit iteration start
                self._emit_event(on_event, "iteration_start", iteration, {})

                # Call LLM with tools
                try:
                    content, usage, cost, tool_calls = llm_client.call_with_tools(
                        model=model,
                        messages=messages,
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )

                    self.total_cost += cost

                except Exception as e:
                    # LLM call failed
                    return self._create_error_result(
                        messages,
                        f"LLM call failed in iteration {iteration}: {str(e)}"
                    )

                # Build assistant message
                assistant_msg = {"role": "assistant"}
                if content:
                    assistant_msg["content"] = content
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls

                messages.append(assistant_msg)

                # Check if agent is done (no tool calls)
                if not tool_calls:
                    if is_complete(messages):
                        # Agent completed successfully
                        self._emit_event(on_event, "agent_complete", iteration, {
                            "total_cost": self.total_cost,
                            "iterations": iteration
                        })

                        return self._create_success_result(messages)
                    else:
                        # Agent stopped without completing
                        # Prompt to continue (give it one more chance)
                        messages.append({
                            "role": "user",
                            "content": "Please continue using the available tools to complete your task."
                        })
                        continue

                # Execute tool calls
                for tool_call in tool_calls:
                    tool_name = tool_call['function']['name']

                    try:
                        arguments = json.loads(tool_call['function']['arguments'])
                    except json.JSONDecodeError:
                        arguments = {}

                    # Execute tool with timing
                    tool_start = time.time()
                    try:
                        result = execute_tool(tool_name, arguments)
                    except Exception as e:
                        result = json.dumps({"error": f"Tool execution failed: {str(e)}"})

                    tool_time = time.time() - tool_start

                    # Log tool call
                    self._log_tool_call(iteration, tool_name, arguments, result, tool_time)

                    # Emit tool call event
                    self._emit_event(on_event, "tool_call", iteration, {
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "execution_time": tool_time
                    })

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call['id'],
                        "content": result
                    })

                # Emit iteration complete
                self._emit_event(on_event, "iteration_complete", iteration, {
                    "cost": cost,
                    "total_cost": self.total_cost,
                    "tool_count": len(tool_calls) if tool_calls else 0
                })

                # Check if agent completed after executing tools
                if is_complete(messages):
                    self._emit_event(on_event, "agent_complete", iteration, {
                        "total_cost": self.total_cost,
                        "iterations": iteration
                    })

                    return self._create_success_result(messages)

            # Max iterations reached
            return self._create_error_result(
                messages,
                f"Agent did not complete within {self.max_iterations} iterations"
            )

        except Exception as e:
            # Unexpected error
            return self._create_error_result(
                messages,
                f"Unexpected error: {str(e)}"
            )

    def _log_tool_call(
        self,
        iteration: int,
        tool_name: str,
        arguments: Dict,
        result: str,
        execution_time: float
    ):
        """Log tool call to internal buffer."""
        self.tool_calls_log.append({
            'iteration': iteration,
            'tool_name': tool_name,
            'arguments': arguments,
            'result': result[:500],  # Truncate long results
            'execution_time_seconds': execution_time,
            'timestamp': datetime.now().isoformat()
        })

    def _save_tool_calls(self, run_timestamp: str) -> Optional[Path]:
        """Save tool calls to JSONL file."""
        if not self.log_dir or not self.tool_calls_log:
            return None

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        tool_calls_path = self.log_dir / f"tool-calls-{run_timestamp}.jsonl"

        with open(tool_calls_path, 'w') as f:
            for call in self.tool_calls_log:
                f.write(json.dumps(call) + '\n')

        return tool_calls_path

    def _emit_event(
        self,
        on_event: Optional[Callable],
        event_type: str,
        iteration: int,
        data: Dict
    ):
        """Emit event to callback if provided."""
        if on_event:
            event = AgentEvent(
                event_type=event_type,
                iteration=iteration,
                timestamp=time.time(),
                data=data
            )
            on_event(event)

    def _create_success_result(self, messages: List[Dict]) -> AgentResult:
        """Create successful AgentResult."""
        elapsed = time.time() - self.start_time
        run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = self._save_tool_calls(run_timestamp)

        return AgentResult(
            success=True,
            iterations=self.iteration_count,
            total_cost_usd=self.total_cost,
            execution_time_seconds=elapsed,
            final_messages=messages,
            tool_calls_log_path=log_path
        )

    def _create_error_result(
        self,
        messages: List[Dict],
        error_message: str
    ) -> AgentResult:
        """Create failed AgentResult."""
        elapsed = time.time() - self.start_time if self.start_time else 0.0
        run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = self._save_tool_calls(run_timestamp)

        return AgentResult(
            success=False,
            iterations=self.iteration_count,
            total_cost_usd=self.total_cost,
            execution_time_seconds=elapsed,
            final_messages=messages,
            tool_calls_log_path=log_path,
            error_message=error_message
        )
