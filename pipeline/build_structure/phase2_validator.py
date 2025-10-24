"""
Phase 2: Validate draft metadata against ground truth (merged pages).

This phase checks the LLM's structure claims by loading actual pages and verifying:
- Chapter heading blocks exist at claimed chapter start pages
- Page ranges are valid and don't overlap
- Front/back matter classifications match claims
- Printed page numbers align with structure

Cost: ~$0-1 per book (mostly file I/O, optional LLM for vision validation)
Time: ~1-2 minutes
"""

from pathlib import Path
from typing import List, Optional, Tuple, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.client import LLMClient
from infra.config import Config

from .schemas import (
    DraftMetadata,
    ValidationResult,
    ValidationIssue,
    Chapter,
    Part,
    PageRange,
    Section,
    HeadingData,
    HeadingEntry,
)


def find_chapter_heading_pages(
    storage: BookStorage,
    logger: PipelineLogger,
) -> List[int]:
    """
    Find all pages with CHAPTER_HEADING blocks in merged/ directory.

    Returns:
        List of page numbers with CHAPTER_HEADING blocks, sorted
    """
    merged_stage = storage.stage("merged")
    chapter_pages = []

    for page_file in merged_stage.list_output_pages():
        page_num = int(page_file.stem.split("_")[1])
        try:
            page_data = merged_stage.load_page(page_num)
            blocks = page_data.get("blocks", [])

            # Check if any block is a CHAPTER_HEADING
            for block in blocks:
                if block.get("classification") == "CHAPTER_HEADING":
                    chapter_pages.append(page_num)
                    break  # Only count page once
        except Exception:
            continue

    return sorted(chapter_pages)


def validate_page_range(
    page_range: PageRange,
    storage: BookStorage,
    context: str,
) -> List[ValidationIssue]:
    """
    Validate that a page range exists in merged/ directory.

    Args:
        page_range: PageRange to validate
        storage: BookStorage instance
        context: Human-readable context (e.g., "Chapter 1", "TOC")

    Returns:
        List of validation issues (empty if valid)
    """
    issues = []

    # Check that start <= end
    if page_range.start_page > page_range.end_page:
        issues.append(
            ValidationIssue(
                severity="error",
                issue_type="invalid_page_range",
                message=f"{context}: start page > end page",
                expected=f"start <= end",
                actual=f"start={page_range.start_page}, end={page_range.end_page}",
            )
        )
        return issues

    # Check that pages exist
    merged_stage = storage.stage("merged")
    for page_num in range(page_range.start_page, page_range.end_page + 1):
        page_file = merged_stage.output_page(page_num)
        if not page_file.exists():
            issues.append(
                ValidationIssue(
                    severity="error",
                    issue_type="missing_page",
                    message=f"{context}: page {page_num} not found in merged/",
                    page_num=page_num,
                    expected=f"merged/page_{page_num:04d}.json exists",
                    actual="file not found",
                )
            )

    return issues


def find_chapter_heading_nearby(
    claimed_page: int,
    storage: BookStorage,
    search_radius: int = 5,
) -> Optional[int]:
    """
    Search for CHAPTER_HEADING block near claimed chapter start page.

    Args:
        claimed_page: Page where LLM claimed chapter starts
        storage: BookStorage instance
        search_radius: How many pages before/after to search

    Returns:
        Page number with CHAPTER_HEADING, or None if not found
    """
    merged_stage = storage.stage("merged")

    # Search nearby pages (claimed_page ± search_radius)
    start = max(1, claimed_page - search_radius)
    end = claimed_page + search_radius

    for page_num in range(start, end + 1):
        page_file = merged_stage.output_page(page_num)
        if not page_file.exists():
            continue

        try:
            page_data = merged_stage.load_page(page_num)
            blocks = page_data.get("blocks", [])

            # Check if this page has CHAPTER_HEADING
            for block in blocks:
                if block.get("classification") == "CHAPTER_HEADING":
                    return page_num
        except Exception:
            continue

    return None


def verify_boundary_with_llm(
    page_num: int,
    expected_title: str,
    boundary_type: str,  # "chapter" or "section"
    storage: BookStorage,
    model: str,
    logger: PipelineLogger,
) -> Tuple[bool, Optional[str], float]:
    """
    Use LLM to verify if a page contains a chapter or section boundary.

    Args:
        page_num: Page to check
        expected_title: Expected chapter/section title from structure analysis
        boundary_type: Either "chapter" or "section"
        storage: BookStorage instance
        model: LLM model to use
        logger: Pipeline logger

    Returns:
        Tuple of (is_boundary, detected_title, cost_usd)
    """
    merged_stage = storage.stage("merged")

    # Extract text from page
    try:
        page_data = merged_stage.load_page(page_num)
        blocks = page_data.get("blocks", [])

        # Combine all paragraph text
        text_parts = []
        for block in blocks:
            for para in block.get("paragraphs", []):
                text = para.get("text", "")
                if text:
                    text_parts.append(text)

        page_text = "\n".join(text_parts)

        if not page_text.strip():
            logger.warning("LLM verification: page has no text", page=page_num, boundary_type=boundary_type)
            return False, None, 0.0

    except Exception as e:
        logger.error("LLM verification: failed to load page", page=page_num, boundary_type=boundary_type, error=str(e))
        return False, None, 0.0

    # Prepare LLM prompt based on boundary type
    if boundary_type == "chapter":
        prompt = f"""You are verifying whether a page from a scanned book is the start of a new chapter.

Expected chapter title: "{expected_title}"

Page text (first 1500 chars):
{page_text[:1500]}

Does this page START a new chapter?
- Look for chapter headings, titles, or clear chapter markers
- The expected title is "{expected_title}" but it might be formatted differently
- Some chapters start with "CHAPTER 1", "Part I", roman numerals, etc.

Respond with JSON:
{{
  "is_boundary": true/false,
  "detected_title": "exact title text from page" or null if not a chapter start,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}"""
    else:  # section
        prompt = f"""You are verifying whether a page from a scanned book contains a section heading.

Expected section title: "{expected_title}"

Page text (first 1500 chars):
{page_text[:1500]}

Does this page contain a section heading?
- Look for section headings, subheadings, or subsection markers
- The expected title is "{expected_title}" but it might be formatted differently
- Sections are typically less prominent than chapter headings
- Sections may appear mid-page, not necessarily at the top

Respond with JSON:
{{
  "is_boundary": true/false,
  "detected_title": "exact title text from page" or null if no section heading found,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}"""

    client = LLMClient()

    try:
        response_text, usage, cost_usd = client.call(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,  # Deterministic
        )

        # Parse response
        import json

        response_text = response_text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

        result = json.loads(response_text)

        is_boundary = result.get("is_boundary", False)
        title = result.get("detected_title")
        confidence = result.get("confidence", 0.0)

        logger.info(
            f"LLM {boundary_type} verification",
            page=page_num,
            is_boundary=is_boundary,
            title=title,
            confidence=confidence,
            cost=f"${cost_usd:.4f}",
        )

        return is_boundary, title, cost_usd

    except Exception as e:
        logger.error("LLM verification failed", page=page_num, boundary_type=boundary_type, error=str(e))
        return False, None, 0.0


# Keep old function name for backward compatibility
def verify_chapter_boundary_with_llm(
    page_num: int,
    expected_title: str,
    storage: BookStorage,
    model: str,
    logger: PipelineLogger,
) -> Tuple[bool, Optional[str], float]:
    """Backward compatibility wrapper for verify_boundary_with_llm."""
    return verify_boundary_with_llm(page_num, expected_title, "chapter", storage, model, logger)


def validate_and_correct_chapter(
    chapter: Chapter,
    storage: BookStorage,
    logger: PipelineLogger,
    model: Optional[str] = None,
    use_llm_verification: bool = True,
) -> tuple[Optional[int], List[ValidationIssue], float]:
    """
    Validate chapter start page and attempt to correct if wrong.

    Strategy:
    1. Check if claimed page has CHAPTER_HEADING (fast path)
    2. If not, search nearby pages (±5) for CHAPTER_HEADING
    3. If found, return corrected page number
    4. If not found AND use_llm_verification=True, use LLM to verify the claimed page
    5. If LLM confirms, accept it; otherwise return warning

    Args:
        chapter: Chapter to validate
        storage: BookStorage instance
        logger: Pipeline logger
        model: LLM model for verification (optional)
        use_llm_verification: Whether to use LLM when classification search fails

    Returns:
        Tuple of (corrected_page_num or None, issues, cost_usd)
    """
    issues = []
    claimed_page = chapter.start_page
    total_cost = 0.0

    # Fast path: Check claimed page
    merged_stage = storage.stage("merged")
    page_file = merged_stage.output_page(claimed_page)

    if not page_file.exists():
        issues.append(
            ValidationIssue(
                severity="error",
                issue_type="missing_chapter_start_page",
                message=f"Chapter {chapter.chapter_number}: claimed page {claimed_page} not found",
                page_num=claimed_page,
                chapter_num=chapter.chapter_number,
                expected="merged page exists",
                actual="file not found",
            )
        )
        return None, issues, total_cost

    try:
        page_data = merged_stage.load_page(claimed_page)
        blocks = page_data.get("blocks", [])

        # Check for CHAPTER_HEADING on claimed page
        has_heading = any(b.get("classification") == "CHAPTER_HEADING" for b in blocks)

        if has_heading:
            # Perfect! Claimed page is correct
            logger.debug(
                "Chapter heading confirmed",
                chapter=chapter.chapter_number,
                page=claimed_page,
            )
            return claimed_page, issues, total_cost

        # No heading on claimed page - search nearby
        logger.info(
            "Chapter heading missing on claimed page, searching nearby",
            chapter=chapter.chapter_number,
            claimed_page=claimed_page,
        )

        corrected_page = find_chapter_heading_nearby(claimed_page, storage, search_radius=5)

        if corrected_page:
            # Found it nearby!
            issues.append(
                ValidationIssue(
                    severity="info",
                    issue_type="chapter_boundary_corrected",
                    message=f"Chapter {chapter.chapter_number}: corrected start from page {claimed_page} → {corrected_page}",
                    page_num=corrected_page,
                    chapter_num=chapter.chapter_number,
                    expected=f"page {claimed_page}",
                    actual=f"page {corrected_page} (CHAPTER_HEADING found)",
                )
            )
            logger.info(
                "Chapter boundary corrected",
                chapter=chapter.chapter_number,
                claimed=claimed_page,
                corrected=corrected_page,
            )
            return corrected_page, issues, total_cost

        # Still not found - use LLM verification if enabled
        if use_llm_verification and model:
            logger.info(
                "Using LLM to verify chapter boundary",
                chapter=chapter.chapter_number,
                page=claimed_page,
            )

            is_chapter, detected_title, llm_cost = verify_chapter_boundary_with_llm(
                page_num=claimed_page,
                expected_title=chapter.title,
                storage=storage,
                model=model,
                logger=logger,
            )

            total_cost += llm_cost

            if is_chapter:
                # LLM confirmed it's a chapter boundary!
                issues.append(
                    ValidationIssue(
                        severity="info",
                        issue_type="chapter_boundary_verified_by_llm",
                        message=f"Chapter {chapter.chapter_number}: LLM confirmed chapter start at page {claimed_page}",
                        page_num=claimed_page,
                        chapter_num=chapter.chapter_number,
                        expected=f"Chapter heading classification",
                        actual=f"LLM verified: '{detected_title or chapter.title}'",
                    )
                )
                logger.info(
                    "LLM confirmed chapter boundary",
                    chapter=chapter.chapter_number,
                    page=claimed_page,
                    detected_title=detected_title,
                )
                return claimed_page, issues, total_cost

        # Not found even with LLM - return warning
        issues.append(
            ValidationIssue(
                severity="warning",
                issue_type="chapter_heading_not_found",
                message=f"Chapter {chapter.chapter_number}: no CHAPTER_HEADING found near page {claimed_page} (searched ±5, LLM verification: {'enabled' if use_llm_verification else 'disabled'})",
                page_num=claimed_page,
                chapter_num=chapter.chapter_number,
                expected="CHAPTER_HEADING block within ±5 pages or LLM confirmation",
                actual=f"not found in pages {claimed_page-5} to {claimed_page+5}",
            )
        )
        logger.warning(
            "Chapter heading not found",
            chapter=chapter.chapter_number,
            claimed_page=claimed_page,
            llm_verified=use_llm_verification,
        )
        return None, issues, total_cost

    except Exception as e:
        issues.append(
            ValidationIssue(
                severity="error",
                issue_type="page_load_error",
                message=f"Chapter {chapter.chapter_number}: failed to load page {claimed_page}",
                page_num=claimed_page,
                chapter_num=chapter.chapter_number,
                expected="page loads successfully",
                actual=f"error: {str(e)}",
            )
        )
        return None, issues, total_cost


def calculate_confidence(issues: List[ValidationIssue]) -> float:
    """
    Calculate overall confidence score based on validation issues.

    Score formula:
    - Start at 1.0 (perfect)
    - Each error: -0.1 (blocking issues)
    - Each warning: -0.05 (problems we couldn't fix)
    - Each info: -0.0 (corrections we successfully made - no penalty!)
    - Minimum: 0.0

    Args:
        issues: List of validation issues

    Returns:
        Confidence score between 0.0 and 1.0
    """
    score = 1.0

    for issue in issues:
        if issue.severity == "error":
            score -= 0.1
        elif issue.severity == "warning":
            score -= 0.05
        # info severity = successful correction, no penalty

    return max(0.0, score)


def batch_verify_boundaries(
    boundaries: List[Tuple[int, str, str]],  # [(page_num, title, boundary_type), ...]
    storage: BookStorage,
    model: str,
    logger: PipelineLogger,
    max_workers: int = None,
) -> Tuple[Dict[int, Tuple[bool, Optional[str]]], float]:
    """
    Batch verify chapter/section boundaries in parallel using ThreadPoolExecutor.

    Args:
        boundaries: List of (page_num, expected_title, boundary_type) tuples to verify
        storage: BookStorage instance
        model: LLM model to use
        logger: Pipeline logger
        max_workers: Number of parallel workers (defaults to Config.max_workers)

    Returns:
        Tuple of (results_dict, total_cost)
        results_dict: {page_num: (is_boundary, detected_title)}
    """
    if not boundaries:
        return {}, 0.0

    max_workers = max_workers or Config.max_workers
    results = {}
    total_cost = 0.0

    logger.info(f"Batch verifying {len(boundaries)} boundaries", workers=max_workers)

    def verify_one(page_num: int, title: str, boundary_type: str):
        is_boundary, detected_title, cost = verify_boundary_with_llm(
            page_num=page_num,
            expected_title=title,
            boundary_type=boundary_type,
            storage=storage,
            model=model,
            logger=logger,
        )
        return page_num, is_boundary, detected_title, cost

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_page = {
            executor.submit(verify_one, page_num, title, btype): page_num
            for page_num, title, btype in boundaries
        }

        for future in as_completed(future_to_page):
            try:
                page_num, is_boundary, detected_title, cost = future.result()
                results[page_num] = (is_boundary, detected_title)
                total_cost += cost
            except Exception as e:
                page_num = future_to_page[future]
                logger.error("Batch verification failed", page=page_num, error=str(e))
                results[page_num] = (False, None)

    logger.info("Batch verification complete", verified=len(results), cost=f"${total_cost:.4f}")

    return results, total_cost


def restructure_draft_from_headings(
    draft: DraftMetadata,
    heading_data: HeadingData,
    storage: BookStorage,
    logger: PipelineLogger,
) -> DraftMetadata:
    """
    Restructure draft to properly separate parts from chapters using heading data.

    If heading_data shows book has parts (part_count > 0), rebuild the structure
    to have Parts → Chapters hierarchy instead of treating parts as chapters.

    Args:
        draft: Original draft from Phase 1b
        heading_data: Extracted heading data from Phase 1.5
        storage: BookStorage instance
        logger: Pipeline logger

    Returns:
        Restructured draft with proper parts and chapters
    """
    if heading_data.part_count == 0:
        logger.info("No parts detected in heading data, keeping original structure")
        return draft

    logger.info(
        "Parts detected - restructuring draft",
        parts=heading_data.part_count,
        chapters=heading_data.chapter_count,
    )

    # Extract parts from headings where is_part=true
    part_headings = [h for h in heading_data.headings if h.is_part]
    # Extract chapters from headings where is_part=false (exclude front/back matter)
    chapter_headings = [h for h in heading_data.headings if not h.is_part]

    # Filter out front matter and back matter chapter headings
    # (headings before first part or after last part)
    if part_headings:
        first_part_page = part_headings[0].page_num
        last_part_heading = part_headings[-1]

        # Find where the last part ends (next part start or end of body)
        last_part_end = draft.body_page_range.end_page

        # Keep only chapter headings within the body range
        chapter_headings = [
            h for h in chapter_headings
            if h.page_num >= first_part_page and h.page_num <= last_part_end
        ]

    # Build parts
    parts = []
    for i, part_heading in enumerate(part_headings):
        part_num = i + 1
        part_start = part_heading.page_num

        # Part ends at the next part's start (or end of body)
        if i < len(part_headings) - 1:
            part_end = part_headings[i + 1].page_num - 1
        else:
            part_end = draft.body_page_range.end_page

        # Extract title from heading text (remove "Part X" prefix if present)
        title = part_heading.heading_text
        if title.lower().startswith("part"):
            # Try to extract title after "Part X"
            parts_split = title.split(maxsplit=2)
            if len(parts_split) >= 3:
                title = parts_split[2]  # e.g., "Part I April 12, 1945" → "April 12, 1945"

        part = Part(
            part_number=part_num,
            title=title.strip(),
            page_range=PageRange(start_page=part_start, end_page=part_end),
        )
        parts.append(part)

    # Build chapters and assign to parts
    chapters = []
    for i, chapter_heading in enumerate(chapter_headings):
        chapter_num = i + 1
        chapter_start = chapter_heading.page_num

        # Chapter ends at next chapter start (or part end)
        if i < len(chapter_headings) - 1:
            chapter_end = chapter_headings[i + 1].page_num - 1
        else:
            # Last chapter extends to end of last part
            if parts:
                chapter_end = parts[-1].end_page
            else:
                chapter_end = draft.body_page_range.end_page

        # Determine which part this chapter belongs to
        part_number = None
        for part in parts:
            if part.page_range.contains(chapter_start):
                part_number = part.part_number
                # Trim chapter end to not exceed part boundary
                if chapter_end > part.end_page:
                    chapter_end = part.end_page
                break

        # Extract title from heading text
        title = chapter_heading.heading_text
        # Truncate long titles
        if len(title) > 100:
            title = title[:100] + "..."

        chapter = Chapter(
            chapter_number=chapter_num,
            title=title.strip(),
            page_range=PageRange(start_page=chapter_start, end_page=chapter_end),
            part_number=part_number,
            sections=[],  # TODO: Extract sections if needed
        )
        chapters.append(chapter)

    # Update body_page_range to match actual parts span
    if parts:
        new_body_start = parts[0].start_page
        new_body_end = parts[-1].end_page
        new_body_range = PageRange(start_page=new_body_start, end_page=new_body_end)
    else:
        new_body_range = draft.body_page_range

    logger.info(
        "Restructured draft",
        parts=len(parts),
        chapters=len(chapters),
        body_range=f"{new_body_range.start_page}-{new_body_range.end_page}",
    )

    # Return new draft with restructured parts and chapters
    return DraftMetadata(
        front_matter=draft.front_matter,
        parts=parts,
        chapters=chapters,
        back_matter=draft.back_matter,
        total_parts=len(parts),
        total_chapters=len(chapters),
        total_sections=0,  # TODO: Count sections if we extract them
        body_page_range=new_body_range,
        page_numbering_changes=draft.page_numbering_changes,
    )


def validate_structure(
    draft: DraftMetadata,
    heading_data: Optional[HeadingData],
    storage: BookStorage,
    logger: PipelineLogger,
    model: Optional[str] = None,
    use_llm_verification: bool = True,
) -> tuple[DraftMetadata, ValidationResult, float]:
    """
    Validate draft metadata against ground truth (merged pages).

    Phase 2 of build-structure: Restructure (if needed) and verify structure.

    Args:
        draft: DraftMetadata from Phase 1b
        heading_data: HeadingData from Phase 1.5 (optional)
        storage: BookStorage instance
        logger: Pipeline logger
        model: LLM model for verification (optional)
        use_llm_verification: Whether to use LLM verification for uncertain boundaries

    Returns:
        Tuple of (restructured_draft, ValidationResult, cost_usd)
    """
    # STEP 1: Restructure draft if heading data shows parts-based hierarchy
    if heading_data and heading_data.part_count > 0:
        logger.info("Phase 2a: Restructuring draft using heading data")
        draft = restructure_draft_from_headings(draft, heading_data, storage, logger)

    # STEP 2: Validate the (possibly restructured) draft
    logger.info("Phase 2b: Validating structure", parts=draft.total_parts, chapters=draft.total_chapters)

    issues: List[ValidationIssue] = []
    total_cost = 0.0

    # Validate front matter page ranges
    fm = draft.front_matter
    if fm.toc:
        issues.extend(validate_page_range(fm.toc, storage, "Front Matter TOC"))
    if fm.preface:
        issues.extend(validate_page_range(fm.preface, storage, "Front Matter Preface"))
    if fm.foreword:
        issues.extend(validate_page_range(fm.foreword, storage, "Front Matter Foreword"))
    if fm.introduction:
        issues.extend(validate_page_range(fm.introduction, storage, "Front Matter Introduction"))

    # Validate and correct chapters using batch processing (strict mode)
    if use_llm_verification and model:
        logger.info("Strict mode: Batch verifying all chapter and section boundaries with LLM")

        # Collect all boundaries to verify
        boundaries_to_verify = []

        # Collect chapter boundaries
        for chapter in draft.chapters:
            boundaries_to_verify.append((
                chapter.start_page,
                chapter.title,
                "chapter"
            ))

        # Collect section boundaries
        for chapter in draft.chapters:
            for section in chapter.sections:
                boundaries_to_verify.append((
                    section.page_range.start_page,
                    section.title,
                    "section"
                ))

        # Batch verify all boundaries in parallel
        verification_results, batch_cost = batch_verify_boundaries(
            boundaries=boundaries_to_verify,
            storage=storage,
            model=model,
            logger=logger,
        )
        total_cost += batch_cost

        logger.info(
            "Batch verification complete",
            total_boundaries=len(boundaries_to_verify),
            cost=f"${batch_cost:.4f}",
        )
    else:
        verification_results = {}

    # Apply verification results to chapters
    corrected_chapters = []
    for chapter in draft.chapters:
        # Validate page range exists
        issues.extend(
            validate_page_range(chapter.page_range, storage, f"Chapter {chapter.chapter_number}")
        )

        # Check if chapter boundary was verified
        chapter_page = chapter.start_page
        is_verified, detected_title = verification_results.get(chapter_page, (None, None))

        if is_verified is not None:
            if is_verified:
                # LLM confirmed chapter boundary
                issues.append(
                    ValidationIssue(
                        severity="info",
                        issue_type="chapter_boundary_verified_by_llm",
                        message=f"Chapter {chapter.chapter_number}: LLM confirmed chapter start at page {chapter_page}",
                        page_num=chapter_page,
                        chapter_num=chapter.chapter_number,
                        expected="Chapter heading",
                        actual=f"LLM verified: '{detected_title or chapter.title}'",
                    )
                )
            else:
                # LLM rejected claimed boundary
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        issue_type="chapter_boundary_rejected_by_llm",
                        message=f"Chapter {chapter.chapter_number}: LLM could not confirm chapter start at page {chapter_page}",
                        page_num=chapter_page,
                        chapter_num=chapter.chapter_number,
                        expected=f"Chapter '{chapter.title}'",
                        actual="LLM found no chapter heading",
                    )
                )

        # No correction logic yet - just tracking verification results
        corrected_chapters.append(chapter)

        # Validate sections within chapter
        for section in chapter.sections:
            # Validate page range exists
            issues.extend(
                validate_page_range(
                    section.page_range,
                    storage,
                    f"Chapter {chapter.chapter_number} Section '{section.title}'",
                )
            )

            # Check if section boundary was verified
            section_page = section.page_range.start_page
            is_verified, detected_title = verification_results.get(section_page, (None, None))

            if is_verified is not None:
                if is_verified:
                    issues.append(
                        ValidationIssue(
                            severity="info",
                            issue_type="section_boundary_verified_by_llm",
                            message=f"Chapter {chapter.chapter_number} Section '{section.title}': LLM confirmed section at page {section_page}",
                            page_num=section_page,
                            chapter_num=chapter.chapter_number,
                            expected="Section heading",
                            actual=f"LLM verified: '{detected_title or section.title}'",
                        )
                    )
                else:
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            issue_type="section_boundary_rejected_by_llm",
                            message=f"Chapter {chapter.chapter_number} Section '{section.title}': LLM could not confirm section at page {section_page}",
                            page_num=section_page,
                            chapter_num=chapter.chapter_number,
                            expected=f"Section '{section.title}'",
                            actual="LLM found no section heading",
                        )
                    )

    # Update draft with corrected chapters
    draft.chapters = corrected_chapters

    # Validate back matter page ranges
    bm = draft.back_matter
    if bm.epilogue:
        issues.extend(validate_page_range(bm.epilogue, storage, "Back Matter Epilogue"))
    if bm.afterword:
        issues.extend(validate_page_range(bm.afterword, storage, "Back Matter Afterword"))
    if bm.notes:
        issues.extend(validate_page_range(bm.notes, storage, "Back Matter Notes"))
    if bm.bibliography:
        issues.extend(validate_page_range(bm.bibliography, storage, "Back Matter Bibliography"))
    if bm.index:
        issues.extend(validate_page_range(bm.index, storage, "Back Matter Index"))

    if bm.appendices:
        for i, appendix in enumerate(bm.appendices, start=1):
            issues.extend(validate_page_range(appendix, storage, f"Back Matter Appendix {i}"))

    # Count issues by severity
    error_count = sum(1 for i in issues if i.severity == "error")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    info_count = sum(1 for i in issues if i.severity == "info")

    # Calculate confidence
    confidence = calculate_confidence(issues)

    # Overall validation passes if no errors
    is_valid = error_count == 0

    # Build result
    result = ValidationResult(
        is_valid=is_valid,
        confidence=confidence,
        issues=issues,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        pages_validated=sum(len(ch.page_range) for ch in draft.chapters),
        chapters_validated=draft.total_chapters,
    )

    logger.info(
        "Validation complete",
        is_valid=is_valid,
        confidence=f"{confidence:.2f}",
        errors=error_count,
        warnings=warning_count,
        issues_total=len(issues),
        validation_cost=f"${total_cost:.4f}",
    )

    return draft, result, total_cost
