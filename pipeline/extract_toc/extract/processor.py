"""
Extract: Single-call complete ToC extraction.

Loads all ToC pages and extracts complete structure in one API call.
"""

import json
import time
from typing import Dict, List
from infra.pipeline.status import PhaseStatusTracker
from infra.llm.openrouter import OpenRouterTransport
from infra.llm.openrouter.pricing import CostCalculator
from ..schemas import PageRange
from .prompts import SYSTEM_PROMPT, build_user_prompt


def extract_complete_toc(tracker: PhaseStatusTracker, **kwargs) -> Dict:
    """
    Extract complete ToC structure in a single API call.

    Loads:
    - finder_result.json (ToC page range, structure summary)
    - Blended OCR text for all ToC pages

    Returns complete ToC structure.
    """
    tracker.logger.info("=== Extracting complete ToC (single-call) ===")

    storage = tracker.storage
    stage_storage = tracker.stage_storage

    # Load finder result
    finder_result = stage_storage.load_file("finder_result.json")

    # If no ToC found, skip extraction
    if not finder_result.get("toc_found") or not finder_result.get("toc_page_range"):
        tracker.logger.info("No ToC found - skipping extraction")
        stage_storage.save_file("toc.json", {
            "entries": [],
            "toc_page_range": None,
            "notes": ["No ToC found - extraction skipped"]
        })
        return {"status": "skipped", "reason": "No ToC found"}

    toc_range = PageRange(**finder_result["toc_page_range"])
    structure_summary = finder_result.get("structure_summary", {})

    # Load blended OCR text for all ToC pages
    tracker.logger.info(f"Loading {len(toc_range)} ToC pages...")
    toc_pages = []

    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        # Use blended OCR (combined mistral + olm + paddle)
        blended_stage = storage.stage("ocr-pages")
        try:
            blended_data = blended_stage.load_file(f"blended/page_{page_num:04d}.json")
            ocr_text = blended_data.get("text", "")
        except FileNotFoundError:
            tracker.logger.warning(f"Missing blended OCR for page {page_num}")
            # Fallback to single OCR engine
            try:
                olm_data = blended_stage.load_file(f"olm/page_{page_num:04d}.json")
                ocr_text = olm_data.get("text", "")
            except FileNotFoundError:
                tracker.logger.error(f"No OCR data found for page {page_num}")
                continue

        toc_pages.append({
            "page_num": page_num,
            "ocr_text": ocr_text
        })

    if not toc_pages:
        tracker.logger.error("No OCR text found for any ToC page")
        return {"status": "error", "reason": "No OCR data"}

    # Build prompt with all pages
    user_prompt = build_user_prompt(toc_pages, structure_summary)

    # Make single API call
    tracker.logger.info(f"Making single API call for {len(toc_pages)} pages...")

    model = "anthropic/claude-3.5-sonnet"  # Better for complex extraction
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    payload = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"}
    }

    # Call API
    transport = OpenRouterTransport(logger=tracker.logger)
    start_time = time.time()

    try:
        response = transport.post(payload, timeout=180)
    except Exception as e:
        tracker.logger.error(f"API call failed: {e}")
        return {"status": "error", "reason": f"API error: {str(e)}"}

    elapsed_time = time.time() - start_time

    # Extract result
    result = response["choices"][0]["message"]
    usage = response.get("usage", {})

    # Calculate cost
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    cost_calculator = CostCalculator()
    cost_usd = cost_calculator.calculate_cost(model, input_tokens, output_tokens)

    # Record metrics
    tracker.metrics_manager.record(
        key=f"{tracker.metrics_prefix}extract",
        cost_usd=cost_usd,
        time_seconds=elapsed_time,
        custom_metrics={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "toc_pages": len(toc_pages)
        }
    )

    # Parse response
    try:
        toc_data = json.loads(result.get("content", "{}"))
        entries = toc_data.get("entries", [])

        if not entries:
            tracker.logger.warning("No entries extracted from ToC")
        else:
            tracker.logger.info(f"Extracted {len(entries)} entries")

        # Build final ToC structure
        final_toc = {
            "entries": entries,
            "toc_page_range": {
                "start_page": toc_range.start_page,
                "end_page": toc_range.end_page
            },
            "total_entries": len(entries),
            "extraction_method": "single_call"
        }

        # Save to toc.json
        stage_storage.save_file("toc.json", final_toc)

        tracker.logger.info(f"Saved complete ToC: {len(entries)} entries")

        return final_toc

    except json.JSONDecodeError as e:
        tracker.logger.error(f"Failed to parse LLM response as JSON: {e}")
        tracker.logger.error(f"Response: {result.get('content', '')[:500]}...")
        return {"status": "error", "reason": "Invalid JSON response"}
