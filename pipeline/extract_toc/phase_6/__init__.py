"""
Phase 6: ToC Validation

Aggregate page-level assemblies into final TableOfContents.
Perform validation checks for consistency and completeness.
"""

import time
from typing import List, Dict, Tuple
from pathlib import Path

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from ..schemas import PageRange, TableOfContents, ToCEntry, TocPageAssembly
from ..storage import ExtractTocStageStorage


def validate_toc(
    storage: BookStorage,
    toc_range: PageRange,
    logger: PipelineLogger
) -> Tuple[Dict[str, any], Dict[str, any]]:
    """
    Validate and finalize ToC structure.

    Aggregates page-level assemblies, performs validation checks,
    and produces final TableOfContents.

    Args:
        storage: Book storage
        toc_range: Range of ToC pages
        logger: Pipeline logger

    Returns:
        Tuple of (results_data, metrics)
        - results_data: {"toc": TableOfContents.model_dump()}
        - metrics: {"cost_usd": 0.0, "time_seconds": float, ...}
    """
    stage_storage = ExtractTocStageStorage(stage_name='extract-toc')

    # Load Phase 5 assembly results
    toc_assembled = stage_storage.load_toc_assembled(storage)
    pages_data = toc_assembled["pages"]

    start_time = time.time()

    logger.info(f"Validating ToC from {len(pages_data)} pages")

    # Aggregate all entries
    all_entries = []
    total_assembly_confidence = 0.0
    validation_notes = []

    for page_data in pages_data:
        page_assembly = TocPageAssembly(**page_data)
        all_entries.extend(page_assembly.entries)
        total_assembly_confidence += page_assembly.assembly_confidence

        if page_assembly.notes:
            validation_notes.append(f"Page {page_assembly.page_num}: {page_assembly.notes}")

    # Calculate average confidence
    avg_confidence = total_assembly_confidence / len(pages_data) if pages_data else 0.0

    # Perform validation checks
    validation_issues = _validate_hierarchy(all_entries)
    validation_notes.extend(validation_issues)

    chapter_sequence_issues = _validate_chapter_sequence(all_entries)
    validation_notes.extend(chapter_sequence_issues)

    # Calculate statistics
    total_chapters = sum(1 for e in all_entries if e.level == 1)
    total_sections = sum(1 for e in all_entries if e.level > 1)

    # Adjust confidence based on validation issues
    parsing_confidence = avg_confidence
    if len(validation_issues) > 0:
        # Reduce confidence by 0.1 per major issue (capped)
        reduction = min(0.3, len(validation_issues) * 0.1)
        parsing_confidence = max(0.0, avg_confidence - reduction)

    # Create final TableOfContents
    toc = TableOfContents(
        entries=all_entries,
        toc_page_range=toc_range,
        total_chapters=total_chapters,
        total_sections=total_sections,
        parsing_confidence=parsing_confidence,
        notes=validation_notes
    )

    elapsed_time = time.time() - start_time

    results_data = {
        "toc": toc.model_dump(),
    }

    metrics = {
        "cost_usd": 0.0,  # No LLM calls in validation
        "time_seconds": elapsed_time,
        "total_entries": len(all_entries),
        "total_chapters": total_chapters,
        "total_sections": total_sections,
        "validation_issues": len(validation_issues),
    }

    logger.info(
        f"Validation complete: {len(all_entries)} entries "
        f"({total_chapters} chapters, {total_sections} sections), "
        f"confidence: {parsing_confidence:.2f}, "
        f"{len(validation_issues)} issues"
    )

    return results_data, metrics


def _validate_hierarchy(entries: List[ToCEntry]) -> List[str]:
    """
    Validate hierarchy consistency.

    Checks:
    - No level 2 before level 1
    - No level 3 before level 2
    - No level 3 without level 2 parent
    """
    issues = []
    seen_levels = set()

    for idx, entry in enumerate(entries):
        if entry.level == 2 and 1 not in seen_levels:
            issues.append(f"Entry {idx} ('{entry.title[:30]}') is level 2 but no level 1 seen yet")

        if entry.level == 3 and 2 not in seen_levels:
            issues.append(f"Entry {idx} ('{entry.title[:30]}') is level 3 but no level 2 seen yet")

        seen_levels.add(entry.level)

    return issues


def _validate_chapter_sequence(entries: List[ToCEntry]) -> List[str]:
    """
    Validate chapter numbering sequence.

    Checks for:
    - Missing chapter numbers in sequence (e.g., 1, 2, 4 - missing 3)
    - Duplicate chapter numbers
    """
    issues = []

    # Extract numbered chapters (level 1 with chapter_number)
    numbered_chapters = [
        (idx, e.chapter_number)
        for idx, e in enumerate(entries)
        if e.level == 1 and e.chapter_number is not None
    ]

    if not numbered_chapters:
        return issues

    # Check for duplicates
    chapter_nums = [num for _, num in numbered_chapters]
    duplicates = set([num for num in chapter_nums if chapter_nums.count(num) > 1])
    if duplicates:
        issues.append(f"Duplicate chapter numbers found: {sorted(duplicates)}")

    # Check for gaps in sequence
    unique_nums = sorted(set(chapter_nums))
    expected_sequence = list(range(unique_nums[0], unique_nums[-1] + 1))
    missing = set(expected_sequence) - set(unique_nums)
    if missing:
        issues.append(f"Missing chapter numbers in sequence: {sorted(missing)}")

    return issues
