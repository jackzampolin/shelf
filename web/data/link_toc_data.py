from typing import Optional, Dict, Any, List
from infra.pipeline.storage.book_storage import BookStorage


def get_enriched_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    link_toc_storage = storage.stage("link-toc")
    enriched_path = link_toc_storage.output_dir / "enriched_toc.json"

    if not enriched_path.exists():
        return None

    return link_toc_storage.load_file("enriched_toc.json")


def get_pattern_analysis(storage: BookStorage) -> Optional[Dict[str, Any]]:
    link_toc_storage = storage.stage("link-toc")
    pattern_path = link_toc_storage.output_dir / "pattern" / "pattern_analysis.json"

    if not pattern_path.exists():
        return None

    return link_toc_storage.load_file("pattern/pattern_analysis.json")


def get_evaluation_summary(storage: BookStorage) -> Optional[Dict[str, Any]]:
    link_toc_storage = storage.stage("link-toc")
    eval_dir = link_toc_storage.output_dir / "evaluation"

    if not eval_dir.exists():
        return None

    decision_files = sorted(eval_dir.glob("heading_*.json"))
    if not decision_files:
        return None

    decisions = []
    for decision_file in decision_files:
        decision_data = link_toc_storage.load_file(f"evaluation/{decision_file.name}")
        if decision_data:
            decisions.append(decision_data)

    included = sum(1 for d in decisions if d.get('include', False))
    excluded = len(decisions) - included

    return {
        'total_evaluated': len(decisions),
        'included_count': included,
        'excluded_count': excluded,
        'decisions': decisions
    }


def get_link_toc_data(storage: BookStorage) -> Optional[Dict[str, Any]]:
    link_toc_storage = storage.stage("link-toc")

    enriched_data = get_enriched_toc_data(storage)

    if enriched_data:
        linked_toc_data = link_toc_storage.load_file("linked_toc.json")

        return {
            'entries': enriched_data.get('entries', []),
            'metadata': {
                'total_entries': enriched_data.get('total_entries', 0),
                'original_toc_count': enriched_data.get('original_toc_count', 0),
                'discovered_count': enriched_data.get('discovered_count', 0),
            },
            'stats': {
                'total_cost_usd': linked_toc_data.get('total_cost_usd', 0.0) if linked_toc_data else 0.0,
                'total_time_seconds': linked_toc_data.get('total_time_seconds', 0.0) if linked_toc_data else 0.0,
            },
            'is_enriched': True,
            'pattern_analysis': get_pattern_analysis(storage),
            'evaluation_summary': get_evaluation_summary(storage),
        }

    linked_toc_path = link_toc_storage.output_dir / "linked_toc.json"

    if not linked_toc_path.exists():
        return None

    linked_toc_data = link_toc_storage.load_file("linked_toc.json")

    if not linked_toc_data:
        return None

    return {
        'entries': linked_toc_data.get('entries', []),
        'metadata': {
            'total_entries': linked_toc_data.get('total_entries', 0),
            'linked_entries': linked_toc_data.get('linked_entries', 0),
            'unlinked_entries': linked_toc_data.get('unlinked_entries', 0),
        },
        'stats': {
            'total_cost_usd': linked_toc_data.get('total_cost_usd', 0.0),
            'total_time_seconds': linked_toc_data.get('total_time_seconds', 0.0),
        },
        'is_enriched': False,
        'pattern_analysis': None,
        'evaluation_summary': None,
    }


def get_linked_entries_tree(storage: BookStorage) -> Optional[List[Dict[str, Any]]]:
    data = get_link_toc_data(storage)
    if not data:
        return None

    entries = data.get('entries', [])
    if not entries:
        return []

    return [entry for entry in entries if entry is not None]
