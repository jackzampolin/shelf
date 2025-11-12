"""
Assembly: Lightweight ToC Assembly

Merges ToC entries from multiple pages, handles continuations, validates sequence.
"""

import json
import time
from typing import Dict, Tuple

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.client import LLMClient
from infra.config import Config

from ..schemas import PageRange
from .prompts import SYSTEM_PROMPT, build_user_prompt


def assemble_toc(
    storage: BookStorage,
    toc_range: PageRange,
    logger: PipelineLogger,
    model: str = None
) -> Dict[str, any]:
    """
    Assemble final ToC from extracted entries across pages.

    This is a lightweight operation that:
    - Merges continuation entries across pages
    - Validates entry sequence
    - Counts chapters and sections
    - Trusts Phase 1's hierarchy determination

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        logger: Pipeline logger
        model: Text model to use (default: Config.text_model_expensive)

    Returns:
        results_data: {"toc": {...}, "validation": {...}, "notes": "..."}
    """
    model = model or Config.text_model_expensive
    llm_client = LLMClient()
    stage_storage = storage.stage('extract-toc')

    logger.info("Assembling ToC from extracted entries")

    start_time = time.time()

    # Load entries from Phase 1
    entries_data = stage_storage.load_file("entries.json")
    pages_data = entries_data.get("pages", [])

    entries_by_page = {p["page_num"]: p for p in pages_data}

    user_prompt = build_user_prompt(entries_by_page, toc_range)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    # Build structured output schema from our Pydantic models
    from ..schemas import TableOfContents, ToCEntry, PageRange

    toc_entry_schema = {
        "type": "object",
        "properties": {
            "entry_number": {"type": ["string", "null"]},
            "title": {"type": "string", "minLength": 1},
            "level": {"type": "integer", "minimum": 1, "maximum": 3},
            "level_name": {"type": ["string", "null"]},
            "printed_page_number": {"type": ["string", "null"]}
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
            "entries_by_level": {
                "type": "object",
                "additionalProperties": {"type": "integer", "minimum": 0}
            },
            "parsing_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "notes": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["entries", "toc_page_range", "entries_by_level", "parsing_confidence"],
        "additionalProperties": False
    }

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_assembly",
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

    # Single LLM call - lightweight assembly (now returns LLMResult)
    result = llm_client.call(
        model=model,
        messages=messages,
        temperature=0.0,
        response_format=response_format,
        timeout=300
    )

    # Print summary line after completion
    from infra.llm.batch.progress.display import format_batch_summary

    summary = format_batch_summary(
        batch_name="ToC assembly",
        completed=1,
        total=1,
        time_seconds=result.total_time_seconds,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        reasoning_tokens=result.reasoning_tokens,
        cost_usd=result.cost_usd,
        unit="call"
    )
    from rich.console import Console
    Console().print(summary)

    try:
        # LLMResult.parsed_json contains the parsed JSON (if response_format was set)
        response_data = result.parsed_json if result.parsed_json else json.loads(result.response)

        toc_data = response_data.get("toc", {})
        validation_data = response_data.get("validation", {})
        notes = response_data.get("notes", "")

        total_entries = len(toc_data.get("entries", []))
        confidence = validation_data.get("confidence", 0.0)
        issues = validation_data.get("issues_found", [])

        logger.info(f"  Assembled ToC: {total_entries} entries, confidence={confidence:.2f}, {len(issues)} issues")

        results_data = {
            "toc": toc_data,
            "validation": validation_data,
            "notes": notes,
            "search_strategy": "vision_agent_with_ocr"
        }

        # Save toc.json
        stage_storage.save_file("toc.json", results_data)
        logger.info(f"Saved toc.json ({total_entries} entries)")

        # Record metrics
        reasoning_details = usage.get("completion_tokens_details", {})
        stage_storage.metrics_manager.record(
            key="phase2_assembly",
            cost_usd=cost,
            time_seconds=elapsed_time,
            custom_metrics={
                "phase": "assembly",
                "total_entries": total_entries,
                "confidence": confidence,
                "issues_found": len(issues),
                "completion_tokens": usage.get("completion_tokens", 0),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "reasoning_tokens": reasoning_details.get("reasoning_tokens", 0),
            }
        )

        return results_data

    except Exception as e:
        logger.error(f"  Failed to parse assembly response: {e}")
        raise
