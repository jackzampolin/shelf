import time
from typing import Tuple, Dict, List

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.agent import AgentConfig, AgentBatchConfig, AgentBatchClient

from .schemas import LinkedTableOfContents, LinkedToCEntry
from .storage import LinkTocStageStorage
from .agent.finder import TocEntryFinderAgent
from .agent.finder_tools import TocEntryFinderTools
from .agent.prompts import FINDER_SYSTEM_PROMPT, build_finder_user_prompt


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

        stage_storage.update_linked_entry(storage, idx, linked_entry)

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
