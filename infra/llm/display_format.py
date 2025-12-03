def format_token_count(count: int, width: int = 0) -> str:
    """
    Format token count with optional fixed width padding.

    Args:
        count: Token count to format
        width: Minimum width for right-aligned padding (0 = no padding)
    """
    if count >= 1_000_000:
        result = f"{count / 1_000_000:.1f}M"
    elif count >= 1_000:
        result = f"{count / 1_000:.1f}k"
    else:
        result = str(count)

    if width > 0:
        return result.rjust(width)
    return result


def format_token_string(
    prompt_tokens: int,
    completion_tokens: int,
    reasoning_tokens: int = 0,
    colored: bool = False,
    fixed_width: bool = False
) -> str:
    """
    Format token counts for display.

    Note: reasoning_tokens are a SUBSET of completion_tokens (not additive).
    When reasoning_tokens > 0, we show: (in)in->(out-r)out+(r)r
    This makes it clear that out + r = completion_tokens.

    Args:
        fixed_width: If True, use fixed-width formatting for vertical alignment.
                    Token counts padded to 6 chars each (handles up to 999.9M).
    """
    # Width of 6 handles: "999.9M", "999.9k", "999999" (6 digits max before k)
    width = 6 if fixed_width else 0
    in_tokens = format_token_count(prompt_tokens, width)

    if reasoning_tokens > 0:
        # Subtract reasoning from completion to show actual output content
        content_tokens = max(0, completion_tokens - reasoning_tokens)
        out_tokens = format_token_count(content_tokens, width)
        r_tokens = format_token_count(reasoning_tokens, width)

        if colored:
            return f"[green]({in_tokens})[/green]in→[blue]({out_tokens})[/blue]out+[magenta]({r_tokens})[/magenta]r"
        else:
            return f"({in_tokens})in->({out_tokens})out+({r_tokens})r"
    else:
        out_tokens = format_token_count(completion_tokens, width)
        # Pad the non-reasoning format to match width of reasoning format
        if fixed_width:
            # With reasoning: "(XXXXXX)in->(XXXXXX)out+(XXXXXX)r"
            # Without:        "(XXXXXX)in->(XXXXXX)out"
            # Missing: "+(XXXXXX)r" = 2 + 6 + 2 = 10 chars
            padding = " " * 10
            if colored:
                return f"[green]({in_tokens})[/green]in→[blue]({out_tokens})[/blue]out{padding}"
            else:
                return f"({in_tokens})in->({out_tokens})out{padding}"
        else:
            if colored:
                return f"[green]({in_tokens})[/green]in→[blue]({out_tokens})[/blue]out"
            else:
                return f"({in_tokens})in->({out_tokens})out"
