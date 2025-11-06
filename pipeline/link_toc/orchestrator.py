import time
from typing import Tuple, Dict, List

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger

from .schemas import LinkedTableOfContents, LinkedToCEntry, AgentResult
from .storage import LinkTocStageStorage
from .agent.finder import TocEntryFinderAgent


def find_all_toc_entries(
    storage: BookStorage,
    logger: PipelineLogger,
    model: str,
    max_iterations: int = 15,
    verbose: bool = False
) -> Tuple[LinkedTableOfContents, Dict]:
    """
    Spawn agents for all ToC entries and collect results.

    Process:
    1. Load ToC entries from extract-toc
    2. For each entry, spawn TocEntryFinderAgent
    3. Run agents sequentially with progress tracking
    4. Collect all AgentResults
    5. Build LinkedTableOfContents (enriched ToC) with statistics
    6. Return output + metrics (cost, time)

    Args:
        storage: BookStorage instance
        logger: PipelineLogger for logging
        model: Model to use for agent LLM calls
        max_iterations: Maximum iterations per agent (default 15)
        verbose: Show progress displays for agents

    Returns:
        - LinkedTableOfContents: Enriched ToC with scan page links
        - Metrics dict: {cost_usd, time_seconds, total_entries, found_count}
    """
    start_time = time.time()

    stage_storage = LinkTocStageStorage(stage_name="link-toc")

    # Load original ToC from extract-toc
    extract_toc_output = stage_storage.load_extract_toc_output(storage)

    # extract-toc output structure: {"toc": {"entries": [...], ...}, ...}
    toc_data = extract_toc_output.get('toc', {}) if extract_toc_output else {}

    if not toc_data or not toc_data.get('entries'):
        logger.warning("No ToC entries found in extract-toc output")
        return LinkedTableOfContents(
            entries=[],
            toc_page_range={},
            entries_by_level={},
            original_parsing_confidence=0.0,
            total_entries=0,
            linked_entries=0,
            unlinked_entries=0,
            avg_link_confidence=0.0,
            total_cost_usd=0.0,
            total_time_seconds=0.0,
            avg_iterations_per_entry=0.0
        ), {
            "cost_usd": 0.0,
            "time_seconds": 0.0,
            "total_entries": 0,
            "found_count": 0,
        }

    toc_entries = toc_data['entries']

    total_entries = len(toc_entries)

    # Check for existing progress (resume support)
    completed_indices = stage_storage.get_completed_entry_indices(storage)
    remaining_indices = [idx for idx in range(total_entries) if idx not in completed_indices]

    if completed_indices:
        logger.info(f"Resuming: {len(completed_indices)}/{total_entries} entries already complete")

    logger.info(f"Processing {len(remaining_indices)} remaining ToC entries")

    # Run agents sequentially (simpler for debugging, can parallelize later)
    for idx in remaining_indices:
        toc_entry = toc_entries[idx]
        logger.info(f"[{idx+1}/{total_entries}] Searching: {toc_entry['title']}")

        agent = TocEntryFinderAgent(
            toc_entry=toc_entry,
            toc_entry_index=idx,
            storage=storage,
            logger=logger,
            model=model,
            max_iterations=max_iterations,
            verbose=verbose
        )

        result = agent.search()

        # Build LinkedToCEntry immediately
        linked_entry = LinkedToCEntry(
            # Original ToC fields
            entry_number=toc_entry.get('entry_number'),
            title=toc_entry['title'],
            level=toc_entry.get('level', 1),
            level_name=toc_entry.get('level_name'),
            printed_page_number=toc_entry.get('printed_page_number'),
            # Link fields
            scan_page=result.scan_page,
            link_confidence=result.confidence,
            agent_reasoning=result.reasoning,
            agent_iterations=result.iterations_used,
            candidates_checked=result.candidates_checked,
        )

        # Save immediately for resume support
        stage_storage.update_linked_entry(storage, idx, linked_entry)

        if result.found:
            logger.info(
                f"  ✓ Found at scan page {result.scan_page} (confidence: {result.confidence:.2f})"
            )
        else:
            logger.info(f"  ✗ Not found: {result.reasoning}")

    # Load complete linked_toc.json (now includes all entries)
    linked_toc = stage_storage.load_linked_toc(storage)

    if not linked_toc or not linked_toc.entries:
        logger.warning("No linked ToC data found after processing")
        return LinkedTableOfContents(
            entries=[],
            toc_page_range={},
            entries_by_level={},
            original_parsing_confidence=0.0,
            total_entries=0,
            linked_entries=0,
            unlinked_entries=0,
            avg_link_confidence=0.0,
            total_cost_usd=0.0,
            total_time_seconds=0.0,
            avg_iterations_per_entry=0.0
        ), {
            "cost_usd": 0.0,
            "time_seconds": 0.0,
            "total_entries": 0,
            "found_count": 0,
        }

    linked_entries = [e for e in linked_toc.entries if e is not None]

    # Compute statistics
    linked_count = sum(1 for e in linked_entries if e.scan_page is not None)
    unlinked_count = len(linked_entries) - linked_count

    # Average confidence (only for linked entries)
    linked_only = [e for e in linked_entries if e.scan_page is not None]
    avg_confidence = (
        sum(e.link_confidence for e in linked_only) / len(linked_only)
        if linked_only else 0.0
    )

    # Average iterations
    avg_iterations = sum(e.agent_iterations for e in linked_entries) / len(linked_entries) if linked_entries else 0.0

    # Get total cost and time from metrics
    stage_storage_obj = storage.stage("link-toc")
    all_metrics = stage_storage_obj.metrics_manager.get_all()

    total_cost_usd = sum(m.get('cost_usd', 0.0) for m in all_metrics.values())
    total_time_seconds = time.time() - start_time

    # Finalize metadata in linked_toc.json
    stage_storage.finalize_linked_toc_metadata(
        storage=storage,
        toc_page_range=toc_data.get('toc_page_range', {}),
        entries_by_level=toc_data.get('entries_by_level', {}),
        original_parsing_confidence=toc_data.get('parsing_confidence', 0.0),
        total_entries=len(linked_entries),
        linked_entries=linked_count,
        unlinked_entries=unlinked_count,
        avg_link_confidence=avg_confidence,
        total_cost_usd=total_cost_usd,
        total_time_seconds=total_time_seconds,
        avg_iterations_per_entry=avg_iterations
    )

    # Build output object for return
    output = LinkedTableOfContents(
        entries=linked_entries,
        toc_page_range=toc_data.get('toc_page_range', {}),
        entries_by_level=toc_data.get('entries_by_level', {}),
        original_parsing_confidence=toc_data.get('parsing_confidence', 0.0),
        total_entries=len(linked_entries),
        linked_entries=linked_count,
        unlinked_entries=unlinked_count,
        avg_link_confidence=avg_confidence,
        total_cost_usd=total_cost_usd,
        total_time_seconds=total_time_seconds,
        avg_iterations_per_entry=avg_iterations
    )

    metrics = {
        "cost_usd": total_cost_usd,
        "time_seconds": total_time_seconds,
        "total_entries": len(linked_entries),
        "found_count": linked_count,
    }

    logger.info(
        f"All entries processed: {linked_count}/{len(linked_entries)} linked, "
        f"cost ${total_cost_usd:.4f}, time {total_time_seconds:.1f}s"
    )

    return output, metrics
