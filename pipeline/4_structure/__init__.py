"""
Stage 4: Structure Detection

ToC-first approach to detecting book structure:
1. Parse ToC with LLM
2. Build PDF ↔ Book page mapping from ToC + labels
3. Detect chapter boundaries from labels
4. Validate ALL boundaries with LLM (liberal strategy)
5. Assemble final chapter structure

Entry point: detect_structure()
"""

from pathlib import Path
from datetime import datetime
from typing import Optional, List
import json
import time
import importlib

import logging

from infra.checkpoint import CheckpointManager

# Import schemas from numeric module names using importlib
merge_schemas = importlib.import_module('pipeline.3_merge.schemas')
MergedPageOutput = getattr(merge_schemas, 'MergedPageOutput')

structure_schemas = importlib.import_module('pipeline.4_structure.schemas')
TocOutput = getattr(structure_schemas, 'TocOutput')
PageMappingOutput = getattr(structure_schemas, 'PageMappingOutput')
BoundaryCandidatesOutput = getattr(structure_schemas, 'BoundaryCandidatesOutput')
ValidatedBoundariesOutput = getattr(structure_schemas, 'ValidatedBoundariesOutput')
ChaptersOutput = getattr(structure_schemas, 'ChaptersOutput')

toc_parser_module = importlib.import_module('pipeline.4_structure.toc_parser')
parse_toc = getattr(toc_parser_module, 'parse_toc')

logger = logging.getLogger(__name__)


def detect_structure(
    book_dir: Path,
    scan_id: str,
    checkpoint_manager: CheckpointManager,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> ChaptersOutput:
    """
    Detect book structure using ToC-first approach.

    Args:
        book_dir: Book directory containing processed/ pages
        scan_id: Scan identifier
        checkpoint_manager: Checkpoint manager for resume capability
        start_page: Optional start page (for testing)
        end_page: Optional end page (for testing)

    Returns:
        ChaptersOutput: Complete book structure with chapters

    Raises:
        FileNotFoundError: If processed pages not found
        ValueError: If ToC cannot be parsed or structure invalid
    """
    logger.info(f"Starting structure detection for {scan_id}")
    start_time = time.time()

    # Create output directory
    chapters_dir = book_dir / "chapters"
    chapters_dir.mkdir(exist_ok=True)

    # Load all processed pages
    processed_dir = book_dir / "processed"
    if not processed_dir.exists():
        raise FileNotFoundError(f"Processed directory not found: {processed_dir}")

    pages = _load_processed_pages(processed_dir, start_page, end_page)
    logger.info(f"Loaded {len(pages)} processed pages")

    # Track costs
    total_cost = 0.0

    # Substage 4a: Parse ToC
    toc_output = _parse_toc(pages, scan_id, chapters_dir)
    logger.info(f"Parsed ToC with {toc_output.total_entries} entries")
    total_cost += toc_output.cost

    # Substage 4b: Build page mapping
    page_mapping = _build_page_mapping(pages, toc_output, scan_id, chapters_dir)
    logger.info(f"Built page mapping: {len(page_mapping.mappings)} pages mapped")

    # Substage 4c: Detect boundary candidates
    candidates = _detect_boundary_candidates(pages, toc_output, page_mapping, scan_id, chapters_dir)
    logger.info(f"Detected {candidates.total_candidates} chapter boundary candidates")

    # Substage 4d: LLM validate all boundaries
    validated = _validate_boundaries_with_llm(
        pages, candidates, page_mapping, scan_id, chapters_dir
    )
    logger.info(
        f"Validated {validated.total_boundaries} boundaries "
        f"({validated.llm_corrections_made} corrections made)"
    )
    total_cost += validated.validation_cost

    # Substage 4e: Assemble final chapter structure
    chapters_output = _assemble_chapters(
        validated, page_mapping, len(pages), scan_id, chapters_dir, total_cost, start_time
    )
    logger.info(
        f"Assembled {chapters_output.total_chapters} chapters "
        f"(cost: ${chapters_output.total_cost:.3f}, time: {chapters_output.processing_time_seconds:.1f}s)"
    )

    # Mark checkpoint complete
    checkpoint_manager.mark_completed()

    return chapters_output


def _load_processed_pages(
    processed_dir: Path,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> List[MergedPageOutput]:
    """Load all processed pages in order."""
    # Find all page files
    page_files = sorted(processed_dir.glob("page_*.json"))
    if not page_files:
        raise FileNotFoundError(f"No processed pages found in {processed_dir}")

    # Filter by page range if specified
    if start_page or end_page:
        page_files = [
            f for f in page_files
            if (start_page is None or int(f.stem.split("_")[1]) >= start_page)
            and (end_page is None or int(f.stem.split("_")[1]) <= end_page)
        ]

    # Load and parse
    pages = []
    for page_file in page_files:
        with open(page_file, "r") as f:
            page_data = json.load(f)
            pages.append(MergedPageOutput(**page_data))

    return pages


def _parse_toc(
    pages: List[MergedPageOutput],
    scan_id: str,
    output_dir: Path,
) -> TocOutput:
    """
    Substage 4a: Parse Table of Contents.

    Finds TABLE_OF_CONTENTS labeled pages and uses LLM to extract
    structured entries with chapter titles and page numbers.
    """
    return parse_toc(pages, scan_id, output_dir)


def _build_page_mapping(
    pages: List[MergedPageOutput],
    toc: TocOutput,
    scan_id: str,
    output_dir: Path,
) -> PageMappingOutput:
    """
    Substage 4b: Build PDF ↔ Book page mapping.

    Matches ToC entries to CHAPTER_HEADING labels to derive
    the mapping between PDF pages and book page numbers.
    """
    # TODO: Implement page mapping
    logger.warning("Page mapping not yet implemented, using placeholder")

    mapping_output = PageMappingOutput(
        scan_id=scan_id,
        total_pages=len(pages),
        mappings=[],
        front_matter_pages=[],
        body_pages=[],
        back_matter_pages=[],
        toc_match_count=0,
        header_validated_count=0,
        unmapped_pages=len(pages),
        timestamp=datetime.now().isoformat(),
    )

    # Save checkpoint
    output_file = output_dir / "page_mapping.json"
    with open(output_file, "w") as f:
        f.write(mapping_output.model_dump_json(indent=2))
    logger.info(f"Saved page mapping to {output_file}")

    return mapping_output


def _detect_boundary_candidates(
    pages: List[MergedPageOutput],
    toc: TocOutput,
    page_mapping: PageMappingOutput,
    scan_id: str,
    output_dir: Path,
) -> BoundaryCandidatesOutput:
    """
    Substage 4c: Detect chapter boundary candidates.

    Scans for CHAPTER_HEADING labels and cross-validates
    against ToC entries to build initial boundary candidates.
    """
    # TODO: Implement boundary detection
    logger.warning("Boundary detection not yet implemented, using placeholder")

    candidates_output = BoundaryCandidatesOutput(
        scan_id=scan_id,
        candidates=[],
        total_candidates=0,
        toc_matched_count=0,
        label_only_count=0,
        toc_only_count=0,
        timestamp=datetime.now().isoformat(),
    )

    # Save checkpoint
    output_file = output_dir / "boundary_candidates.json"
    with open(output_file, "w") as f:
        f.write(candidates_output.model_dump_json(indent=2))
    logger.info(f"Saved boundary candidates to {output_file}")

    return candidates_output


def _validate_boundaries_with_llm(
    pages: List[MergedPageOutput],
    candidates: BoundaryCandidatesOutput,
    page_mapping: PageMappingOutput,
    scan_id: str,
    output_dir: Path,
) -> ValidatedBoundariesOutput:
    """
    Substage 4d: Validate boundaries with LLM.

    For EACH boundary, provide 3-page context and ask LLM
    to confirm/correct the boundary location and title.
    Liberal strategy: validate all, not just ambiguous ones.
    """
    # TODO: Implement LLM validation
    logger.warning("LLM validation not yet implemented, using placeholder")

    validated_output = ValidatedBoundariesOutput(
        scan_id=scan_id,
        boundaries=[],
        total_boundaries=0,
        llm_corrections_made=0,
        high_confidence_count=0,
        low_confidence_count=0,
        model_used="gpt-4o-mini",
        validation_cost=0.0,
        avg_validation_time_seconds=0.0,
        timestamp=datetime.now().isoformat(),
    )

    # Save checkpoint
    output_file = output_dir / "boundaries_validated.json"
    with open(output_file, "w") as f:
        f.write(validated_output.model_dump_json(indent=2))
    logger.info(f"Saved validated boundaries to {output_file}")

    return validated_output


def _assemble_chapters(
    validated: ValidatedBoundariesOutput,
    page_mapping: PageMappingOutput,
    total_pages: int,
    scan_id: str,
    output_dir: Path,
    total_cost: float,
    start_time: float,
) -> ChaptersOutput:
    """
    Substage 4e: Assemble final chapter structure.

    Converts validated boundaries into chapter ranges with
    start/end pages, calculates statistics, and writes final output.
    """
    # TODO: Implement chapter assembly
    logger.warning("Chapter assembly not yet implemented, using placeholder")

    processing_time = time.time() - start_time

    chapters_output = ChaptersOutput(
        scan_id=scan_id,
        total_pages=total_pages,
        chapters=[],
        total_chapters=0,
        front_matter_pages=[],
        back_matter_pages=[],
        detection_method="TOC_FIRST + HEADING_LABELS + LLM_VALIDATION",
        toc_available=False,
        llm_validation_used=False,
        avg_chapter_confidence=0.0,
        low_confidence_chapters=0,
        toc_mismatch_count=0,
        total_cost=total_cost,
        processing_time_seconds=processing_time,
        timestamp=datetime.now().isoformat(),
    )

    # Save final output
    output_file = output_dir / "chapters.json"
    with open(output_file, "w") as f:
        f.write(chapters_output.model_dump_json(indent=2))
    logger.info(f"Saved final chapters output to {output_file}")

    return chapters_output
