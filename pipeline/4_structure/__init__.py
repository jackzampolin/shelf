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
from typing import Optional, List, Dict
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
Chapter = getattr(structure_schemas, 'Chapter')

toc_parser_module = importlib.import_module('pipeline.4_structure.toc_parser')
parse_toc = getattr(toc_parser_module, 'parse_toc')

page_mapper_module = importlib.import_module('pipeline.4_structure.page_mapper')
build_page_mapping_from_anchors = getattr(page_mapper_module, 'build_page_mapping_from_anchors')

validator_module = importlib.import_module('pipeline.4_structure.page_mapping_validator')
find_toc_anchors_with_llm = getattr(validator_module, 'validate_page_mapping_with_llm')  # Still named this for compatibility

boundary_detector_module = importlib.import_module('pipeline.4_structure.boundary_detector')
detect_and_validate_boundaries = getattr(boundary_detector_module, 'detect_and_validate_boundaries')

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

    # Substage 4b: Build page mapping (LLM finds anchors, deterministic interpolation)
    page_mapping, mapping_cost = _build_page_mapping_with_anchors(pages, toc_output, scan_id, chapters_dir)
    logger.info(f"Built page mapping: {len(page_mapping.mappings)} pages mapped")
    total_cost += mapping_cost

    # Substages 4c+4d: Detect and validate boundaries (combined - direct ToC validation)
    validated = _detect_and_validate_boundaries(pages, toc_output, page_mapping, scan_id, chapters_dir)
    logger.info(
        f"Detected and validated {validated.total_boundaries} boundaries "
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
    checkpoint_manager.mark_stage_complete(metadata={
        "total_chapters": chapters_output.total_chapters,
        "total_cost_usd": total_cost,
        "processing_time_seconds": chapters_output.processing_time_seconds
    })

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


def _build_page_mapping_with_anchors(
    pages: List[MergedPageOutput],
    toc: TocOutput,
    scan_id: str,
    output_dir: Path,
) -> tuple[PageMappingOutput, float]:
    """
    Substage 4b: Build PDF ↔ Book page mapping using ToC anchors.

    Process:
    1. LLM finds ToC anchors (matches ToC entries to PDF pages)
    2. Deterministic interpolation between anchors
    3. Detect front/body/back matter from ToC structure

    Returns:
        (PageMappingOutput, llm_cost)
    """
    logger.info("Substage 4b: Building page mapping with ToC anchors...")

    # Step 1: LLM finds ToC anchor points
    anchor_result, llm_cost = find_toc_anchors_with_llm(
        toc_entries=toc.entries,
        pages=pages,
        initial_mappings=[]  # Not used anymore
    )

    # Save anchor result for debugging
    anchor_file = output_dir / "page_mapping_anchors.json"
    with open(anchor_file, "w") as f:
        json.dump(anchor_result, f, indent=2)
    logger.info(f"Saved ToC anchors to {anchor_file}")

    # Step 2: Build complete mapping using anchors + interpolation
    page_mapping = build_page_mapping_from_anchors(
        pages=pages,
        toc_entries=toc.entries,
        toc_anchors=anchor_result['anchors'],
        scan_id=scan_id,
        output_dir=output_dir
    )

    logger.info(
        f"Page mapping complete: {page_mapping.toc_match_count} ToC anchors, "
        f"{page_mapping.unmapped_pages} unmapped pages"
    )

    return page_mapping, llm_cost


def _detect_and_validate_boundaries(
    pages: List[MergedPageOutput],
    toc: TocOutput,
    page_mapping: PageMappingOutput,
    scan_id: str,
    output_dir: Path,
) -> ValidatedBoundariesOutput:
    """
    Substages 4c+4d: Detect and validate boundaries (combined).

    Direct ToC validation approach:
    1. For each ToC entry, look up expected PDF page from page mapping
    2. Create ±1 page window (3 pages total)
    3. Ask LLM to validate boundary location
    4. Return validated boundaries

    Much simpler than collecting all CHAPTER_HEADING labels and filtering.
    """
    logger.info("Substages 4c+4d: Detecting and validating boundaries from ToC...")

    # Call combined detector/validator
    validated_output = detect_and_validate_boundaries(
        pages=pages,
        toc_entries=toc.entries,
        page_mappings=page_mapping.mappings,
        scan_id=scan_id,
        model="openai/gpt-4o-mini",
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

    Process:
    1. Sort boundaries by PDF page (ensure sequential order)
    2. For each boundary, calculate chapter range:
       - start_pdf = boundary.pdf_page
       - end_pdf = next_boundary.pdf_page - 1 (or total_pages for last chapter)
    3. Look up book pages from page_mapping
    4. Build Chapter objects with all metadata
    5. Calculate statistics and save
    """
    logger.info("Substage 4e: Assembling final chapter structure...")

    # Build page mapping lookup (PDF page → book page)
    page_map = {m.pdf_page: m for m in page_mapping.mappings}

    # Sort boundaries by PDF page (should already be sorted, but ensure)
    sorted_boundaries = sorted(validated.boundaries, key=lambda b: b.pdf_page)

    # Build chapters from boundaries
    chapters = []
    for i, boundary in enumerate(sorted_boundaries):
        # Start of this chapter
        start_pdf = boundary.pdf_page
        start_book = boundary.book_page

        # End of this chapter (start of next chapter - 1, or total_pages for last)
        if i < len(sorted_boundaries) - 1:
            end_pdf = sorted_boundaries[i + 1].pdf_page - 1
        else:
            end_pdf = total_pages

        # Look up end book page from mapping
        end_book = None
        if end_pdf in page_map:
            end_book = page_map[end_pdf].book_page

        # Calculate page count
        page_count = end_pdf - start_pdf + 1

        # Create Chapter
        chapter = Chapter(
            chapter_num=i + 1,
            title=boundary.title,
            start_pdf_page=start_pdf,
            end_pdf_page=end_pdf,
            start_book_page=start_book,
            end_book_page=end_book,
            page_count=page_count,
            detected_by=boundary.detected_by,
            confidence=boundary.final_confidence,
            toc_match=boundary.toc_match,
        )
        chapters.append(chapter)

        logger.info(
            f"Chapter {i+1}: \"{chapter.title}\" "
            f"(PDF {start_pdf}-{end_pdf}, {page_count} pages, "
            f"confidence: {chapter.confidence:.2f})"
        )

    # Calculate statistics
    total_chapters = len(chapters)
    avg_confidence = sum(c.confidence for c in chapters) / total_chapters if total_chapters > 0 else 0.0
    low_confidence_count = sum(1 for c in chapters if c.confidence < 0.7)
    toc_mismatch_count = validated.llm_corrections_made  # LLM corrections = ToC mismatches

    processing_time = time.time() - start_time

    # Build final output
    chapters_output = ChaptersOutput(
        scan_id=scan_id,
        total_pages=total_pages,
        chapters=chapters,
        total_chapters=total_chapters,
        front_matter_pages=page_mapping.front_matter_pages,
        back_matter_pages=page_mapping.back_matter_pages,
        detection_method="TOC_FIRST + PAGE_MAPPING + LLM_VALIDATION",
        toc_available=(total_chapters > 0),  # We have ToC if we found chapters
        llm_validation_used=True,  # We always validate with LLM
        avg_chapter_confidence=avg_confidence,
        low_confidence_chapters=low_confidence_count,
        toc_mismatch_count=toc_mismatch_count,
        total_cost=total_cost,
        processing_time_seconds=processing_time,
        timestamp=datetime.now().isoformat(),
    )

    # Save final output
    output_file = output_dir / "chapters.json"
    with open(output_file, "w") as f:
        f.write(chapters_output.model_dump_json(indent=2))
    logger.info(f"Saved final chapters output to {output_file}")

    logger.info(
        f"Chapter assembly complete: {total_chapters} chapters, "
        f"avg confidence: {avg_confidence:.2f}, "
        f"{low_confidence_count} low confidence"
    )

    return chapters_output


# Removed _apply_mapping_corrections - no longer needed with deterministic approach


def clean_stage(scan_id: str, storage_root: Path, confirm: bool = False) -> bool:
    """
    Clean/delete all structure outputs and checkpoint for a book.

    Args:
        scan_id: Book scan ID
        storage_root: Root storage directory
        confirm: If False, prompts for confirmation before deleting

    Returns:
        bool: True if cleaned, False if cancelled
    """
    book_dir = storage_root / scan_id

    if not book_dir.exists():
        print(f"❌ Book directory not found: {book_dir}")
        return False

    chapters_dir = book_dir / "chapters"
    checkpoint_file = book_dir / "checkpoints" / "structure.json"

    # Count what will be deleted
    chapter_files = list(chapters_dir.glob("*.json")) if chapters_dir.exists() else []

    print(f"\n🗑️  Clean Structure stage for: {scan_id}")
    print(f"   Chapter outputs: {len(chapter_files)} files")
    print(f"   Checkpoint: {'exists' if checkpoint_file.exists() else 'none'}")

    if not confirm:
        response = input("\n   Proceed? (yes/no): ").strip().lower()
        if response != 'yes':
            print("   Cancelled.")
            return False

    # Delete chapter outputs
    if chapters_dir.exists():
        import shutil
        shutil.rmtree(chapters_dir)
        print(f"   ✓ Deleted {len(chapter_files)} chapter files")

    # Reset checkpoint
    if checkpoint_file.exists():
        checkpoint_file.unlink()
        print(f"   ✓ Deleted checkpoint")

    print(f"\n✅ Structure stage cleaned for {scan_id}")
    return True
