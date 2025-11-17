import csv
import json
import re
from typing import Callable
from pathlib import Path

from infra.pipeline.storage.book_storage import BookStorage
from ..schemas import LabelStructurePageReport, LabelStructurePageOutput


def parse_page_number(page_num_str: str) -> tuple[str, int | None]:
    if not page_num_str or not page_num_str.strip():
        return ('none', None)

    cleaned = page_num_str.strip().lower()

    roman_pattern = r'^[ivxlcdm]+$'
    if re.match(roman_pattern, cleaned):
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

    arabic_pattern = r'^(\d+)$'
    match = re.match(arabic_pattern, cleaned)
    if match:
        return ('arabic', int(match.group(1)))

    return ('other', None)


def calculate_sequence_validation(report_rows: list[dict]) -> list[dict]:
    prev_type = None
    prev_value = None

    for i, row in enumerate(report_rows):
        page_num_str = row['page_num_value']
        curr_type, curr_value = parse_page_number(page_num_str)

        row['sequence_status'] = 'unknown'
        row['sequence_gap'] = 0
        row['expected_value'] = ''
        row['needs_review'] = False

        if curr_type == 'none':
            row['sequence_status'] = 'no_number'
            row['sequence_gap'] = 0
            row['expected_value'] = ''
            row['needs_review'] = False
            continue

        if curr_value is None:
            row['sequence_status'] = 'unparseable'
            row['sequence_gap'] = 0
            row['expected_value'] = ''
            row['needs_review'] = True
            continue

        if prev_value is None:
            row['sequence_status'] = 'first_page'
            row['sequence_gap'] = 0
            row['expected_value'] = ''
            row['needs_review'] = False
            prev_type = curr_type
            prev_value = curr_value
            continue

        if curr_type != prev_type:
            row['sequence_status'] = 'type_change'
            row['sequence_gap'] = 0
            row['expected_value'] = f'{prev_value + 1} ({prev_type})'
            row['needs_review'] = False
            prev_type = curr_type
            prev_value = curr_value
            continue

        gap = curr_value - prev_value
        row['sequence_gap'] = gap
        row['expected_value'] = str(prev_value + 1)

        if gap < 0:
            row['sequence_status'] = 'backward_jump'
            row['needs_review'] = True
        elif gap == 1:
            row['sequence_status'] = 'ok'
            row['needs_review'] = False
        elif gap == 2:
            row['sequence_status'] = 'gap_1'
            row['needs_review'] = False
        elif gap == 3:
            row['sequence_status'] = 'gap_2'
            row['needs_review'] = False
        else:
            row['sequence_status'] = f'gap_{gap-1}'
            row['needs_review'] = True

        prev_type = curr_type
        prev_value = curr_value

    return report_rows


def generate_report_for_stage(
    storage: BookStorage,
    output_path: Path,
    merge_fn: Callable[[BookStorage, int], LabelStructurePageOutput],
    logger,
    stage_name: str
):
    logger.info(f"Generating report.csv for {stage_name}")

    source_pages = storage.stage("source").list_pages(extension="png")

    if not source_pages:
        logger.warning("No source pages found")
        return

    report_rows = []
    failed_pages = []

    for page_num in source_pages:
        try:
            page_output = merge_fn(storage, page_num)
            page_data = page_output.model_dump()

            header = page_data.get('header', {})
            footer = page_data.get('footer', {})
            page_number = page_data.get('page_number', {})

            headings_present = page_data.get('headings_present', False)
            heading_items = page_data.get('headings', [])

            headings_text = '|'.join(h.get('text', '') for h in heading_items) if heading_items else ''
            headings_levels = '|'.join(str(h.get('level', '')) for h in heading_items) if heading_items else ''

            report_row = LabelStructurePageReport(
                page_num=page_num,
                header_present=header.get('present', False),
                header_text=header.get('text', '') or '',
                header_conf=header.get('confidence', 'low'),
                header_source=header.get('source_provider', ''),
                footer_present=footer.get('present', False),
                footer_text=footer.get('text', '') or '',
                footer_conf=footer.get('confidence', 'low'),
                footer_source=footer.get('source_provider', ''),
                page_num_present=page_number.get('present', False),
                page_num_value=page_number.get('number', '') or '',
                page_num_location=page_number.get('location', '') or '',
                page_num_conf=page_number.get('confidence', 'low'),
                page_num_source=page_number.get('source_provider', ''),
                headings_present=headings_present,
                headings_count=len(heading_items),
                headings_text=headings_text,
                headings_levels=headings_levels,
                headings_conf='high',
                headings_source='mistral-markdown',
            )
            report_rows.append(report_row.model_dump())
        except Exception as e:
            logger.error(
                f"Failed to generate report for page {page_num}",
                page_num=page_num,
                error=str(e),
                error_type=type(e).__name__
            )
            failed_pages.append({"page": page_num, "error": str(e), "error_type": type(e).__name__})

    if failed_pages:
        error_report_path = output_path.parent / f"{output_path.stem}_errors.json"
        error_report_path.write_text(json.dumps(failed_pages, indent=2))
        logger.warning(f"{len(failed_pages)} pages failed report generation - see {error_report_path}")

        if len(failed_pages) == len(source_pages):
            raise ValueError(f"Report generation completely failed - all {len(source_pages)} pages failed")

    if not report_rows:
        logger.warning("No valid pages to write to report")
        return

    report_rows = calculate_sequence_validation(report_rows)

    status_counts = {}
    for row in report_rows:
        status = row.get('sequence_status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1

    needs_review_count = sum(1 for row in report_rows if row.get('needs_review', False))

    logger.info(f"{stage_name} - Sequence validation: {needs_review_count} pages need review")
    for status, count in sorted(status_counts.items()):
        logger.info(f"  {status}: {count} pages")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', newline='') as f:
        fieldnames = list(report_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    logger.info(f"{stage_name} - Report written: {output_path} ({len(report_rows)} pages)")
