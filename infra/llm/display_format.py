"""
Standard formatting for LLM call display across the codebase.

Provides consistent formatting for:
- Agent tool calls
- Single LLM calls
- Batch summaries

Format: Icon + Description + Time + Tokens + Cost
Example: "  🔧 get_frontmatter_grep_report()                 ( 1.1s)   3002in→77out+58r   0.06¢"
"""

from rich.text import Text


def format_token_string(
    prompt_tokens: int,
    completion_tokens: int,
    reasoning_tokens: int = 0
) -> str:
    """
    Format token counts as 'Nin→Nout+Nr' or 'Nin→Nout'.

    Args:
        prompt_tokens: Input tokens
        completion_tokens: Output tokens
        reasoning_tokens: Reasoning tokens (optional)

    Returns:
        Formatted string like "3002in→77out+58r" or "3002in→77out"
    """
    token_str = f"{prompt_tokens}in→{completion_tokens}out"
    if reasoning_tokens > 0:
        token_str += f"+{reasoning_tokens}r"
    return token_str


def format_individual_call(
    description: str,
    time_seconds: float,
    prompt_tokens: int,
    completion_tokens: int,
    reasoning_tokens: int,
    cost_usd: float,
    icon: str = "🔧",
    description_width: int = 45
) -> Text:
    """
    Format an individual LLM call with aligned metrics.

    Args:
        description: Call description (e.g., "get_frontmatter_grep_report()")
        time_seconds: Execution time
        prompt_tokens: Input tokens
        completion_tokens: Output tokens
        reasoning_tokens: Reasoning tokens
        cost_usd: Cost in USD
        icon: Display icon (default: 🔧)
        description_width: Width for description padding (default: 45)

    Returns:
        Rich Text object with formatted call

    Example:
        "  🔧 get_frontmatter_grep_report()                 ( 1.1s)   3002in→77out+58r   0.06¢"
    """
    text = Text()
    text.append(f"  {icon} ", style="dim")
    text.append(f"{description:<{description_width}}", style="")
    text.append(f" ({time_seconds:4.1f}s)", style="dim")

    token_str = format_token_string(prompt_tokens, completion_tokens, reasoning_tokens)
    text.append(f" {token_str:>18}", style="cyan")

    cost_cents = cost_usd * 100
    text.append(f" {cost_cents:5.2f}¢", style="yellow")

    return text


def format_batch_summary(
    batch_name: str,
    completed: int,
    total: int,
    time_seconds: float,
    prompt_tokens: int,
    completion_tokens: int,
    reasoning_tokens: int,
    cost_usd: float,
    unit: str = "requests",
    description_width: int = 45
) -> Text:
    """
    Format a batch processing summary with Rich colors and aligned metrics.

    Args:
        batch_name: Name of batch operation (e.g., "OCR (OlmOCR)", "Element identification")
        completed: Number of successful requests
        total: Total number of requests
        time_seconds: Total execution time
        prompt_tokens: Total input tokens
        completion_tokens: Total output tokens
        reasoning_tokens: Total reasoning tokens
        cost_usd: Total cost in USD
        unit: Unit name for items (default: "requests", can be "pages")
        description_width: Width for description padding (default: 45)

    Returns:
        Rich Text object with colored formatting

    Example:
        "✅ OCR (OlmOCR): 4/4 pages                      ( 6.9s) 13608in→1378out  0.1¢"
    """
    text = Text()
    text.append("✅ ", style="green")

    # Build description and pad it
    description = f"{batch_name}: {completed}/{total} {unit}"
    text.append(f"{description:<{description_width}}", style="")

    text.append(f" ({time_seconds:4.1f}s)", style="dim")

    token_str = format_token_string(prompt_tokens, completion_tokens, reasoning_tokens)
    text.append(f" {token_str:>22}", style="cyan")

    cost_cents = cost_usd * 100
    text.append(f" {cost_cents:5.2f}¢", style="yellow")

    return text
