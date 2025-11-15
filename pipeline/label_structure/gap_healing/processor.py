import re
from infra.pipeline.status import PhaseStatusTracker
from ..schemas.merged_output import LabelStructurePageOutput
from ..schemas.structure import PageNumberObservation


def is_roman_numeral(value: str) -> bool:
    """Check if a string is a roman numeral."""
    if not value:
        return False
    return bool(re.match(r'^[IVXLCDMivxlcdm]+$', value.strip()))


def get_arabic_value(page_data: dict) -> int | None:
    """
    Extract arabic numeral value from page data.
    Returns None if roman numeral, missing, or invalid.
    """
    detected = page_data.get("detected")
    if detected is None:
        return None

    # Check if it's stored as int (already parsed)
    if isinstance(detected, int):
        return detected

    # Check if it's a string that could be roman
    if isinstance(detected, str):
        if is_roman_numeral(detected):
            return None
        try:
            return int(detected)
        except ValueError:
            return None

    return None


def heal_page_number_gaps(
    tracker: PhaseStatusTracker,
    **kwargs
) -> dict:
    """Simple gap healing using sequence analysis.

    Args:
        tracker: PhaseStatusTracker providing access to storage, logger, status
        **kwargs: Optional configuration (unused for this phase)
    """
    tracker.logger.info("=== Gap Healing: Analyzing page numbers ===")

    stage_storage = tracker.storage.stage("label-structure")
    source_pages = tracker.storage.stage("source").list_pages(extension="png")
    total_pages = len(source_pages)

    sequence = []
    for page_num in range(1, total_pages + 1):
        try:
            data = stage_storage.load_file(f"page_{page_num:04d}.json")
            output = LabelStructurePageOutput(**data)

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
            tracker.logger.error(f"Failed to load page_{page_num:04d}: {e}")
            sequence.append({
                "scan_page": page_num,
                "detected": None,
                "detected_raw": None,
                "output": None
            })

    trivial_healed = 0
    ocr_error_healed = 0
    complex_gaps = []

    i = 0
    while i < len(sequence):
        current = sequence[i]

        # Case 1: Missing page number - check for N-page gaps
        if current["detected"] is None:
            # Find the previous valid arabic page number
            prev_val = None
            for j in range(i - 1, -1, -1):
                prev_val = get_arabic_value(sequence[j])
                if prev_val is not None:
                    break

            # Find the next valid arabic page number (skip all missing pages)
            next_val = None
            next_idx = None
            for j in range(i + 1, len(sequence)):
                next_val = get_arabic_value(sequence[j])
                if next_val is not None:
                    next_idx = j
                    break

            if prev_val is not None and next_val is not None:
                # Calculate expected gap size
                expected_gap_size = next_val - prev_val - 1
                # Count actual missing pages
                actual_gap_size = next_idx - i

                # Check if all pages in the gap are missing
                all_missing = all(
                    sequence[k]["detected"] is None
                    for k in range(i, next_idx)
                )

                if all_missing and expected_gap_size == actual_gap_size and expected_gap_size > 0:
                    # Heal the entire gap
                    gap_type = f"gap_{expected_gap_size}"
                    tracker.logger.info(
                        f"✓ {gap_type} heal: pages {sequence[i]['scan_page']:04d}-{sequence[next_idx-1]['scan_page']:04d} "
                        f"({prev_val} -> [{prev_val + 1}...{next_val - 1}] -> {next_val})"
                    )

                    for offset in range(expected_gap_size):
                        gap_page_idx = i + offset
                        expected = prev_val + 1 + offset

                        sequence[gap_page_idx]["output"].page_number = PageNumberObservation(
                            present=True,
                            number=str(expected),
                            location="margin",
                            confidence="high",
                            source_provider="paddle"
                        )

                        stage_storage.save_file(
                            f"page_{sequence[gap_page_idx]['scan_page']:04d}.json",
                            sequence[gap_page_idx]["output"].model_dump(),
                            schema=LabelStructurePageOutput
                        )

                        sequence[gap_page_idx]["detected"] = expected
                        trivial_healed += 1

                    # Skip past all the pages we just healed
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

        # Case 2: Roman numeral detected (possible OCR error in arabic sequence)
        elif isinstance(current["detected"], str) and is_roman_numeral(current["detected"]):
            # Get arabic values from adjacent pages
            prev_val = get_arabic_value(sequence[i-1]) if i > 0 else None
            next_val = get_arabic_value(sequence[i+1]) if i < len(sequence) - 1 else None

            # Check if we're in the middle of an arabic sequence
            if prev_val is not None and next_val is not None:
                if next_val == prev_val + 2:
                    expected = prev_val + 1
                    tracker.logger.info(
                        f"✓ OCR error heal: page_{current['scan_page']:04d} "
                        f"({prev_val} -> [{current['detected']}→{expected}] -> {next_val})"
                    )

                    current["output"].page_number = PageNumberObservation(
                        present=True,
                        number=str(expected),
                        location="margin",
                        confidence="high",
                        source_provider="paddle"
                    )

                    stage_storage.save_file(
                        f"page_{current['scan_page']:04d}.json",
                        current["output"].model_dump(),
                        schema=LabelStructurePageOutput
                    )

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

    return {
        "trivial_healed": trivial_healed,
        "ocr_error_healed": ocr_error_healed,
        "total_healed": total_healed,
        "complex_gaps": len(complex_gaps),
        "complex_gap_details": complex_gaps
    }
