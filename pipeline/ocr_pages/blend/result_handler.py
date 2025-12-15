"""
Handle blend results by applying corrections to Mistral output.
"""

from typing import List
import logging

from infra.llm.models import LLMResult
from infra.pipeline import PhaseStatusTracker
from ..schemas.blend import BlendedOcrPageOutput, TextCorrection


def apply_corrections(base_text: str, corrections: List[dict], logger=None) -> tuple[str, int]:
    """
    Apply corrections to base text.

    Returns: (corrected_text, num_applied)
    """
    result = base_text
    applied = 0

    for correction in corrections:
        original = correction.get("original", "")
        replacement = correction.get("replacement", "")
        reason = correction.get("reason", "")

        if not original:
            continue

        if original in result:
            result = result.replace(original, replacement, 1)
            applied += 1
            if logger:
                logger.debug(f"Applied: '{original[:30]}...' → '{replacement[:30]}...' ({reason})")
        else:
            if logger:
                logger.warning(f"Could not find: '{original[:50]}...'")

    return result, applied


def create_result_handler(tracker: PhaseStatusTracker):
    """Create result handler that applies corrections to Mistral output."""

    def on_result(result: LLMResult):
        if not result.success:
            tracker.logger.error(
                f"✗ Blend failed: {result.request.id}",
                request_id=result.request.id,
                error_type=result.error_type,
                error=result.error_message,
            )
            return

        if result.parsed_json is None:
            tracker.logger.error(f"✗ Blend returned None: {result.request.id}")
            return

        page_num = int(result.request.id.split("_")[1])

        # Load Mistral base text
        ocr_stage = tracker.storage.stage("ocr-pages")
        try:
            mistral_data = ocr_stage.load_page(page_num, subdir="mistral")
            base_text = mistral_data.get("markdown", "")
            base_source = "mistral"
        except FileNotFoundError:
            # Fallback to paddle if mistral missing
            try:
                paddle_data = ocr_stage.load_page(page_num, subdir="paddle")
                base_text = paddle_data.get("text", "")
                base_source = "paddle"
            except FileNotFoundError:
                tracker.logger.error(f"✗ No base OCR for page {page_num}")
                return

        # Get corrections from LLM response
        corrections_raw = result.parsed_json.get("corrections", [])
        confidence = result.parsed_json.get("confidence", 1.0)

        # Apply corrections
        corrected_text, num_applied = apply_corrections(
            base_text,
            corrections_raw,
            logger=tracker.logger
        )

        # Convert raw corrections to TextCorrection objects for storage
        corrections_typed = [
            TextCorrection(
                original=c.get("original", ""),
                replacement=c.get("replacement", ""),
                reason=c.get("reason", "")
            )
            for c in corrections_raw
            if c.get("original")  # Skip empty corrections
        ]

        # Save result with full audit trail
        output = BlendedOcrPageOutput(
            markdown=corrected_text,
            model_used=result.model_used or "unknown",
            base_source=base_source,
            corrections_applied=num_applied,
            corrections=corrections_typed,
            confidence=confidence,
        )

        tracker.stage_storage.save_page(
            page_num,
            output.model_dump(),
            schema=BlendedOcrPageOutput,
            subdir="blend"
        )

        result.record_to_metrics(
            metrics_manager=tracker.stage_storage.metrics_manager,
            key=f"{tracker.metrics_prefix}{result.request.id}",
        )

        # Log summary
        if num_applied > 0:
            tracker.logger.info(f"✓ {result.request.id}: {num_applied} corrections applied")
        else:
            tracker.logger.info(f"✓ {result.request.id}: no corrections needed")

    return on_result
