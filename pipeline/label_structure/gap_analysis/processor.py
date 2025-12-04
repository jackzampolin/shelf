import re
import json
from typing import List, Dict, Any, Optional
from infra.pipeline.status import PhaseStatusTracker
from ..merge import get_base_merged_page


def _save_patch(tracker: PhaseStatusTracker, scan_page: int, patch_data: dict) -> None:
    tracker.phase_dir.mkdir(parents=True, exist_ok=True)
    patch_file = tracker.phase_dir / f"page_{scan_page:04d}.json"
    patch_file.write_text(json.dumps(patch_data, indent=2))


def is_roman_numeral(value: str) -> bool:
    if not value:
        return False
    return bool(re.match(r'^[IVXLCDMivxlcdm]+$', value.strip()))


def parse_page_number(value: str) -> tuple[str, Optional[int]]:
    if not value or not value.strip():
        return ('none', None)

    cleaned = value.strip().lower()

    if re.match(r'^[ivxlcdm]+$', cleaned):
        roman_map = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100, 'd': 500, 'm': 1000}
        result = 0
        prev = 0
        for char in reversed(cleaned):
            val = roman_map.get(char, 0)
            if val < prev:
                result -= val
            else:
                result += val
            prev = val
        return ('roman', result)

    if re.match(r'^\d+$', cleaned):
        return ('arabic', int(cleaned))

    return ('other', None)


def _load_all_pages(tracker: PhaseStatusTracker) -> List[Dict[str, Any]]:
    source_pages = tracker.storage.stage("source").list_pages(extension="png")
    sequence = []
    failed_pages = []

    for page_num in source_pages:
        try:
            output = get_base_merged_page(tracker.storage, page_num)

            detected_raw = None
            if output.page_number.present and output.page_number.number:
                detected_raw = output.page_number.number

            num_type, num_value = parse_page_number(detected_raw or "")

            sequence.append({
                "scan_page": page_num,
                "detected_raw": detected_raw,
                "num_type": num_type,
                "num_value": num_value,
            })
        except Exception as e:
            tracker.logger.error(f"Failed to load page {page_num}", error=str(e))
            failed_pages.append(page_num)

    if failed_pages:
        raise ValueError(
            f"Gap analysis cannot proceed: {len(failed_pages)} pages failed to load"
        )

    return sequence


def _get_arabic_value(entry: dict) -> Optional[int]:
    if entry["num_type"] == "arabic":
        return entry["num_value"]
    return None


def _heal_trivial_gaps(tracker: PhaseStatusTracker, sequence: List[Dict]) -> tuple[int, List[Dict]]:
    healed_count = 0
    complex_gaps = []

    i = 0
    while i < len(sequence):
        current = sequence[i]

        if current["num_type"] == "none":
            prev_val = None
            for j in range(i - 1, -1, -1):
                prev_val = _get_arabic_value(sequence[j])
                if prev_val is not None:
                    break

            next_val = None
            next_idx = None
            for j in range(i + 1, len(sequence)):
                next_val = _get_arabic_value(sequence[j])
                if next_val is not None:
                    next_idx = j
                    break

            if prev_val is not None and next_val is not None:
                expected_gap_size = next_val - prev_val - 1
                actual_gap_size = next_idx - i

                all_missing = all(
                    sequence[k]["num_type"] == "none"
                    for k in range(i, next_idx)
                )

                if all_missing and expected_gap_size == actual_gap_size and expected_gap_size > 0:
                    tracker.logger.info(
                        f"✓ Trivial heal: pages {sequence[i]['scan_page']:04d}-{sequence[next_idx-1]['scan_page']:04d} "
                        f"({prev_val} -> [{prev_val + 1}...{next_val - 1}] -> {next_val})"
                    )

                    for offset in range(expected_gap_size):
                        gap_page_idx = i + offset
                        expected = prev_val + 1 + offset
                        scan_page = sequence[gap_page_idx]['scan_page']

                        patch = {
                            "scan_page": scan_page,
                            "page_number": {
                                "present": True,
                                "number": str(expected),
                                "location": "margin",
                                "reasoning": f"Trivial gap heal: prev={prev_val}, next={next_val}, inferred={expected}",
                                "source_provider": "gap_healing_simple"
                            }
                        }

                        _save_patch(tracker, scan_page, patch)
                        sequence[gap_page_idx]["num_type"] = "arabic"
                        sequence[gap_page_idx]["num_value"] = expected
                        healed_count += 1

                    i = next_idx
                    continue

                elif next_val < prev_val:
                    complex_gaps.append({
                        "scan_page": current["scan_page"],
                        "type": "backwards",
                        "prev": prev_val,
                        "next": next_val,
                    })
                elif expected_gap_size != actual_gap_size:
                    complex_gaps.append({
                        "scan_page": current["scan_page"],
                        "type": f"mismatch_gap_{actual_gap_size}_expected_{expected_gap_size}",
                        "prev": prev_val,
                        "next": next_val,
                    })
                else:
                    complex_gaps.append({
                        "scan_page": current["scan_page"],
                        "type": "multi_page_jump",
                        "prev": prev_val,
                        "next": next_val,
                    })

            elif prev_val is None and next_val is None:
                complex_gaps.append({
                    "scan_page": current["scan_page"],
                    "type": "isolated",
                    "prev": None,
                    "next": None,
                })
            else:
                complex_gaps.append({
                    "scan_page": current["scan_page"],
                    "type": "edge_gap",
                    "prev": prev_val,
                    "next": next_val,
                })

        elif current["num_type"] == "other":
            prev_val = _get_arabic_value(sequence[i-1]) if i > 0 else None
            next_val = _get_arabic_value(sequence[i+1]) if i < len(sequence) - 1 else None

            if prev_val is not None and next_val is not None and next_val == prev_val + 2:
                expected = prev_val + 1
                scan_page = current['scan_page']

                tracker.logger.info(
                    f"✓ OCR error heal: page_{scan_page:04d} "
                    f"({prev_val} -> [{current['detected_raw']}→{expected}] -> {next_val})"
                )

                patch = {
                    "scan_page": scan_page,
                    "page_number": {
                        "present": True,
                        "number": str(expected),
                        "location": "margin",
                        "reasoning": f"OCR error heal: detected='{current['detected_raw']}', corrected={expected}",
                        "source_provider": "gap_healing_simple"
                    }
                }

                _save_patch(tracker, scan_page, patch)
                sequence[i]["num_type"] = "arabic"
                sequence[i]["num_value"] = expected
                healed_count += 1
            else:
                complex_gaps.append({
                    "scan_page": current["scan_page"],
                    "type": "unparseable",
                    "raw_value": current["detected_raw"],
                    "prev": prev_val,
                    "next": next_val,
                })

        i += 1

    return healed_count, complex_gaps


def _calculate_sequence_status(sequence: List[Dict]) -> List[Dict]:
    prev_type = None
    prev_value = None

    for entry in sequence:
        entry["status"] = "unknown"
        entry["expected"] = None

        if entry["num_type"] == "none":
            entry["status"] = "no_number"
            continue

        if entry["num_value"] is None:
            entry["status"] = "unparseable"
            continue

        if prev_value is None:
            entry["status"] = "first_page"
            prev_type = entry["num_type"]
            prev_value = entry["num_value"]
            continue

        if entry["num_type"] != prev_type:
            entry["status"] = "type_change"
            entry["expected"] = prev_value + 1
            prev_type = entry["num_type"]
            prev_value = entry["num_value"]
            continue

        gap = entry["num_value"] - prev_value
        entry["expected"] = prev_value + 1

        if gap < 0:
            entry["status"] = "backward_jump"
        elif gap == 1:
            entry["status"] = "ok"
        elif gap == 2:
            entry["status"] = "gap_1"
        else:
            entry["status"] = f"gap_{gap - 1}"

        prev_type = entry["num_type"]
        prev_value = entry["num_value"]

    return sequence


def _identify_clusters(sequence: List[Dict]) -> List[Dict]:
    clusters = []
    seq_by_page = {e["scan_page"]: e for e in sequence}

    for entry in sequence:
        if entry["status"] == "backward_jump":
            cascade_pages = [entry["scan_page"]]
            current_page = entry["scan_page"]

            while True:
                next_page = current_page + 1
                if next_page not in seq_by_page:
                    break
                next_entry = seq_by_page[next_page]
                if next_entry["status"] == "ok":
                    break
                if next_entry["status"].startswith("gap_") or next_entry["status"] == "no_number":
                    cascade_pages.append(next_page)
                    current_page = next_page
                else:
                    break

            clusters.append({
                "cluster_id": f"backward_jump_{entry['scan_page']:04d}",
                "type": "backward_jump",
                "scan_pages": cascade_pages,
                "priority": "high",
                "detected_value": entry["num_value"],
                "expected_value": entry["expected"]
            })

    for entry in sequence:
        if entry["status"] == "unparseable":
            clusters.append({
                "cluster_id": f"ocr_error_{entry['scan_page']:04d}",
                "type": "ocr_error",
                "scan_pages": [entry["scan_page"]],
                "priority": "medium",
                "raw_value": entry.get("detected_raw"),
                "expected_value": entry["expected"]
            })

    i = 0
    while i < len(sequence):
        entry = sequence[i]
        if entry["status"] in ["gap_3", "gap_4", "gap_5", "gap_6"]:
            gap_size = int(entry["status"].split("_")[1])
            gap_pages = [entry["scan_page"]]

            j = i + 1
            while len(gap_pages) < gap_size and j < len(sequence):
                next_entry = sequence[j]
                if next_entry["status"] in ["no_number"] or next_entry["status"].startswith("gap_"):
                    gap_pages.append(next_entry["scan_page"])
                    j += 1
                else:
                    break

            clusters.append({
                "cluster_id": f"structural_gap_{entry['scan_page']:04d}",
                "type": "structural_gap",
                "scan_pages": gap_pages,
                "priority": "low",
                "gap_size": gap_size
            })

            i = j
            continue

        if entry["status"].startswith("mismatch_gap_"):
            parts = entry["status"].split("_")
            actual_gap = int(parts[2])
            expected_gap = int(parts[4])

            clusters.append({
                "cluster_id": f"mismatch_{entry['scan_page']:04d}",
                "type": "gap_mismatch",
                "scan_pages": [entry["scan_page"]],
                "priority": "high",
                "actual_gap": actual_gap,
                "expected_gap": expected_gap
            })

        if entry["status"] in ["isolated", "edge_gap", "multi_page_jump"]:
            clusters.append({
                "cluster_id": f"isolated_{entry['scan_page']:04d}",
                "type": entry["status"],
                "scan_pages": [entry["scan_page"]],
                "priority": "medium"
            })

        i += 1

    return clusters


def analyze_gaps(tracker: PhaseStatusTracker, **kwargs) -> Dict[str, Any]:
    tracker.logger.info("=== Gap Analysis: Analyzing page number sequence ===")

    sequence = _load_all_pages(tracker)
    tracker.logger.info(f"Loaded {len(sequence)} pages")

    healed_count, complex_from_healing = _heal_trivial_gaps(tracker, sequence)
    tracker.logger.info(f"Trivially healed {healed_count} pages")

    sequence = _calculate_sequence_status(sequence)

    clusters = _identify_clusters(sequence)

    cluster_types = {}
    for c in clusters:
        t = c["type"]
        cluster_types[t] = cluster_types.get(t, 0) + 1

    tracker.logger.info(f"Identified {len(clusters)} clusters for agent healing:")
    for t, count in sorted(cluster_types.items()):
        tracker.logger.info(f"  - {t}: {count}")

    result = {
        "total_pages": len(sequence),
        "trivially_healed": healed_count,
        "clusters": clusters,
        "clusters_by_type": cluster_types,
    }

    output_path = tracker.phase_dir / "clusters.json"
    output_path.write_text(json.dumps(result, indent=2))

    return result
