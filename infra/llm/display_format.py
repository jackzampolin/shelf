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
    reasoning_tokens: int = 0,
    colored: bool = False
) -> str:
    """
    Format token counts for display.

    Note: reasoning_tokens are a SUBSET of completion_tokens (not additive).
    When reasoning_tokens > 0, we show: (in)in->(out-r)out+(r)r
    This makes it clear that out + r = completion_tokens.
    """
    in_tokens = format_token_count(prompt_tokens)

    if reasoning_tokens > 0:
        # Subtract reasoning from completion to show actual output content
        content_tokens = completion_tokens - reasoning_tokens
        out_tokens = format_token_count(content_tokens)
        r_tokens = format_token_count(reasoning_tokens)

        if colored:
            return f"[green]({in_tokens})[/green]in→[blue]({out_tokens})[/blue]out+[magenta]({r_tokens})[/magenta]r"
        else:
            return f"({in_tokens})in->({out_tokens})out+({r_tokens})r"
    else:
        out_tokens = format_token_count(completion_tokens)
        if colored:
            return f"[green]({in_tokens})[/green]in→[blue]({out_tokens})[/blue]out"
        else:
            return f"({in_tokens})in->({out_tokens})out"
