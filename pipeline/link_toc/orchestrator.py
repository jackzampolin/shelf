import time
from typing import Tuple, Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.agent import MultiAgentProgressDisplay

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
    start_time = time.time()

    stage_storage = LinkTocStageStorage(stage_name="link-toc")

    extract_toc_output = stage_storage.load_extract_toc_output(storage)

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

    completed_indices = stage_storage.get_completed_entry_indices(storage)
    remaining_indices = [idx for idx in range(total_entries) if idx not in completed_indices]

    if completed_indices:
        logger.info(f"Resuming: {len(completed_indices)}/{total_entries} entries already complete")

    logger.info(f"Processing {len(remaining_indices)} remaining ToC entries")

    progress = MultiAgentProgressDisplay(
        total_agents=total_entries,
        max_visible_agents=10,
        completed_agent_display_seconds=5.0
    )

    for idx in range(total_entries):
        agent_id = f"entry_{idx:03d}"
        progress.register_agent(
            agent_id=agent_id,
            entry_index=idx,
            entry_title=toc_entries[idx]['title'],
            max_iterations=max_iterations
        )

    for idx in completed_indices:
        agent_id = f"entry_{idx:03d}"
        linked_toc_partial = stage_storage.load_linked_toc(storage)
        if linked_toc_partial and linked_toc_partial.entries and idx < len(linked_toc_partial.entries):
            entry = linked_toc_partial.entries[idx]
            status = "found" if entry and entry.scan_page else "not_found"
        else:
            status = "not_found"

        progress.agents[agent_id].status = status
        progress.agents[agent_id].completion_time = 0.0
        progress.completed_count += 1
        if status == "found":
            progress.found_count += 1
        else:
            progress.not_found_count += 1

    def process_entry(idx: int) -> AgentResult:
        toc_entry = toc_entries[idx]
        agent_id = f"entry_{idx:03d}"

        def on_event(event):
            progress.on_event(agent_id, event)

        agent = TocEntryFinderAgent(
            toc_entry=toc_entry,
            toc_entry_index=idx,
            storage=storage,
            logger=None,
            model=model,
            max_iterations=max_iterations,
            verbose=False
        )

        result = agent.search(on_event=on_event)

        linked_entry = LinkedToCEntry(
            entry_number=toc_entry.get('entry_number'),
            title=toc_entry['title'],
            level=toc_entry.get('level', 1),
            level_name=toc_entry.get('level_name'),
            printed_page_number=toc_entry.get('printed_page_number'),
            scan_page=result.scan_page,
            link_confidence=result.confidence,
            agent_reasoning=result.reasoning,
            agent_iterations=result.iterations_used,
            candidates_checked=result.candidates_checked,
        )

        stage_storage.update_linked_entry(storage, idx, linked_entry)

        from infra.llm.agent import AgentEvent
        progress.on_event(agent_id, AgentEvent(
            event_type="agent_complete",
            iteration=result.iterations_used,
            timestamp=time.time(),
            data={
                "status": "found" if result.found else "not_found",
                "total_cost": 0.0
            }
        ))

        return result

    progress.__enter__()

    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(process_entry, idx): idx for idx in remaining_indices}

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Agent {idx} failed: {str(e)}")
    finally:
        progress.__exit__(None, None, None)

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

    linked_count = sum(1 for e in linked_entries if e.scan_page is not None)
    unlinked_count = len(linked_entries) - linked_count

    linked_only = [e for e in linked_entries if e.scan_page is not None]
    avg_confidence = (
        sum(e.link_confidence for e in linked_only) / len(linked_only)
        if linked_only else 0.0
    )

    avg_iterations = sum(e.agent_iterations for e in linked_entries) / len(linked_entries) if linked_entries else 0.0

    stage_storage_obj = storage.stage("link-toc")
    all_metrics = stage_storage_obj.metrics_manager.get_all()

    total_cost_usd = sum(m.get('cost_usd', 0.0) for m in all_metrics.values())
    total_time_seconds = time.time() - start_time

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
