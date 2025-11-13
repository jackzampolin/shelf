"""
OCR quality filtering utilities.

Detects and filters low-quality OCR output that would bloat prompts
and slow down LLM processing.
"""

from typing import Dict


def filter_ocr_quality(
    mistral_text: str,
    olm_text: str,
    paddle_text: str,
    inflation_threshold: float = 2.0
) -> Dict[str, any]:
    """
    Detects and filters low-quality OCR output based on size inflation.

    PADDLE OCR sometimes hallucinates massive garbage output (repetitive dots)
    on pages with Table of Contents leader dots, indexes, or decorative elements.
    This function detects when one OCR source produces abnormally large output
    compared to others and filters it out.

    Args:
        mistral_text: Text from Mistral OCR
        olm_text: Text from OLM OCR
        paddle_text: Text from PADDLE OCR
        inflation_threshold: Max ratio before flagging as garbage (default: 2.0x)

    Returns:
        {
            "mistral": str,      # Original or filtered
            "olm": str,          # Original or filtered
            "paddle": str,       # Original or empty if filtered
            "filtered": bool,    # True if any OCR was filtered
            "reason": str        # Why filtering occurred
        }
    """
    mistral_len = len(mistral_text)
    olm_len = len(olm_text)
    paddle_len = len(paddle_text)

    # Calculate average of Mistral and OLM (the reliable OCR engines)
    baseline_avg = (mistral_len + olm_len) / 2.0

    # Special case: If baseline is very small but PADDLE has lots of text,
    # it's likely garbage (e.g., photo pages with PADDLE hallucinations)
    if baseline_avg < 100:
        if paddle_len > 1000:  # PADDLE has >1000 chars but Mistral/OLM nearly empty
            inflation_ratio = paddle_len / max(baseline_avg, 1)  # Avoid div by zero
            return {
                "mistral": mistral_text,
                "olm": olm_text,
                "paddle": "",  # Filter out PADDLE garbage
                "filtered": True,
                "reason": f"PADDLE output ({paddle_len} chars) on near-blank page (Mistral/OLM avg: {baseline_avg:.0f} chars) - likely hallucination"
            }
        # Truly blank page - keep all OCR as-is
        return {
            "mistral": mistral_text,
            "olm": olm_text,
            "paddle": paddle_text,
            "filtered": False,
            "reason": None
        }

    # Check if PADDLE is abnormally inflated
    if paddle_len > baseline_avg * inflation_threshold:
        inflation_ratio = paddle_len / baseline_avg
        return {
            "mistral": mistral_text,
            "olm": olm_text,
            "paddle": "",  # Filter out PADDLE garbage
            "filtered": True,
            "reason": f"PADDLE output ({paddle_len} chars) is {inflation_ratio:.1f}x larger than Mistral/OLM average ({baseline_avg:.0f} chars)"
        }

    # All OCR outputs look normal
    return {
        "mistral": mistral_text,
        "olm": olm_text,
        "paddle": paddle_text,
        "filtered": False,
        "reason": None
    }


__all__ = ["filter_ocr_quality"]
