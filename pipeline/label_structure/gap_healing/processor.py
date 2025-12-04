import re
import json
from infra.pipeline.status import PhaseStatusTracker
from ..schemas.merged_output import LabelStructurePageOutput
from ..schemas.structure import PageNumberObservation
from ..merge import get_merged_page


def _save_patch(tracker: PhaseStatusTracker, scan_page: int, patch_data: dict) -> None:
    tracker.phase_dir.mkdir(parents=True, exist_ok=True)
    patch_file = tracker.phase_dir / f"page_{scan_page:04d}.json"
    patch_file.write_text(json.dumps(patch_data, indent=2))


def is_roman_numeral(value: str) -> bool:
    if not value:
        return False
    return bool(re.match(r'^[IVXLCDMivxlcdm]+$', value.strip()))


def get_arabic_value(page_data: dict) -> int | None:
    detected = page_data.get("detected")
    if detected is None:
        return None

    if isinstance(detected, int):
        return detected

    if isinstance(detected, str):
        if is_roman_numeral(detected):
            return None
        try:
            return int(detected)
        except ValueError:
            return None

    return None


def heal_page_number_gaps(tracker: PhaseStatusTracker, **kwargs) -> dict:
    tracker.logger.info("=== Gap Healing: Analyzing page numbers ===")

    stage_storage = tracker.storage.stage("label-structure")
    source_pages = tracker.storage.stage("source").list_pages(extension="png")
    total_pages = len(source_pages)

    sequence = []
    failed_pages = []

    for page_num in range(1, total_pages + 1):
        try:
            # Use get_merged_page to get current state (mechanical + structure + annotations)
            output = get_merged_page(tracker.storage, page_num)

            detected_value = None
            detected_raw = None
            if output.page_number.present and output.page_number.number:
                detected_raw = output.page_number.number
                if is_roman_numeral(detected_raw):
                    detected_value = detected_raw  # Keep as string for roman
                else:
                    try:
                        detected_value = int(detected_raw)
                    except (ValueError, TypeError):
                        detected_value = detected_raw  # Keep raw if can't parse

            sequence.append({
                "scan_page": page_num,
                "detected": detected_value,
                "detected_raw": detected_raw,
                "output": output
            })
        except Exception as e:
            tracker.logger.error(
                f"Failed to load page {page_num}",
                page_num=page_num,
                error=str(e),
                error_type=type(e).__name__
            )
            failed_pages.append(page_num)

    if failed_pages:
        raise ValueError(
            f"Gap healing cannot proceed: {len(failed_pages)} pages failed to load "
            f"(pages: {', '.join(str(p) for p in failed_pages[:10])}{'...' if len(failed_pages) > 10 else ''})"
        )

    trivial_healed = 0
    ocr_error_healed = 0
    complex_gaps = []

    i = 0
    while i < len(sequence):
        current = sequence[i]

        if current["detected"] is None:
            prev_val = None
            for j in range(i - 1, -1, -1):
                prev_val = get_arabic_value(sequence[j])
                if prev_val is not None:
                    break

            next_val = None
            next_idx = None
            for j in range(i + 1, len(sequence)):
                next_val = get_arabic_value(sequence[j])
                if next_val is not None:
                    next_idx = j
                    break

            if prev_val is not None and next_val is not None:
                expected_gap_size = next_val - prev_val - 1
                actual_gap_size = next_idx - i

                all_missing = all(
                    sequence[k]["detected"] is None
                    for k in range(i, next_idx)
                )

                if all_missing and expected_gap_size == actual_gap_size and expected_gap_size > 0:
                    gap_type = f"gap_{expected_gap_size}"
                    tracker.logger.info(
                        f"✓ {gap_type} heal: pages {sequence[i]['scan_page']:04d}-{sequence[next_idx-1]['scan_page']:04d} "
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
                                "confidence": "high",
                                "source_provider": "gap_healing_simple"
                            }
                        }

                        _save_patch(tracker, scan_page, patch)
                        sequence[gap_page_idx]["detected"] = expected
                        trivial_healed += 1

                    i = next_idx
                    continue
                elif next_val < prev_val:
                    complex_gaps.append({
                        "scan_page": current["scan_page"],
                        "prev": prev_val,
                        "next": next_val,
                        "type": "backwards"
                    })
                elif expected_gap_size != actual_gap_size:
                    complex_gaps.append({
                        "scan_page": current["scan_page"],
                        "prev": prev_val,
                        "next": next_val,
                        "type": f"mismatch_gap_{actual_gap_size}_expected_{expected_gap_size}"
                    })
                else:
                    complex_gaps.append({
                        "scan_page": current["scan_page"],
                        "prev": prev_val,
                        "next": next_val,
                        "type": "multi_page_jump"
                    })
            elif prev_val is None and next_val is None:
                complex_gaps.append({
                    "scan_page": current["scan_page"],
                    "prev": None,
                    "next": None,
                    "type": "isolated"
                })
            else:
                complex_gaps.append({
                    "scan_page": current["scan_page"],
                    "prev": prev_val,
                    "next": next_val,
                    "type": "edge_gap"
                })

        elif isinstance(current["detected"], str) and is_roman_numeral(current["detected"]):
            prev_val = get_arabic_value(sequence[i-1]) if i > 0 else None
            next_val = get_arabic_value(sequence[i+1]) if i < len(sequence) - 1 else None

            if prev_val is not None and next_val is not None:
                if next_val == prev_val + 2:
                    expected = prev_val + 1
                    scan_page = current['scan_page']

                    tracker.logger.info(
                        f"✓ OCR error heal: page_{scan_page:04d} "
                        f"({prev_val} -> [{current['detected']}→{expected}] -> {next_val})"
                    )

                    patch = {
                        "scan_page": scan_page,
                        "page_number": {
                            "present": True,
                            "number": str(expected),
                            "location": "margin",
                            "confidence": "high",
                            "source_provider": "gap_healing_simple"
                        }
                    }

                    _save_patch(tracker, scan_page, patch)
                    current["detected"] = expected
                    ocr_error_healed += 1

        i += 1

    total_healed = trivial_healed + ocr_error_healed
    tracker.logger.info(
        f"Gap healing complete: {total_healed} pages healed "
        f"({trivial_healed} gap_1, {ocr_error_healed} OCR errors)"
    )

    if complex_gaps:
        tracker.logger.warning(f"Found {len(complex_gaps)} complex gaps requiring review:")
        for gap in complex_gaps[:10]:
            tracker.logger.warning(
                f"  page_{gap['scan_page']:04d}: "
                f"{gap['prev']} -> [?] -> {gap['next']} ({gap['type']})"
            )
        if len(complex_gaps) > 10:
            tracker.logger.warning(f"  ... and {len(complex_gaps) - 10} more")

    summary = {
        "trivial_healed": trivial_healed,
        "ocr_error_healed": ocr_error_healed,
        "total_healed": total_healed,
        "complex_gaps": len(complex_gaps),
        "complex_gap_details": complex_gaps
    }

    summary_path = tracker.phase_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    return summary
