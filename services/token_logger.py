"""
Token usage logger for all Gemini API calls.
Reads usage_metadata from every generate_content response,
logs to console, and returns a structured dict.
"""

import logging

logger = logging.getLogger("token_usage")


def log_token_usage(
    service: str,
    model: str,
    response,
) -> dict:
    """
    Extract and log token usage from a Gemini generate_content response.

    Args:
        service : human label for the calling service, e.g. "OCR (questions)"
        model   : model name string, e.g. "gemini-2.0-flash-lite"
        response: the GenerateContentResponse object from generate_content()

    Returns:
        dict with keys:
            prompt_tokens     – input tokens (prompt + system instruction)
            output_tokens     – candidate / completion tokens
            thoughts_tokens   – tokens used during thinking (0 if not a thinking model)
            total_tokens      – prompt + output + thoughts
    """
    meta = getattr(response, "usage_metadata", None)

    if meta is None:
        logger.warning("[%s] usage_metadata not available on response.", service)
        return {
            "prompt_tokens":   0,
            "output_tokens":   0,
            "thoughts_tokens": 0,
            "total_tokens":    0,
        }

    prompt_tokens   = getattr(meta, "prompt_token_count",      0) or 0
    output_tokens   = getattr(meta, "candidates_token_count",  0) or 0
    thoughts_tokens = getattr(meta, "thoughts_token_count",    0) or 0
    total_tokens    = getattr(meta, "total_token_count",        0) or 0

    # If total_token_count is not populated, compute it
    if total_tokens == 0:
        total_tokens = prompt_tokens + output_tokens + thoughts_tokens

    usage = {
        "prompt_tokens":   prompt_tokens,
        "output_tokens":   output_tokens,
        "thoughts_tokens": thoughts_tokens,
        "total_tokens":    total_tokens,
    }

    # ── Console output ────────────────────────────────────────────────────────
    parts = [
        f"  input  : {prompt_tokens:,}",
        f"  output : {output_tokens:,}",
    ]
    if thoughts_tokens:
        parts.append(f"  thinking: {thoughts_tokens:,}")
    parts.append(f"  total  : {total_tokens:,}")

    print(
        f"\n[Token Usage] {service} | model: {model}\n" + "\n".join(parts)
    )

    return usage