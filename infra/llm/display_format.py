"""Display formatting utilities for LLM token counts."""


def format_token_count(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    elif count >= 1_000:
        return f"{count / 1_000:.1f}k"
    else:
        return str(count)


def format_token_string(
    prompt_tokens: int,
    completion_tokens: int,
    reasoning_tokens: int = 0
) -> str:
    in_tokens = format_token_count(prompt_tokens)
    out_tokens = format_token_count(completion_tokens)

    token_str = f"{in_tokens}in→{out_tokens}out"
    if reasoning_tokens > 0:
        r_tokens = format_token_count(reasoning_tokens)
        token_str += f"+{r_tokens}r"
    return token_str
