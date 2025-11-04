import json
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional
from PIL import Image

from infra.llm.batch_client import LLMBatchClient
from infra.llm.models import LLMRequest
from infra.pipeline.logger import PipelineLogger
from infra.storage.book_storage import BookStorage
from infra.utils.pdf import downsample_for_vision
from ..schemas import TableOfContents, PageRange

from .prompts import TOC_STRUCTURE_DETECTION_PROMPT, build_detail_extraction_prompt


def load_toc_images(storage: BookStorage, toc_range: PageRange) -> List[Image.Image]:
    source_storage = storage.stage("source")
    toc_images = []

    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_file = source_storage.output_dir / f"page_{page_num:04d}.png"
        if page_file.exists():
            image = Image.open(page_file)
            image = downsample_for_vision(image)
            toc_images.append(image)

    return toc_images


def extract_toc_text(storage: BookStorage, toc_range: PageRange, stage_storage) -> str:
    toc_text_parts = []
    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        page_text = stage_storage.get_merged_page_text(storage, page_num)
        if page_text:
            toc_text_parts.append(f"=== Page {page_num} ===\n{page_text}\n")

    return "\n".join(toc_text_parts)


def detect_toc_structure(
    toc_images: List[Image.Image],
    model: str,
    logger: PipelineLogger,
    log_dir: Path,
    structure_notes_from_finder: Optional[Dict[int, str]] = None,
) -> Tuple[dict, Dict[str, Any]]:
    """
    Detect ToC structure from images.

    Returns:
        Tuple of (observations, metrics) where metrics contains:
        - cost_usd: LLM call cost
        - time_seconds: Execution time
        - completion_tokens: Output tokens
        - prompt_tokens: Input tokens
        - reasoning_tokens: Reasoning tokens (Grok only)
    """
    logger.info("Phase 2: Detecting ToC structure (document-level)", toc_pages=len(toc_images))
    print(f"   🔍 Phase 2: Analyzing document structure...")

    structure_schema = {
        "type": "object",
        "properties": {
            "visual_observations": {
                "type": "object",
                "properties": {
                    "approximate_entry_count": {"type": "string"},
                    "numbering_style": {"type": "string"},
                    "indentation_levels": {"type": "integer"},
                    "formatting_notes": {"type": "array", "items": {"type": "string"}},
                    "structural_features": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["approximate_entry_count", "numbering_style", "indentation_levels"]
            },
            "confidence": {"type": "number"},
            "notes": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["visual_observations", "confidence"]
    }

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "toc_structure_detection",
            "schema": structure_schema
        }
    }

    # Create structure detection request
    user_content = "Analyze these ToC pages and identify the overall document structure."
    if structure_notes_from_finder:
        notes_text = "\n\n".join([
            f"Page {page_num}: {observations}"
            for page_num, observations in sorted(structure_notes_from_finder.items())
        ])
        user_content += f"\n\nFinder agent observations (use as guidance):\n{notes_text}"

    request = LLMRequest(
        id="detect_structure",
        model=model,
        messages=[
            {"role": "system", "content": TOC_STRUCTURE_DETECTION_PROMPT},
            {"role": "user", "content": user_content}
        ],
        images=toc_images,
        temperature=0.0,
        max_tokens=2000,
        response_format=response_format
    )

    batch_client = LLMBatchClient(
        max_workers=1,
        max_retries=5,
        verbose=False,
        log_dir=log_dir
    )

    results = batch_client.process_batch([request])

    result = results[0]
    if not result.success:
        raise ValueError(f"Structure detection failed: {result.error_message}")

    structure_data = result.parsed_json
    observations = structure_data["visual_observations"]

    # Extract full metrics from LLMResult
    metrics = {
        'cost_usd': result.cost_usd,
        'time_seconds': result.execution_time_seconds,
        'completion_tokens': result.usage.get('completion_tokens', 0),
        'prompt_tokens': result.usage.get('prompt_tokens', 0),
        'reasoning_tokens': result.usage.get('reasoning_tokens', 0),
    }

    logger.info(
        "Structure observed",
        approx_entries=observations["approximate_entry_count"],
        numbering=observations["numbering_style"],
        levels=observations["indentation_levels"],
        confidence=structure_data.get("confidence", 0.0),
        cost=f"${metrics['cost_usd']:.4f}"
    )

    print(f"   ✓ Observations: {observations['approximate_entry_count']}, "
          f"numbering={observations['numbering_style']}, "
          f"levels={observations['indentation_levels']}")

    return observations, metrics


def extract_toc_entries(
    toc_images: List[Image.Image],
    toc_text: str,
    toc_range: PageRange,
    observations: dict,
    model: str,
    logger: PipelineLogger,
    log_dir: Path,
) -> Tuple[TableOfContents, Dict[str, Any]]:
    """
    Extract ToC entries from images and text.

    Returns:
        Tuple of (toc, metrics) where metrics contains:
        - cost_usd: LLM call cost
        - time_seconds: Execution time
        - completion_tokens: Output tokens
        - prompt_tokens: Input tokens
        - reasoning_tokens: Reasoning tokens (Grok only)
    """
    logger.info("Phase 3: Extracting ToC entries (structure-guided)", model=model)
    print(f"   📝 Phase 3: Extracting entries with structure guidance...")

    detail_prompt = build_detail_extraction_prompt(observations)

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "table_of_contents",
            "schema": TableOfContents.model_json_schema()
        }
    }

    user_message = f"""Extract ALL entries from this Table of Contents.

**ToC page range (scan pages):** {toc_range.start_page}-{toc_range.end_page}

**OCR Text (corrected):**

{toc_text}

Remember to:
1. Use IMAGES for structure (indentation, layout, visual hierarchy)
2. Use OCR TEXT for accurate titles and numbers
3. Run self-verification checks before returning"""

    request = LLMRequest(
        id="extract_details",
        model=model,
        messages=[
            {"role": "system", "content": detail_prompt},
            {"role": "user", "content": user_message}
        ],
        images=toc_images,
        temperature=0.0,
        max_tokens=4000,
        response_format=response_format
    )

    batch_client = LLMBatchClient(
        max_workers=1,
        max_retries=5,
        verbose=False,
        log_dir=log_dir
    )

    results = batch_client.process_batch([request])

    result = results[0]
    if not result.success:
        raise ValueError(f"Detail extraction failed: {result.error_message}")

    # Parse response as TableOfContents
    toc = TableOfContents(**result.parsed_json)

    # Extract full metrics from LLMResult
    metrics = {
        'cost_usd': result.cost_usd,
        'time_seconds': result.execution_time_seconds,
        'completion_tokens': result.usage.get('completion_tokens', 0),
        'prompt_tokens': result.usage.get('prompt_tokens', 0),
        'reasoning_tokens': result.usage.get('reasoning_tokens', 0),
    }

    print(f"   ✓ Extracted: {len(toc.entries)} entries ({toc.total_chapters} chapters, {toc.total_sections} sections)")

    logger.info(
        "ToC entries extracted",
        entries=len(toc.entries),
        chapters=toc.total_chapters,
        sections=toc.total_sections,
        confidence=f"{toc.parsing_confidence:.2f}",
        cost=f"${metrics['cost_usd']:.4f}",
    )

    return toc, metrics
