from rich.text import Text

def format_token_string(
    prompt_tokens: int,
    completion_tokens: int,
    reasoning_tokens: int = 0
) -> str:
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
    text = Text()
    text.append("✅ ", style="green")

    description = f"{batch_name}: {completed}/{total} {unit}"
    text.append(f"{description:<{description_width}}", style="")

    text.append(f" ({time_seconds:4.1f}s)", style="dim")

    token_str = format_token_string(prompt_tokens, completion_tokens, reasoning_tokens)
    text.append(f" {token_str:>22}", style="cyan")

    cost_cents = cost_usd * 100
    text.append(f" {cost_cents:5.2f}¢", style="yellow")

    return text
