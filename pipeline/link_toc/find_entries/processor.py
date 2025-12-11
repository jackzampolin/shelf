import time
from typing import Dict, List

from infra.pipeline.storage.book_storage import BookStorage
from infra.llm.agent import AgentConfig, AgentBatchConfig, AgentBatchClient

from ..schemas import LinkedTableOfContents, LinkedToCEntry
from .agent.finder_tools import TocEntryFinderTools
from .agent.prompts import FINDER_SYSTEM_PROMPT, build_finder_user_prompt
from .agent.tools import get_book_structure


def _get_completed_entry_indices(storage: BookStorage) -> List[int]:
    linked_toc_path = storage.stage("link-toc").output_dir / "linked_toc.json"
    if not linked_toc_path.exists():
        return []

    data = storage.stage("link-toc").load_file("linked_toc.json")
    linked_toc = LinkedTableOfContents(**data) if data else None

    if not linked_toc or not linked_toc.entries:
        return []

    return [idx for idx, entry in enumerate(linked_toc.entries) if entry is not None]


def _update_linked_entry(storage: BookStorage, entry_index: int, linked_entry: LinkedToCEntry):
    stage_storage = storage.stage("link-toc")
    linked_toc_path = stage_storage.output_dir / "linked_toc.json"

    if linked_toc_path.exists():
        data = stage_storage.load_file("linked_toc.json")
    else:
        data = {
            "entries": [],
            "toc_page_range": {},
            "entries_by_level": {},
            "original_parsing_confidence": 0.0,
            "total_entries": 0,
            "linked_entries": 0,
            "unlinked_entries": 0,
            "total_cost_usd": 0.0,
            "total_time_seconds": 0.0,
        }

    entries = data.get("entries", [])
    entry_dict = linked_entry.model_dump()

    while len(entries) <= entry_index:
        entries.append(None)
    entries[entry_index] = entry_dict
    data["entries"] = entries

    stage_storage.save_file("linked_toc.json", data)


def _finalize_linked_toc_metadata(
    storage: BookStorage,
    toc_page_range: Dict,
    entries_by_level: Dict,
    original_parsing_confidence: float,
    total_entries: int,
    linked_entries: int,
    unlinked_entries: int,
    total_cost_usd: float,
    total_time_seconds: float,
):
    stage_storage = storage.stage("link-toc")
    linked_toc_path = stage_storage.output_dir / "linked_toc.json"

    if not linked_toc_path.exists():
        return

    data = stage_storage.load_file("linked_toc.json")
    data.update({
        "toc_page_range": toc_page_range,
        "entries_by_level": entries_by_level,
        "original_parsing_confidence": original_parsing_confidence,
        "total_entries": total_entries,
        "linked_entries": linked_entries,
        "unlinked_entries": unlinked_entries,
        "total_cost_usd": total_cost_usd,
        "total_time_seconds": total_time_seconds,
    })
    stage_storage.save_file("linked_toc.json", data)


def _create_linked_entry_from_result(toc_entry: Dict, agent_result, tools) -> LinkedToCEntry:
    if agent_result.success and tools._pending_result:
        result_data = tools._pending_result
        return LinkedToCEntry(
            entry_number=toc_entry.get('entry_number'),
            title=toc_entry.get('title', ''),
            level=toc_entry.get('level', 1),
            level_name=toc_entry.get('level_name'),
            printed_page_number=toc_entry.get('printed_page_number'),
            scan_page=result_data["scan_page"],
            agent_reasoning=result_data["reasoning"],
        )
    else:
        return LinkedToCEntry(
            entry_number=toc_entry.get('entry_number'),
            title=toc_entry.get('title', ''),
            level=toc_entry.get('level', 1),
            level_name=toc_entry.get('level_name'),
            printed_page_number=toc_entry.get('printed_page_number'),
            scan_page=None,
            agent_reasoning=agent_result.error_message or "Agent failed",
        )


def find_all_toc_entries(tracker, **kwargs):
    model = kwargs.get('model')
    max_iterations = kwargs.get('max_iterations', 15)
    start_time = time.time()

    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    extract_toc_output = storage.stage("extract-toc").load_file("toc.json")
    if not extract_toc_output:
        logger.warning("No ToC data found in extract-toc output")
        return

    if 'toc' in extract_toc_output and 'entries' in extract_toc_output.get('toc', {}):
        toc_data = extract_toc_output['toc']
    else:
        toc_data = extract_toc_output

    if not toc_data.get('entries'):
        logger.warning("No ToC entries found in extract-toc output")
        return

    toc_entries = toc_data['entries']
    total_entries = len(toc_entries)

    completed_indices = _get_completed_entry_indices(storage)
    remaining_indices = [idx for idx in range(total_entries) if idx not in completed_indices]

    if completed_indices:
        logger.info(f"Resuming: {len(completed_indices)}/{total_entries} entries already complete")
    logger.info(f"Processing {len(remaining_indices)} remaining ToC entries")

    total_pages = storage.load_metadata().get('total_pages', 0)

    # Get book structure once for all agents
    book_structure = get_book_structure(storage, logger)
    back_start = book_structure.get("back_matter", {}).get("start_page")
    if back_start:
        logger.info(f"Book structure: back matter starts around page {back_start}")

    configs = []
    tools_by_idx = {}

    for idx in remaining_indices:
        toc_entry = toc_entries[idx]
        tools = TocEntryFinderTools(storage, toc_entry, total_pages, logger)
        tools_by_idx[idx] = tools

        configs.append(AgentConfig(
            model=model,
            initial_messages=[
                {"role": "system", "content": FINDER_SYSTEM_PROMPT},
                {"role": "user", "content": build_finder_user_prompt(toc_entry, idx, total_pages, book_structure)}
            ],
            tools=tools,
            tracker=tracker,
            agent_id=f"entry-{idx:03d}",
            max_iterations=max_iterations
        ))

    batch_config = AgentBatchConfig(
        tracker=tracker,
        agent_configs=configs,
        batch_name="find-entries",
        max_workers=10
    )

    batch_result = AgentBatchClient(batch_config).run()

    for agent_result, idx in zip(batch_result.results, remaining_indices):
        linked_entry = _create_linked_entry_from_result(toc_entries[idx], agent_result, tools_by_idx[idx])
        _update_linked_entry(storage, idx, linked_entry)

    data = stage_storage.load_file("linked_toc.json")
    linked_toc = LinkedTableOfContents(**data) if data else None

    if not linked_toc or not linked_toc.entries:
        logger.warning("No linked ToC data found after processing")
        return

    linked_entries = [e for e in linked_toc.entries if e is not None]
    linked_count = sum(1 for e in linked_entries if e.scan_page is not None)
    unlinked_count = len(linked_entries) - linked_count

    total_cost_usd = sum(m.get('cost_usd', 0.0) for m in stage_storage.metrics_manager.get_all().values())
    total_time_seconds = time.time() - start_time

    _finalize_linked_toc_metadata(
        storage=storage,
        toc_page_range=toc_data.get('toc_page_range', {}),
        entries_by_level=toc_data.get('entries_by_level', {}),
        original_parsing_confidence=toc_data.get('parsing_confidence', 0.0),
        total_entries=len(linked_entries),
        linked_entries=linked_count,
        unlinked_entries=unlinked_count,
        total_cost_usd=total_cost_usd,
        total_time_seconds=total_time_seconds,
    )

    stage_storage.metrics_manager.record(
        key="find_entries",
        cost_usd=total_cost_usd,
        time_seconds=total_time_seconds,
        custom_metrics={"total_entries": len(linked_entries), "found_entries": linked_count}
    )

    logger.info(
        f"All entries processed: {linked_count}/{len(linked_entries)} linked, "
        f"cost ${total_cost_usd:.4f}, time {total_time_seconds:.1f}s"
    )
