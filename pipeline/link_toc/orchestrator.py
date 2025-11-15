import time
from typing import Tuple, Dict, List

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.agent import AgentConfig, AgentBatchConfig, AgentBatchClient

from .schemas import LinkedTableOfContents, LinkedToCEntry
from .agent.finder import TocEntryFinderAgent
from .agent.finder_tools import TocEntryFinderTools
from .agent.prompts import FINDER_SYSTEM_PROMPT, build_finder_user_prompt


def _get_completed_entry_indices(storage: BookStorage) -> List[int]:
    """Return list of entry indices that have already been processed."""
    linked_toc_path = storage.stage("link-toc").output_dir / "linked_toc.json"
    if not linked_toc_path.exists():
        return []

    data = storage.stage("link-toc").load_file("linked_toc.json")
    linked_toc = LinkedTableOfContents(**data) if data else None

    if not linked_toc or not linked_toc.entries:
        return []

    # Return indices of non-None entries
    return [idx for idx, entry in enumerate(linked_toc.entries) if entry is not None]


def _update_linked_entry(storage: BookStorage, entry_index: int, linked_entry: LinkedToCEntry):
    """Update a single entry in linked_toc.json for incremental progress."""
    stage_storage = storage.stage("link-toc")
    linked_toc_path = stage_storage.output_dir / "linked_toc.json"

    # Load or create linked_toc structure
    if linked_toc_path.exists():
        data = stage_storage.load_file("linked_toc.json")
    else:
        # Initialize empty structure
        data = {
            "entries": [],
            "toc_page_range": {},
            "entries_by_level": {},
            "original_parsing_confidence": 0.0,
            "total_entries": 0,
            "linked_entries": 0,
            "unlinked_entries": 0,
            "avg_link_confidence": 0.0,
            "total_cost_usd": 0.0,
            "total_time_seconds": 0.0,
            "avg_iterations_per_entry": 0.0
        }

    # Update or append entry
    entries = data.get("entries", [])
    entry_dict = linked_entry.model_dump()

    # Pad list if needed and insert at index
    while len(entries) <= entry_index:
        entries.append(None)
    entries[entry_index] = entry_dict

    data["entries"] = entries

    # Save using existing infrastructure (already has locking)
    stage_storage.save_file("linked_toc.json", data)


def _finalize_linked_toc_metadata(
    storage: BookStorage,
    toc_page_range: Dict,
    entries_by_level: Dict,
    original_parsing_confidence: float,
    total_entries: int,
    linked_entries: int,
    unlinked_entries: int,
    avg_link_confidence: float,
    total_cost_usd: float,
    total_time_seconds: float,
    avg_iterations_per_entry: float
):
    """Update metadata fields in linked_toc.json after all entries processed."""
    stage_storage = storage.stage("link-toc")
    linked_toc_path = stage_storage.output_dir / "linked_toc.json"

    if not linked_toc_path.exists():
        return

    # Load existing data
    data = stage_storage.load_file("linked_toc.json")

    # Update metadata
    data.update({
        "toc_page_range": toc_page_range,
        "entries_by_level": entries_by_level,
        "original_parsing_confidence": original_parsing_confidence,
        "total_entries": total_entries,
        "linked_entries": linked_entries,
        "unlinked_entries": unlinked_entries,
        "avg_link_confidence": avg_link_confidence,
        "total_cost_usd": total_cost_usd,
        "total_time_seconds": total_time_seconds,
        "avg_iterations_per_entry": avg_iterations_per_entry
    })

    # Save using existing infrastructure (already has locking)
    stage_storage.save_file("linked_toc.json", data)


def find_all_toc_entries(tracker, **kwargs):
    model = kwargs.get('model')
    max_iterations = kwargs.get('max_iterations', 15)
    verbose = kwargs.get('verbose', False)

    start_time = time.time()

    # Access storage and logger through tracker
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    # Load ToC entries from extract-toc
    extract_toc_output = storage.stage("extract-toc").load_file("toc.json")

    toc_data = extract_toc_output.get('toc', {}) if extract_toc_output else {}

    if not toc_data or not toc_data.get('entries'):
        logger.warning("No ToC entries found in extract-toc output")
        return

    toc_entries = toc_data['entries']

    total_entries = len(toc_entries)

    completed_indices = _get_completed_entry_indices(storage)
    remaining_indices = [idx for idx in range(total_entries) if idx not in completed_indices]

    if completed_indices:
        logger.info(f"Resuming: {len(completed_indices)}/{total_entries} entries already complete")

    logger.info(f"Processing {len(remaining_indices)} remaining ToC entries")

    metadata = storage.load_metadata()
    total_pages = metadata.get('total_pages', 0)

    configs = []
    tools_by_idx = {}

    for idx in remaining_indices:
        toc_entry = toc_entries[idx]
        agent_id = f"entry-{idx:03d}"

        tools = TocEntryFinderTools(
            storage=storage,
            toc_entry=toc_entry,
            total_pages=total_pages
        )
        tools_by_idx[idx] = tools

        initial_messages = [
            {"role": "system", "content": FINDER_SYSTEM_PROMPT},
            {"role": "user", "content": build_finder_user_prompt(toc_entry, idx, total_pages)}
        ]

        configs.append(AgentConfig(
            model=model,
            initial_messages=initial_messages,
            tools=tools,
            stage_storage=storage.stage('link-toc'),
            agent_id=agent_id,
            max_iterations=max_iterations
        ))

    batch_config = AgentBatchConfig(
        agent_configs=configs,
        max_workers=10
    )

    batch = AgentBatchClient(batch_config)
    batch_result = batch.run()

    for agent_result, idx in zip(batch_result.results, remaining_indices):
        toc_entry = toc_entries[idx]
        tools = tools_by_idx[idx]

        if agent_result.success and tools._pending_result:
            result_data = tools._pending_result
            linked_entry = LinkedToCEntry(
                entry_number=toc_entry.get('entry_number'),
                title=toc_entry['title'],
                level=toc_entry.get('level', 1),
                level_name=toc_entry.get('level_name'),
                printed_page_number=toc_entry.get('printed_page_number'),
                scan_page=result_data["scan_page"],
                link_confidence=result_data["confidence"],
                agent_reasoning=result_data["reasoning"],
                agent_iterations=agent_result.iterations,
                candidates_checked=tools._candidates_checked,
            )
        else:
            linked_entry = LinkedToCEntry(
                entry_number=toc_entry.get('entry_number'),
                title=toc_entry['title'],
                level=toc_entry.get('level', 1),
                level_name=toc_entry.get('level_name'),
                printed_page_number=toc_entry.get('printed_page_number'),
                scan_page=None,
                link_confidence=0.0,
                agent_reasoning=agent_result.error_message or "Agent failed",
                agent_iterations=agent_result.iterations,
                candidates_checked=tools._candidates_checked if tools else [],
            )

        _update_linked_entry(storage, idx, linked_entry)

    # Load final linked_toc
    data = stage_storage.load_file("linked_toc.json")
    linked_toc = LinkedTableOfContents(**data) if data else None

    if not linked_toc or not linked_toc.entries:
        logger.warning("No linked ToC data found after processing")
        return

    linked_entries = [e for e in linked_toc.entries if e is not None]

    linked_count = sum(1 for e in linked_entries if e.scan_page is not None)
    unlinked_count = len(linked_entries) - linked_count

    linked_only = [e for e in linked_entries if e.scan_page is not None]
    avg_confidence = (
        sum(e.link_confidence for e in linked_only) / len(linked_only)
        if linked_only else 0.0
    )

    avg_iterations = sum(e.agent_iterations for e in linked_entries) / len(linked_entries) if linked_entries else 0.0

    all_metrics = stage_storage.metrics_manager.get_all()

    total_cost_usd = sum(m.get('cost_usd', 0.0) for m in all_metrics.values())
    total_time_seconds = time.time() - start_time

    # Finalize metadata in linked_toc.json
    _finalize_linked_toc_metadata(
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

    # Record metrics
    stage_storage.metrics_manager.record(
        key="find_entries",
        cost_usd=total_cost_usd,
        time_seconds=total_time_seconds,
        custom_metrics={
            "total_entries": len(linked_entries),
            "found_entries": linked_count,
        }
    )

    logger.info(
        f"All entries processed: {linked_count}/{len(linked_entries)} linked, "
        f"cost ${total_cost_usd:.4f}, time {total_time_seconds:.1f}s"
    )
