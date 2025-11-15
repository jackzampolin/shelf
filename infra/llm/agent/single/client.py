import json
import time
from typing import List, Dict, Optional, Callable, Any
from datetime import datetime
from pathlib import Path

from infra.llm.client import LLMClient
from .config import AgentConfig
from ..schemas import AgentResult, AgentEvent
from ..logging import save_run_log
from .progress import AgentProgressDisplay


class AgentClient:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.tracker = config.tracker
        self.llm_client = LLMClient(logger=self.tracker.logger, max_retries=3)
        self.log_dir = self.tracker.stage_storage.output_dir / 'logs' / 'agents' / config.agent_id
        self.log_filename = f"{config.agent_id}.json"
        self.metrics_manager = self.tracker.stage_storage.metrics_manager
        self.metrics_key_prefix = self.tracker.metrics_prefix
        self.iteration_count = 0
        self.total_cost = 0.0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_reasoning_tokens = 0
        self.start_time = None
        self.run_log = None
        
    def run(
        self,
        verbose: bool = False,
        on_event: Optional[Callable[[AgentEvent], None]] = None
    ) -> AgentResult:
        progress = None
        if verbose:
            progress = AgentProgressDisplay(
                max_iterations=self.config.max_iterations,
                agent_name=self.config.agent_id
            )
            progress.__enter__()

        def combined_on_event(event: AgentEvent):
            if progress:
                progress.on_event(event)
            if on_event:
                on_event(event)

        try:
            return self._run_agent(combined_on_event if (progress or on_event) else None)
        finally:
            if progress:
                progress.__exit__(None, None, None)

    def _run_agent(
        self,
        on_event: Optional[Callable[[AgentEvent], None]] = None
    ) -> AgentResult:
        self.start_time = time.time()
        messages = self.config.initial_messages.copy()
        self.run_log = {
            'metadata': {
                'model': self.config.model,
                'temperature': self.config.temperature,
                'max_tokens': self.config.max_tokens,
                'max_iterations': self.config.max_iterations,
                'start_time': datetime.now().isoformat(),
                'end_time': None,
                'success': None,
                'total_iterations': 0,
                'total_cost_usd': 0.0,
                'execution_time_seconds': 0.0
            },
            'initial_messages': self.config.initial_messages.copy(),
            'iterations': []
        }
        self._emit_event(on_event, "agent_start", 0, {
            "model": self.config.model,
            "max_iterations": self.config.max_iterations
        })
        try:
            for iteration in range(1, self.config.max_iterations + 1):
                iteration_start_time = time.time()
                iteration_tool_time = 0.0
                self.iteration_count = iteration
                iteration_log = {
                    'iteration': iteration,
                    'llm_request': {
                        'model': self.config.model,
                        'temperature': self.config.temperature,
                        'max_tokens': self.config.max_tokens,
                        'timestamp': datetime.now().isoformat()
                    },
                    'llm_response': None,
                    'tool_executions': []
                }
                self._emit_event(on_event, "iteration_start", iteration, {})
                try:
                    # Get images from tools, fallback to config images
                    images = self.config.tools.get_images()
                    if images is None and self.config.images is not None:
                        images = self.config.images

                    # LLMClient.call_with_tools() now returns LLMResult
                    result = self.llm_client.call_with_tools(
                        model=self.config.model,
                        messages=messages,
                        tools=self.config.tools.get_tools(),
                        temperature=self.config.temperature,
                        max_tokens=self.config.max_tokens,
                        images=images
                    )

                    self.total_cost += result.cost_usd
                    self.run_log['metadata']['total_cost_usd'] = self.total_cost
                    prompt_tokens = result.prompt_tokens
                    completion_tokens = result.completion_tokens
                    reasoning_tokens = result.reasoning_tokens
                    self.total_prompt_tokens += prompt_tokens
                    self.total_completion_tokens += completion_tokens
                    self.total_reasoning_tokens += reasoning_tokens
                    iteration_log['llm_response'] = {
                        'content': result.response,
                        'tool_calls': result.tool_calls,
                        'reasoning_details': result.reasoning_details,
                        'prompt_tokens': result.prompt_tokens,
                        'completion_tokens': result.completion_tokens,
                        'total_tokens': result.total_tokens,
                        'reasoning_tokens': result.reasoning_tokens,
                        'cost_usd': result.cost_usd,
                        'timestamp': datetime.now().isoformat()
                    }
                except Exception as e:
                    iteration_log['llm_response'] = {
                        'error': str(e),
                        'timestamp': datetime.now().isoformat()
                    }
                    self.run_log['iterations'].append(iteration_log)
                    return self._create_error_result(
                        messages,
                        f"LLM call failed in iteration {iteration}: {str(e)}"
                    )
                assistant_msg = {"role": "assistant"}
                if result.response:
                    assistant_msg["content"] = result.response
                if result.tool_calls:
                    assistant_msg["tool_calls"] = result.tool_calls
                if result.reasoning_details:
                    assistant_msg["reasoning_details"] = result.reasoning_details
                messages.append(assistant_msg)
                if not result.tool_calls:
                    if self.config.tools.is_complete():
                        elapsed = time.time() - self.start_time
                        self._emit_event(on_event, "agent_complete", iteration, {
                            "total_cost": self.total_cost,
                            "iterations": iteration,
                            "execution_time": elapsed
                        })
                        return self._create_success_result(messages)
                    else:
                        messages.append({
                            "role": "user",
                            "content": "Please continue using the available tools to complete your task."
                        })
                        continue
                for tool_call in result.tool_calls:
                    tool_name = tool_call['function']['name']
                    try:
                        arguments = json.loads(tool_call['function']['arguments'])
                    except json.JSONDecodeError:
                        arguments = {}
                    tool_start = time.time()
                    try:
                        tool_result = self.config.tools.execute_tool(tool_name, arguments)
                    except Exception as e:
                        tool_result = json.dumps({"error": f"Tool execution failed: {str(e)}"})
                    tool_time = time.time() - tool_start
                    iteration_tool_time += tool_time
                    tool_execution_log = {
                        'tool_call_id': tool_call['id'],
                        'tool_name': tool_name,
                        'arguments': arguments,
                        'result': tool_result,
                        'execution_time_seconds': tool_time,
                        'timestamp': datetime.now().isoformat()
                    }
                    iteration_log['tool_executions'].append(tool_execution_log)
                    self._emit_event(on_event, "tool_call", iteration, {
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "execution_time": tool_time
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call['id'],
                        "content": tool_result
                    })
                self.run_log['iterations'].append(iteration_log)
                if self.metrics_manager:
                    self.metrics_manager.record(
                        key=f"{self.metrics_key_prefix}iteration_{iteration:04d}",
                        cost_usd=result.cost_usd,
                        time_seconds=time.time() - iteration_start_time,
                        tokens=prompt_tokens + completion_tokens + reasoning_tokens,
                        custom_metrics={
                            'iteration': iteration,
                            'prompt_tokens': prompt_tokens,
                            'completion_tokens': completion_tokens,
                            'reasoning_tokens': reasoning_tokens,
                            'tool_calls': len(result.tool_calls) if result.tool_calls else 0,
                        }
                    )
                iteration_total_time = time.time() - iteration_start_time
                self._emit_event(on_event, "iteration_complete", iteration, {
                    "cost": result.cost_usd,
                    "total_cost": self.total_cost,
                    "tool_count": len(result.tool_calls) if result.tool_calls else 0,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "reasoning_tokens": reasoning_tokens,
                    "iteration_time": iteration_total_time,
                    "tool_time": iteration_tool_time
                })
                if self.config.tools.is_complete():
                    elapsed = time.time() - self.start_time
                    self._emit_event(on_event, "agent_complete", iteration, {
                        "total_cost": self.total_cost,
                        "iterations": iteration,
                        "execution_time": elapsed
                    })
                    return self._create_success_result(messages)
            return self._create_error_result(
                messages,
                f"Agent did not complete within {self.config.max_iterations} iterations"
            )
        except Exception as e:
            return self._create_error_result(
                messages,
                f"Unexpected error: {str(e)}"
            )
    def _finalize_and_save_log(self, run_timestamp: str, success: bool, error_message: Optional[str] = None) -> Optional[Path]:
        self.run_log['metadata']['end_time'] = datetime.now().isoformat()
        self.run_log['metadata']['success'] = success
        self.run_log['metadata']['total_iterations'] = self.iteration_count
        self.run_log['metadata']['execution_time_seconds'] = time.time() - self.start_time if self.start_time else 0.0
        if error_message:
            self.run_log['metadata']['error_message'] = error_message
        return save_run_log(self.run_log, self.log_dir, run_timestamp, self.log_filename)
    def _emit_event(
        self,
        on_event: Optional[Callable],
        event_type: str,
        iteration: int,
        data: Dict
    ):
        if on_event:
            event = AgentEvent(
                event_type=event_type,
                iteration=iteration,
                timestamp=time.time(),
                data=data
            )
            on_event(event)
    def _create_success_result(self, messages: List[Dict]) -> AgentResult:
        elapsed = time.time() - self.start_time
        run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_log_path = self._finalize_and_save_log(run_timestamp, success=True)
        return AgentResult(
            success=True,
            iterations=self.iteration_count,
            total_cost_usd=self.total_cost,
            total_prompt_tokens=self.total_prompt_tokens,
            total_completion_tokens=self.total_completion_tokens,
            total_reasoning_tokens=self.total_reasoning_tokens,
            execution_time_seconds=elapsed,
            final_messages=messages,
            run_log_path=run_log_path
        )
    def _create_error_result(
        self,
        messages: List[Dict],
        error_message: str
    ) -> AgentResult:
        elapsed = time.time() - self.start_time if self.start_time else 0.0
        run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_log_path = self._finalize_and_save_log(run_timestamp, success=False, error_message=error_message)
        return AgentResult(
            success=False,
            iterations=self.iteration_count,
            total_cost_usd=self.total_cost,
            total_prompt_tokens=self.total_prompt_tokens,
            total_completion_tokens=self.total_completion_tokens,
            total_reasoning_tokens=self.total_reasoning_tokens,
            execution_time_seconds=elapsed,
            final_messages=messages,
            run_log_path=run_log_path,
            error_message=error_message
        )
