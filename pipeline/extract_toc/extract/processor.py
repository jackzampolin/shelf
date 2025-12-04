"""
Extract: Single-call complete ToC extraction.

Loads all ToC pages and extracts complete structure in one API call.
Uses structured outputs to guarantee valid JSON.
"""

import os
import time
from typing import Dict
from rich.console import Console
from rich.live import Live
from rich.text import Text
from infra.pipeline.status import PhaseStatusTracker
from infra.llm import LLMClient
from infra.llm.display import DisplayStats, print_phase_complete
from infra.config import Config
from ..schemas import PageRange
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import ToCExtractionOutput


def is_headless():
    """Check if running in headless mode."""
    return os.environ.get('SCANSHELF_HEADLESS', '').lower() in ('1', 'true', 'yes')


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
            blended_data = blended_stage.load_file(f"blend/page_{page_num:04d}.json")
            ocr_text = blended_data.get("markdown") or blended_data.get("text", "")
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

    # Make single API call with structured output
    tracker.logger.info(f"Making single API call for {len(toc_pages)} pages...")

    model = Config.vision_model_primary
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    # Use structured output - OpenRouter guarantees valid JSON
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_extraction",
            "strict": True,
            "schema": ToCExtractionOutput.model_json_schema()
        }
    }

    client = LLMClient(logger=tracker.logger)
    console = Console()
    start_time = time.time()

    # Show progress spinner during API call
    def make_progress_text(elapsed: float) -> Text:
        text = Text()
        text.append("⏳ ", style="yellow")
        text.append(f"toc-extract: extracting from {len(toc_pages)} pages", style="")
        text.append(f" ({elapsed:.1f}s)", style="dim")
        return text

    result = None
    error = None

    if is_headless():
        # No progress display in headless mode
        try:
            result = client.call(
                model=model,
                messages=messages,
                response_format=response_format,
                timeout=300
            )
        except Exception as e:
            error = e
    else:
        # Show live progress
        with Live(make_progress_text(0), console=console, refresh_per_second=2, transient=True) as live:
            try:
                # Update progress in background would be nice, but for now just show spinner
                result = client.call(
                    model=model,
                    messages=messages,
                    response_format=response_format,
                    timeout=300
                )
            except Exception as e:
                error = e

    elapsed_time = time.time() - start_time

    if error:
        tracker.logger.error(f"API call failed: {error}")
        return {"status": "error", "reason": f"API error: {str(error)}"}

    # Record metrics
    tracker.metrics_manager.record(
        key=f"{tracker.metrics_prefix}extract",
        cost_usd=result.cost_usd,
        time_seconds=elapsed_time,
        custom_metrics={
            "input_tokens": result.prompt_tokens,
            "output_tokens": result.completion_tokens,
            "toc_pages": len(toc_pages)
        }
    )

    if not result.success:
        tracker.logger.error(f"LLM call failed: {result.error_message}")
        # Print error summary
        error_text = Text()
        error_text.append("❌ ", style="red")
        error_text.append(f"toc-extract: failed", style="red")
        error_text.append(f" ({elapsed_time:.1f}s)", style="dim")
        console.print(error_text)
        return {"status": "error", "reason": result.error_message}

    # Structured output guarantees valid JSON
    entries = result.parsed_json.get("entries", [])

    # Print success summary using standard format
    print_phase_complete("toc-extract", DisplayStats(
        completed=len(entries),
        total=len(entries),
        time_seconds=elapsed_time,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        reasoning_tokens=result.reasoning_tokens or 0,
        cost_usd=result.cost_usd,
    ))

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
