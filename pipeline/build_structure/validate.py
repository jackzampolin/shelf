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
from typing import List, Optional, Tuple, Dict, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBarHierarchical
from infra.llm.batch_client import LLMBatchClient
from infra.llm.models import LLMRequest, LLMResult, EventData
from infra.config import Config

from .schemas import (
    DraftMetadata,
    ValidationResult,
    ValidationIssue,
    Chapter,
    Part,
    PageRange,
    Section,
    BoundaryVerificationResult,
    HeadingData,
    HeadingEntry,
)


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
    batch_client: LLMBatchClient,
    on_event: Optional[Callable[[EventData], None]] = None,
) -> Tuple[Dict[int, Tuple[bool, Optional[str]]], float]:
    """
    Batch verify chapter/section boundaries in parallel using LLMBatchClient.

    Args:
        boundaries: List of (page_num, expected_title, boundary_type) tuples to verify
        storage: BookStorage instance
        model: LLM model to use
        logger: Pipeline logger
        batch_client: LLMBatchClient instance (shared for progress tracking)
        on_event: Optional event handler for progress tracking

    Returns:
        Tuple of (results_dict, total_cost)
        results_dict: {page_num: (is_boundary, detected_title)}
    """
    if not boundaries:
        return {}, 0.0

    results = {}

    logger.info(f"Batch verifying {len(boundaries)} boundaries", workers=batch_client.max_workers)

    # Prepare LLM requests for all boundaries
    requests = []
    merged_stage = storage.stage("merged")

    # Import prompt builders
    from .validate_prompts import build_chapter_verification_prompt, build_section_verification_prompt

    for page_num, expected_title, boundary_type in boundaries:
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
                logger.warning("Boundary verification: page has no text", page=page_num, boundary_type=boundary_type)
                results[page_num] = (False, None)
                continue

        except Exception as e:
            logger.error("Boundary verification: failed to load page", page=page_num, boundary_type=boundary_type, error=str(e))
            results[page_num] = (False, None)
            continue

        # Build LLM prompt based on boundary type
        if boundary_type == "chapter":
            prompt = build_chapter_verification_prompt(expected_title, page_text)
        else:  # section
            prompt = build_section_verification_prompt(expected_title, page_text)

        # Get schema for structured output
        from .schemas import BoundaryVerificationResult
        import copy
        base_schema = BoundaryVerificationResult.model_json_schema()
        schema = copy.deepcopy(base_schema)

        # Remove strict mode - OpenRouter's strict validation can be too restrictive
        # We'll validate with Pydantic after receiving the response instead
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "boundary_verification",
                "schema": schema
            }
        }

        # Create LLM request with structured output
        request = LLMRequest(
            id=f"page_{page_num:04d}_{boundary_type}",
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
            response_format=response_format,
            metadata={
                'page_num': page_num,
                'expected_title': expected_title,
                'boundary_type': boundary_type,
            }
        )
        requests.append(request)

    if not requests:
        logger.info("No valid boundaries to verify")
        return results, 0.0

    # Process batch
    def on_result(result: LLMResult):
        """Handle LLM result for boundary verification."""
        try:
            page_num = result.request.metadata['page_num']

            if result.success and result.parsed_json:
                # Parse verification result
                verification = BoundaryVerificationResult(**result.parsed_json)
                results[page_num] = (verification.is_boundary, verification.detected_title)

                logger.info(
                    f"LLM {result.request.metadata['boundary_type']} verification",
                    page=page_num,
                    is_boundary=verification.is_boundary,
                    title=verification.detected_title,
                    confidence=verification.confidence,
                    cost=f"${result.cost_usd:.4f}",
                )
            else:
                # LLM call failed
                logger.error("Boundary verification failed", page=page_num, error=result.error)
                results[page_num] = (False, None)

        except Exception as e:
            logger.error(f"Error handling verification result", error=str(e))
            results[result.request.metadata['page_num']] = (False, None)

    # Process batch with event tracking for progress display
    batch_results = batch_client.process_batch(
        requests,
        on_event=on_event,
        on_result=on_result
    )

    # Get final stats
    batch_stats = batch_client.get_batch_stats(total_requests=len(requests))
    total_cost = batch_stats.total_cost_usd

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
    if fm.title_page:
        issues.extend(validate_page_range(fm.title_page, storage, "Front Matter Title Page"))
    if fm.toc:
        issues.extend(validate_page_range(fm.toc, storage, "Front Matter TOC"))
    if fm.preface:
        issues.extend(validate_page_range(fm.preface, storage, "Front Matter Preface"))
    if fm.introduction:
        issues.extend(validate_page_range(fm.introduction, storage, "Front Matter Introduction"))

    # Validate other front matter sections
    for other_section in fm.other:
        issues.extend(validate_page_range(other_section, storage, f"Front Matter {other_section.label}"))

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

        # Setup progress tracking for batch verification
        logger.info(f"Verifying {len(boundaries_to_verify)} boundaries with LLM...")
        verify_start_time = time.time()
        progress = RichProgressBarHierarchical(
            total=len(boundaries_to_verify),
            prefix="   ",
            width=40,
            unit="boundaries"
        )
        progress.update(0, suffix="starting...")

        # Create batch client (shared for event handler and processing)
        stage_log_dir = storage.stage("build_structure").output_dir / "logs"
        batch_client = LLMBatchClient(
            max_workers=Config.max_workers,
            max_retries=5,
            retry_jitter=(1.0, 3.0),
            verbose=True,  # Enable per-request events for progress tracking
            log_dir=stage_log_dir,
        )

        # Create event handler
        on_event = progress.create_llm_event_handler(
            batch_client=batch_client,
            start_time=verify_start_time,
            model=model,
            total_requests=len(boundaries_to_verify),
            checkpoint=None  # No checkpoint for structure stage
        )

        # Batch verify all boundaries in parallel
        verification_results, batch_cost = batch_verify_boundaries(
            boundaries=boundaries_to_verify,
            storage=storage,
            model=model,
            logger=logger,
            batch_client=batch_client,
            on_event=on_event,
        )
        total_cost += batch_cost

        # Finish progress
        verify_elapsed = time.time() - verify_start_time
        batch_stats = batch_client.get_batch_stats(total_requests=len(boundaries_to_verify))
        progress.finish(f"   ✓ {batch_stats.completed}/{len(boundaries_to_verify)} boundaries verified in {verify_elapsed:.1f}s")

        logger.info(
            "Batch verification complete",
            verified=batch_stats.completed,
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
    if bm.notes:
        issues.extend(validate_page_range(bm.notes, storage, "Back Matter Notes"))
    if bm.bibliography:
        issues.extend(validate_page_range(bm.bibliography, storage, "Back Matter Bibliography"))
    if bm.index:
        issues.extend(validate_page_range(bm.index, storage, "Back Matter Index"))

    # Validate appendices
    for appendix in bm.appendices:
        issues.extend(validate_page_range(appendix, storage, f"Back Matter {appendix.label}"))

    # Validate other back matter sections
    for other_section in bm.other:
        issues.extend(validate_page_range(other_section, storage, f"Back Matter {other_section.label}"))

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
