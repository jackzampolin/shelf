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
    tool_calls_log_path: Optional[Path] = None  # Deprecated: kept for backward compat
    run_log_path: Optional[Path] = None  # New: comprehensive JSON log
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
        self.tool_calls_log = []  # Deprecated: kept for backward compat

        # Vision support: images context passed to every LLM call
        self.images = []  # List of PIL Images or paths, accumulates across iterations

        # New: Comprehensive run log (everything in one structure)
        self.run_log = {
            'metadata': {},
            'initial_messages': [],
            'iterations': []  # List of iteration objects
        }

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

        # Initialize run log
        self.run_log = {
            'metadata': {
                'model': model,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'max_iterations': self.max_iterations,
                'start_time': datetime.now().isoformat(),
                'end_time': None,  # Set on completion
                'success': None,  # Set on completion
                'total_iterations': 0,  # Set on completion
                'total_cost_usd': 0.0,  # Updated incrementally
                'execution_time_seconds': 0.0  # Set on completion
            },
            'initial_messages': initial_messages.copy(),
            'iterations': []
        }

        # Emit start event
        self._emit_event(on_event, "agent_start", 0, {
            "model": model,
            "max_iterations": self.max_iterations
        })

        try:
            for iteration in range(1, self.max_iterations + 1):
                self.iteration_count = iteration

                # Create iteration log entry
                iteration_log = {
                    'iteration': iteration,
                    'llm_request': {
                        'model': model,
                        'temperature': temperature,
                        'max_tokens': max_tokens,
                        'timestamp': datetime.now().isoformat()
                    },
                    'llm_response': None,  # Filled after LLM call
                    'tool_executions': []  # Filled as tools execute
                }

                # Emit iteration start
                self._emit_event(on_event, "iteration_start", iteration, {})

                # Call LLM with tools (include images context if present)
                try:
                    content, usage, cost, tool_calls, reasoning_details = llm_client.call_with_tools(
                        model=model,
                        messages=messages,
                        tools=tools,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        images=self.images if self.images else None
                    )

                    self.total_cost += cost
                    self.run_log['metadata']['total_cost_usd'] = self.total_cost

                    # Log LLM response (including reasoning details)
                    iteration_log['llm_response'] = {
                        'content': content,  # Can be empty string or None
                        'tool_calls': tool_calls,  # Can be None
                        'reasoning_details': reasoning_details,  # Can be None (Grok encrypted reasoning)
                        'usage': usage,
                        'cost_usd': cost,
                        'timestamp': datetime.now().isoformat()
                    }

                except Exception as e:
                    # LLM call failed - add error to iteration log
                    iteration_log['llm_response'] = {
                        'error': str(e),
                        'timestamp': datetime.now().isoformat()
                    }
                    self.run_log['iterations'].append(iteration_log)

                    return self._create_error_result(
                        messages,
                        f"LLM call failed in iteration {iteration}: {str(e)}"
                    )

                # Build assistant message (include reasoning for stateless continuation)
                assistant_msg = {"role": "assistant"}
                if content:
                    assistant_msg["content"] = content
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                if reasoning_details:
                    # Pass encrypted reasoning back for continuation (required for Grok)
                    assistant_msg["reasoning_details"] = reasoning_details

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

                    # Log tool call (deprecated JSONL format - kept for backward compat)
                    self._log_tool_call(iteration, tool_name, arguments, result, tool_time)

                    # NEW: Log to structured iteration log (FULL result, no truncation)
                    tool_execution_log = {
                        'tool_call_id': tool_call['id'],
                        'tool_name': tool_name,
                        'arguments': arguments,
                        'result': result,  # FULL result (was truncated to 500 chars)
                        'execution_time_seconds': tool_time,
                        'timestamp': datetime.now().isoformat()
                    }
                    iteration_log['tool_executions'].append(tool_execution_log)

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

                # Add iteration log to run log
                self.run_log['iterations'].append(iteration_log)

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
        """Save tool calls to JSONL file (deprecated - kept for backward compat)."""
        if not self.log_dir or not self.tool_calls_log:
            return None

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        tool_calls_path = self.log_dir / f"tool-calls-{run_timestamp}.jsonl"

        with open(tool_calls_path, 'w') as f:
            for call in self.tool_calls_log:
                f.write(json.dumps(call) + '\n')

        return tool_calls_path

    def _save_run_log(self, run_timestamp: str, success: bool, error_message: Optional[str] = None) -> Optional[Path]:
        """Save comprehensive run log to single JSON file."""
        if not self.log_dir:
            return None

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Finalize metadata
        self.run_log['metadata']['end_time'] = datetime.now().isoformat()
        self.run_log['metadata']['success'] = success
        self.run_log['metadata']['total_iterations'] = self.iteration_count
        self.run_log['metadata']['execution_time_seconds'] = time.time() - self.start_time if self.start_time else 0.0

        if error_message:
            self.run_log['metadata']['error_message'] = error_message

        # Clean log for readability (strip bloat before saving)
        cleaned_log = self._clean_run_log(self.run_log)

        # Save to JSON file
        run_log_path = self.log_dir / f"run-{run_timestamp}.json"

        with open(run_log_path, 'w') as f:
            json.dump(cleaned_log, f, indent=2)

        return run_log_path

    def _clean_run_log(self, log: Dict) -> Dict:
        """
        Clean run log by removing bloat (images, encrypted data).

        Keeps:
        - Reasoning metadata (ID, format, type, token counts)
        - Tool results (full text)
        - LLM responses (text content)

        Removes:
        - Image data from multipart messages (can be 100KB+ each)
        - Encrypted reasoning data payload (unreadable noise)
        """
        import copy
        cleaned = copy.deepcopy(log)

        # Clean initial messages
        if 'initial_messages' in cleaned:
            cleaned['initial_messages'] = self._strip_images_from_messages(cleaned['initial_messages'])

        # Clean iterations
        for iteration in cleaned.get('iterations', []):
            # Clean reasoning_details: keep metadata, remove encrypted data
            if iteration.get('llm_response') and iteration['llm_response'].get('reasoning_details'):
                cleaned_reasoning = []
                for detail in iteration['llm_response']['reasoning_details']:
                    cleaned_detail = {
                        'type': detail.get('type'),
                        'id': detail.get('id'),
                        'format': detail.get('format'),
                        'index': detail.get('index'),
                        'data_size_bytes': len(detail.get('data', '')) if detail.get('data') else 0,
                        # NOTE: 'data' field removed (encrypted, unreadable)
                    }
                    cleaned_reasoning.append(cleaned_detail)
                iteration['llm_response']['reasoning_details'] = cleaned_reasoning

        return cleaned

    def _strip_images_from_messages(self, messages: List[Dict]) -> List[Dict]:
        """Strip base64 image data from messages, replace with metadata."""
        cleaned_messages = []
        for msg in messages:
            cleaned_msg = msg.copy()

            # Check if content is multipart (list with images)
            content = cleaned_msg.get('content')
            if isinstance(content, list):
                cleaned_content = []
                for item in content:
                    if item.get('type') == 'image_url':
                        # Replace image data with metadata
                        url = item.get('image_url', {}).get('url', '')
                        cleaned_content.append({
                            'type': 'image_url',
                            'image_url': {
                                'url': '[IMAGE_DATA_REMOVED]',
                                'original_size_bytes': len(url)
                            }
                        })
                    else:
                        # Keep text parts as-is
                        cleaned_content.append(item)
                cleaned_msg['content'] = cleaned_content

            cleaned_messages.append(cleaned_msg)

        return cleaned_messages

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

        # Save both logs
        tool_calls_log_path = self._save_tool_calls(run_timestamp)  # Deprecated
        run_log_path = self._save_run_log(run_timestamp, success=True)  # NEW

        return AgentResult(
            success=True,
            iterations=self.iteration_count,
            total_cost_usd=self.total_cost,
            execution_time_seconds=elapsed,
            final_messages=messages,
            tool_calls_log_path=tool_calls_log_path,  # Deprecated
            run_log_path=run_log_path  # NEW
        )

    def _create_error_result(
        self,
        messages: List[Dict],
        error_message: str
    ) -> AgentResult:
        """Create failed AgentResult."""
        elapsed = time.time() - self.start_time if self.start_time else 0.0
        run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Save both logs
        tool_calls_log_path = self._save_tool_calls(run_timestamp)  # Deprecated
        run_log_path = self._save_run_log(run_timestamp, success=False, error_message=error_message)  # NEW

        return AgentResult(
            success=False,
            iterations=self.iteration_count,
            total_cost_usd=self.total_cost,
            execution_time_seconds=elapsed,
            final_messages=messages,
            tool_calls_log_path=tool_calls_log_path,  # Deprecated
            run_log_path=run_log_path,  # NEW
            error_message=error_message
        )
