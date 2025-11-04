
from typing import Dict, Any, Optional

from .schemas import AgentResult


def agent_result_to_metrics(
    result: AgentResult,
    extra_fields: Dict[str, Any] = None
) -> Dict[str, Any]:
    metrics = {

        "cost_usd": result.total_cost_usd,
        "time_seconds": result.execution_time_seconds,
        "tokens": result.total_prompt_tokens + result.total_completion_tokens + result.total_reasoning_tokens,


        "iterations": result.iterations,
        "prompt_tokens": result.total_prompt_tokens,
        "completion_tokens": result.total_completion_tokens,
        "reasoning_tokens": result.total_reasoning_tokens,


        "success": result.success,
    }


    if result.error_message:
        metrics["error_message"] = result.error_message


    if result.run_log_path:
        metrics["run_log_path"] = str(result.run_log_path)


    if extra_fields:
        metrics.update(extra_fields)

    return metrics


def record_agent_result(
    metrics_manager,
    key: str,
    result: AgentResult,
    extra_fields: Optional[Dict[str, Any]] = None,
    accumulate: bool = False
):

    metrics = agent_result_to_metrics(result, extra_fields)


    cost_usd = metrics.pop('cost_usd', 0.0)
    time_seconds = metrics.pop('time_seconds', 0.0)
    tokens = metrics.pop('tokens', 0)






    metrics_manager.record(
        key=key,
        cost_usd=cost_usd,
        time_seconds=time_seconds,
        tokens=tokens,
        custom_metrics=metrics,
        accumulate=accumulate
    )
