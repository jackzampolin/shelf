"""
Phase 4: Validation and Assembly

Reviews all identified elements, validates consistency, and assembles final ToC.
"""

import json
import time
from typing import Dict, Tuple

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.client import LLMClient
from infra.config import Config

from ..schemas import PageRange
from ..storage import ExtractTocStageStorage
from .prompts import SYSTEM_PROMPT, build_user_prompt


def validate_and_assemble(
    storage: BookStorage,
    toc_range: PageRange,
    logger: PipelineLogger,
    model: str = None
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    Validate and assemble final ToC from identified elements.

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        logger: Pipeline logger
        model: Text model to use (default: Config.text_model_expensive)

    Returns:
        Tuple of (results_data, metrics)
        - results_data: {"toc": {...}, "validation": {...}, "notes": "..."}
        - metrics: {"cost_usd": float, "time_seconds": float, ...}
    """
    model = model or Config.text_model_expensive
    llm_client = LLMClient()
    stage_storage = ExtractTocStageStorage(stage_name='extract-toc')

    logger.info("Validating and assembling ToC from identified elements")

    start_time = time.time()

    elements_data = stage_storage.load_elements_identified(storage)
    pages_data = elements_data.get("pages", [])

    elements_by_page = {p["page_num"]: p for p in pages_data}

    user_prompt = build_user_prompt(elements_by_page, toc_range)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    # Build structured output schema from our Pydantic models
    from ..schemas import TableOfContents, ToCEntry, PageRange

    toc_entry_schema = {
        "type": "object",
        "properties": {
            "chapter_number": {"type": ["integer", "null"], "minimum": 1},
            "title": {"type": "string", "minLength": 1},
            "printed_page_number": {"type": ["string", "null"]},
            "level": {"type": "integer", "minimum": 1, "maximum": 3}
        },
        "required": ["title", "level"],
        "additionalProperties": False
    }

    toc_schema = {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": toc_entry_schema
            },
            "toc_page_range": {
                "type": "object",
                "properties": {
                    "start_page": {"type": "integer", "minimum": 1},
                    "end_page": {"type": "integer", "minimum": 1}
                },
                "required": ["start_page", "end_page"],
                "additionalProperties": False
            },
            "total_chapters": {"type": "integer", "minimum": 0},
            "total_sections": {"type": "integer", "minimum": 0},
            "parsing_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "notes": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["entries", "toc_page_range", "total_chapters", "total_sections", "parsing_confidence"],
        "additionalProperties": False
    }

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_validation",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "toc": toc_schema,
                    "validation": {
                        "type": "object",
                        "properties": {
                            "issues_found": {"type": "array", "items": {"type": "string"}},
                            "continuations_resolved": {"type": "integer"},
                            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                        },
                        "required": ["issues_found", "continuations_resolved", "confidence"],
                        "additionalProperties": False
                    },
                    "notes": {"type": "string"}
                },
                "required": ["toc", "validation", "notes"],
                "additionalProperties": False
            }
        }
    }

    # Single LLM call - no progress display needed (phase header already shown)
    response_text, usage, cost = llm_client.call(
        model=model,
        messages=messages,
        temperature=0.0,
        response_format=response_format,
        timeout=300
    )

    elapsed_time = time.time() - start_time

    # Print summary line after completion
    from infra.llm.display_format import format_batch_summary
    reasoning_details = usage.get("completion_tokens_details", {})
    reasoning_tokens = reasoning_details.get("reasoning_tokens", 0)

    summary = format_batch_summary(
        batch_name="ToC validation",
        completed=1,
        total=1,
        time_seconds=elapsed_time,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        reasoning_tokens=reasoning_tokens,
        cost_usd=cost,
        unit="call"
    )
    from rich.console import Console
    Console().print(summary)

    try:
        response_data = json.loads(response_text)

        toc_data = response_data.get("toc", {})
        validation_data = response_data.get("validation", {})
        notes = response_data.get("notes", "")

        total_entries = validation_data.get("total_entries", 0)
        confidence = validation_data.get("confidence", 0.0)
        issues = validation_data.get("issues_found", [])

        logger.info(f"  Assembled ToC: {total_entries} entries, confidence={confidence:.2f}, {len(issues)} issues")

        results_data = {
            "toc": toc_data,
            "validation": validation_data,
            "notes": notes,
            "search_strategy": "vision_agent_with_ocr"
        }

        reasoning_details = usage.get("completion_tokens_details", {})

        metrics = {
            "cost_usd": cost,
            "time_seconds": elapsed_time,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "reasoning_tokens": reasoning_details.get("reasoning_tokens", 0),
            "total_entries": total_entries,
            "confidence": confidence,
            "issues_found": len(issues),
        }

        return results_data, metrics

    except Exception as e:
        logger.error(f"  Failed to parse validation/assembly response: {e}")
        raise
