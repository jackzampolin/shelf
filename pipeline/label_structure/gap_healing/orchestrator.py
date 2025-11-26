import csv
import time
from pathlib import Path
from typing import Dict, List

from infra.pipeline.status import PhaseStatusTracker
from infra.llm.agent import AgentConfig, AgentBatchConfig, AgentBatchClient

from .agent.healer_tools import GapHealingTools
from .agent.prompts import HEALER_SYSTEM_PROMPT, build_healer_user_prompt
from ..merge import get_simple_fixes_merged_page
from .clustering import generate_report_data


def _load_report_data(tracker: PhaseStatusTracker) -> Dict[int, Dict]:
    rows = generate_report_data(tracker.storage, tracker.logger)
    report_data = {}
    for row in rows:
        page_num = row['scan_page']
        report_data[page_num] = row
    return report_data


def _get_sequence_context(cluster: Dict, report_data: Dict[int, Dict], context_size: int = 3) -> List[Dict]:
    scan_pages = cluster['scan_pages']
    min_page = min(scan_pages)
    max_page = max(scan_pages)

    start_page = max(1, min_page - context_size)
    end_page = max_page + context_size

    context = []
    for page_num in range(start_page, end_page + 1):
        if page_num in report_data:
            context.append(report_data[page_num])

    return context


def _get_page_data_for_cluster(tracker: PhaseStatusTracker, cluster: Dict) -> Dict[int, Dict]:
    page_data_map = {}
    failed_pages = []

    for page_num in cluster['scan_pages']:
        try:
            page_output = get_simple_fixes_merged_page(tracker.storage, page_num)
            page_data_map[page_num] = page_output.model_dump()
        except Exception as e:
            tracker.logger.error(
                f"Failed to load page {page_num} for cluster {cluster['cluster_id']}",
                page_num=page_num,
                cluster_id=cluster['cluster_id'],
                error=str(e)
            )
            failed_pages.append(page_num)

    if failed_pages:
        raise ValueError(
            f"Cannot process cluster {cluster['cluster_id']}: "
            f"{len(failed_pages)} pages failed to load ({failed_pages})"
        )

    return page_data_map




def _get_completed_clusters(tracker: PhaseStatusTracker, clusters: List[Dict]) -> List[str]:
    stage_storage = tracker.storage.stage("label-structure")
    healing_dir = stage_storage.output_dir / "agent_healing"

    if not healing_dir.exists():
        return []

    completed = []

    for cluster in clusters:
        cluster_id = cluster['cluster_id']
        marker_path = healing_dir / f"cluster_{cluster_id}.json"

        if marker_path.exists():
            completed.append(cluster_id)

    return completed


def heal_all_clusters(tracker: PhaseStatusTracker, **kwargs):
    model = kwargs.get("model")
    max_iterations = kwargs.get("max_iterations", 10)
    max_workers = kwargs.get("max_workers", 10)
    verbose = kwargs.get("verbose", False)

    start_time = time.time()

    stage_storage = tracker.storage.stage("label-structure")

    try:
        cluster_data = stage_storage.load_file("clusters/clusters.json")
    except Exception as e:
        tracker.logger.error(f"Failed to load clusters.json: {e}")
        raise ValueError(f"Agent healing requires clusters.json - run clustering phase first: {e}")

    clusters = cluster_data.get('clusters', [])
    total_clusters = len(clusters)

    if not clusters:
        tracker.logger.warning("No clusters found in clusters.json")
        return

    completed_cluster_ids = _get_completed_clusters(tracker, clusters)
    remaining_clusters = [c for c in clusters if c['cluster_id'] not in completed_cluster_ids]

    if completed_cluster_ids:
        tracker.logger.info(f"Resuming: {len(completed_cluster_ids)}/{total_clusters} clusters already healed")

    if not remaining_clusters:
        tracker.logger.info("All clusters already healed!")
        return

    tracker.logger.info(f"Dispatching {len(remaining_clusters)} gap healing agents")

    report_data = _load_report_data(tracker)

    configs = []
    tools_by_cluster_id = {}

    for cluster in remaining_clusters:
        cluster_id = cluster['cluster_id']
        agent_id = f"heal_{cluster_id}"

        page_data_map = _get_page_data_for_cluster(tracker, cluster)
        sequence_context = _get_sequence_context(cluster, report_data, context_size=3)

        tools = GapHealingTools(tracker.storage, cluster)
        tools_by_cluster_id[cluster_id] = tools

        initial_messages = [
            {"role": "system", "content": HEALER_SYSTEM_PROMPT},
            {"role": "user", "content": build_healer_user_prompt(cluster, page_data_map, sequence_context)}
        ]

        configs.append(AgentConfig(
            tracker=tracker,
            agent_id=agent_id,
            model=model,
            tools=tools,
            initial_messages=initial_messages,
            max_iterations=max_iterations
        ))

    batch_config = AgentBatchConfig(
        tracker=tracker,
        agent_configs=configs,
        batch_name="label-structure-gap-healing",
        max_workers=max_workers
    )

    batch = AgentBatchClient(batch_config)
    batch_result = batch.run()

    healed_pages = 0
    failed_clusters = 0
    total_cost = 0.0

    for agent_result, cluster, config in zip(batch_result.results, remaining_clusters, configs):
        cluster_id = cluster['cluster_id']
        tools = tools_by_cluster_id[cluster_id]
        pages_healed = tools.get_pages_healed()

        if agent_result.success and tools.is_complete():
            healed_pages += len(pages_healed)

            if pages_healed:
                tracker.logger.info(
                    f"✓ {cluster_id}: {len(pages_healed)} pages healed "
                    f"(${agent_result.total_cost_usd:.4f}, {agent_result.iterations} iter)"
                )
            else:
                tracker.logger.info(
                    f"✓ {cluster_id}: no healing needed "
                    f"(${agent_result.total_cost_usd:.4f}, {agent_result.iterations} iter)"
                )
        else:
            failed_clusters += 1
            if agent_result.success and not tools.is_complete():
                error_msg = "Agent finished but did not call finish_cluster"
            else:
                error_msg = agent_result.error_message or "Agent failed"
            tracker.logger.warning(f"✗ {cluster_id}: {error_msg}")

        total_cost += agent_result.total_cost_usd

    total_time = time.time() - start_time

    stage_storage.metrics_manager.record(
        key="gap_healing_agents",
        cost_usd=total_cost,
        time_seconds=total_time,
        custom_metrics={
            "total_clusters": len(remaining_clusters),
            "healed_pages": healed_pages,
            "failed_clusters": failed_clusters,
        }
    )

    tracker.logger.info(
        f"Gap healing complete: {healed_pages} pages healed from {len(remaining_clusters)} clusters, "
        f"${total_cost:.4f}, {total_time:.1f}s"
    )

    if failed_clusters > 0:
        tracker.logger.warning(f"{failed_clusters} clusters failed - may need manual review")
