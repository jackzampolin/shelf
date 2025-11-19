"""
Validation: Analyze ToC internally for corrections

Single LLM call that analyzes the raw ToC and proposes corrections based on:
- Assembly issues (continuations across page breaks)
- OCR patterns (repeated errors)
- Obvious errors (incomplete titles, missing data)
"""

import json
from typing import Dict, List
from infra.pipeline.status import PhaseStatusTracker
from infra.llm.client import LLMClient

from .prompts import SYSTEM_PROMPT, build_user_prompt


def validate_toc_with_structure(
    tracker: PhaseStatusTracker,
    **kwargs
) -> Dict:
    """
    Validate ToC internally and propose corrections.

    Single LLM call analyzing the raw ToC for assembly issues,
    OCR patterns, and obvious errors.

    Returns corrections (diffs) instead of rewriting entire ToC.
    """
    model = kwargs.get("model")

    tracker.logger.info("=== Validating ToC (internal analysis) ===")

    storage = tracker.storage
    stage_storage = tracker.stage_storage

    # Load raw ToC entries from detection phase (phase 2)
    # finder_result.json comes from find phase (phase 1, same stage)
    finder_result = stage_storage.load_file("finder_result.json")

    # If no ToC was found, skip validation
    if not finder_result.get("toc_found") or not finder_result.get("toc_page_range"):
        tracker.logger.info("No ToC found - skipping validation")
        # Save empty corrections file to mark phase as complete
        stage_storage.save_file("corrections.json", {
            "corrections": [],
            "analysis": {"note": "No ToC found - validation skipped"},
            "validation_stats": {"entries_reviewed": 0, "corrections_proposed": 0}
        })
        return {"status": "skipped", "reason": "No ToC found"}

    from ..schemas import PageRange
    toc_range = PageRange(**finder_result["toc_page_range"])

    # Load all page files from detection
    raw_entries = []
    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_file = f"page_{page_num:04d}.json"
        try:
            page_data = stage_storage.load_file(page_file)
            # Extract entries from this page
            page_entries = page_data.get("entries", [])
            for entry in page_entries:
                # Mark which page this entry came from (for assembly)
                entry["_source_page"] = page_num
                raw_entries.append(entry)
        except FileNotFoundError:
            tracker.logger.warning(f"Missing ToC page file: {page_file}")

    if not raw_entries:
        tracker.logger.warning("No ToC entries found from detection phase")
        return {"corrections": []}

    tracker.logger.info(f"Loaded {len(raw_entries)} raw entries from {toc_range.end_page - toc_range.start_page + 1} pages")

    # Build prompt showing all entries
    user_prompt = build_user_prompt(raw_entries)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    # Define structured output schema for corrections
    correction_schema = {
        "type": "object",
        "properties": {
            "entry_index": {
                "type": "integer",
                "description": "Index of ToC entry to correct"
            },
            "field": {
                "type": "string",
                "description": "Field to correct: title, printed_page_number, level_name, entry_number, _delete"
            },
            "old": {
                "description": "Current value (must match exactly!)"
            },
            "new": {
                "description": "Corrected value"
            },
            "confidence": {
                "type": "number",
                "minimum": 0.7,
                "maximum": 1.0,
                "description": "Confidence in this correction (0.7-1.0)"
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of why this correction is needed"
            }
        },
        "required": ["entry_index", "field", "old", "new", "confidence", "reasoning"],
        "additionalProperties": False
    }

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_corrections",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "corrections": {
                        "type": "array",
                        "items": correction_schema,
                        "description": "Array of corrections to apply (empty if no corrections needed)"
                    },
                    "analysis": {
                        "type": "object",
                        "properties": {
                            "toc_quality": {
                                "type": "string",
                                "enum": ["high", "medium", "low"],
                                "description": "Overall quality assessment of the ToC"
                            },
                            "patterns_found": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of patterns observed (problems and confirmations)"
                            },
                            "observations": {
                                "type": "string",
                                "description": "Brief narrative summary of ToC quality and findings"
                            }
                        },
                        "required": ["toc_quality", "patterns_found", "observations"],
                        "additionalProperties": False
                    }
                },
                "required": ["corrections", "analysis"],
                "additionalProperties": False
            }
        }
    }

    # Single LLM call
    tracker.logger.info(f"Analyzing {len(raw_entries)} entries for corrections")
    llm_client = LLMClient()

    result = llm_client.call(
        model=model,
        messages=messages,
        temperature=0.0,
        response_format=response_format,
        timeout=300
    )

    if not result.success:
        tracker.logger.error(f"Validation LLM call failed: {result.error_message}")
        return {"corrections": [], "error": result.error_message}

    # Parse corrections and analysis from result
    corrections = result.parsed_json.get("corrections", [])
    analysis = result.parsed_json.get("analysis", {})

    tracker.logger.info(f"Validation complete: {len(corrections)} corrections proposed")

    # Log analysis
    toc_quality = analysis.get("toc_quality", "unknown")
    observations = analysis.get("observations", "")
    tracker.logger.info(f"  ToC quality: {toc_quality}")
    if observations:
        tracker.logger.info(f"  Observations: {observations}")

    # Log correction summary
    if corrections:
        by_field = {}
        for corr in corrections:
            field = corr.get("field", "unknown")
            by_field[field] = by_field.get(field, 0) + 1

        summary = ", ".join([f"{count} {field}" for field, count in by_field.items()])
        tracker.logger.info(f"  Corrections: {summary}")

    # Save corrections and analysis
    output_data = {
        "corrections": corrections,
        "analysis": analysis,
        "validation_stats": {
            "entries_reviewed": len(raw_entries),
            "corrections_proposed": len(corrections),
        }
    }

    output_path = tracker.phase_dir / "corrections.json"
    output_path.write_text(json.dumps(output_data, indent=2))

    # Record metrics from LLM result
    result.record_to_metrics(
        tracker.metrics_manager,
        key=f"{tracker.metrics_prefix}validation",
        extra_fields={
            "corrections_proposed": len(corrections),
        }
    )

    return output_data
