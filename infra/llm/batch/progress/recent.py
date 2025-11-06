#!/usr/bin/env python3
import re
from typing import Dict, List, Tuple


def build_recent_lines(results_dict: Dict, metrics_manager, model: str, max_recent: int = 5) -> List[Tuple[str, str]]:
    """Build recent completion lines from worker results + metrics.json."""
    if not results_dict:
        return []

    # Sort by most recent (results dict should have completion order)
    sorted_results = sorted(
        results_dict.items(),
        key=lambda x: x[1].total_time_seconds,
        reverse=True
    )[:max_recent]

    lines = []
    for req_id, result in sorted_results:
        page_id = req_id.replace('page_', 'p')

        if result.success:
            # Try to get detailed metrics from metrics.json
            metrics = None
            if metrics_manager:
                try:
                    match = re.search(r'page_(\d{4})', req_id)
                    metrics_key = f"page_{match.group(1)}" if match else req_id
                    metrics = metrics_manager.get(metrics_key)
                except:
                    pass

            if metrics:
                parts = []
                if metrics.get('ttft_seconds'):
                    parts.append(f"FT {metrics['ttft_seconds']:.1f}s")
                if metrics.get('execution_time_seconds'):
                    parts.append(f"Exec {metrics['execution_time_seconds']:.1f}s")

                if metrics.get('prompt_tokens') is not None and metrics.get('completion_tokens') is not None:
                    tok_str = f"{metrics['prompt_tokens']}→{metrics['completion_tokens']}"
                    reasoning_tokens = metrics.get('reasoning_tokens', 0)
                    if reasoning_tokens > 0:
                        tok_str += f"+{reasoning_tokens}r"
                    parts.append(f"{tok_str} tok")
                elif metrics.get('tokens'):
                    parts.append(f"{metrics['tokens']} tok")

                cost_cents = metrics.get('cost_usd', 0) * 100
                parts.append(f"{cost_cents:.2f}¢")

                model_suffix = ""
                if metrics.get('model_used') and metrics['model_used'] != model:
                    model_suffix = f" [dim][{metrics['model_used'].split('/')[-1]}][/dim]"

                text = f"{page_id}: [bold green]✓[/bold green] [dim]({', '.join(parts)}){model_suffix}[/dim]"
            else:
                # Fallback to result data
                ttft_str = f", TTFT {result.ttft_seconds:.2f}s" if result.ttft_seconds else ""
                model_suffix = f" [dim][{result.model_used.split('/')[-1]}][/dim]" if result.model_used and result.model_used != model else ""
                cost_cents = (result.cost_usd or 0) * 100
                text = f"{page_id}: [bold green]✓[/bold green] [dim]({result.execution_time_seconds:.1f}s{ttft_str}, {cost_cents:.2f}¢){model_suffix}[/dim]"
        else:
            # Format failure
            error_code = extract_error_code(result.error_message)
            retry_count = getattr(result.request, '_retry_count', 0)
            retry_suffix = f", retry {retry_count}" if retry_count > 0 else ""
            model_suffix = f" [dim][{result.model_used.split('/')[-1]}][/dim]" if result.model_used else ""
            text = f"{page_id}: [bold red]✗[/bold red] [dim]({result.execution_time_seconds:.1f}s{retry_suffix})[/dim] - [yellow]{error_code}[/yellow]{model_suffix}"

        lines.append((req_id, text))

    return lines


def extract_error_code(error_message: str) -> str:
    """Extract readable error code from error message."""
    if not error_message:
        return "unknown"

    error_lower = error_message.lower()
    if '413' in error_message:
        return "413"
    elif '422' in error_message:
        return "422"
    elif '429' in error_message or 'rate_limit' in error_lower:
        return "429"
    elif '5' in error_message and 'server' in error_lower:
        return "5xx"
    elif '4' in error_message and ('client' in error_lower or 'error' in error_lower):
        return "4xx"
    elif 'timeout' in error_lower:
        return "timeout"
    else:
        return error_message[:20]
