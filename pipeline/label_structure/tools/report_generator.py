import csv
import re

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def parse_page_number(page_num_str: str) -> tuple[str, int | None]:
    """Parse page number string into type and numeric value.

    Returns:
        (type, value) where type is 'roman', 'arabic', or 'other'
        value is numeric equivalent (None if unparseable)
    """
    if not page_num_str or not page_num_str.strip():
        return ('none', None)

    cleaned = page_num_str.strip().lower()

    # Roman numerals (common in front matter)
    roman_pattern = r'^[ivxlcdm]+$'
    if re.match(roman_pattern, cleaned):
        # Convert roman to arabic for comparison
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

    # Arabic numerals
    arabic_pattern = r'^(\d+)$'
    match = re.match(arabic_pattern, cleaned)
    if match:
        return ('arabic', int(match.group(1)))

    # Mixed or other formats (e.g., "3o" instead of "30")
    return ('other', None)


def calculate_sequence_validation(report_rows: list[dict]) -> list[dict]:
    """Calculate sequence validation metrics for all pages.

    Adds sequence_status, sequence_gap, expected_value, needs_review to each row.
    """
    prev_type = None
    prev_value = None

    for i, row in enumerate(report_rows):
        page_num_str = row['page_num_value']
        curr_type, curr_value = parse_page_number(page_num_str)

        # Default values
        row['sequence_status'] = 'unknown'
        row['sequence_gap'] = 0
        row['expected_value'] = ''
        row['needs_review'] = False

        # No page number on this page
        if curr_type == 'none':
            row['sequence_status'] = 'no_number'
            row['sequence_gap'] = 0
            row['expected_value'] = ''
            row['needs_review'] = False
            continue

        # Unparseable page number
        if curr_value is None:
            row['sequence_status'] = 'unparseable'
            row['sequence_gap'] = 0
            row['expected_value'] = ''
            row['needs_review'] = True
            continue

        # First page with a number
        if prev_value is None:
            row['sequence_status'] = 'first_page'
            row['sequence_gap'] = 0
            row['expected_value'] = ''
            row['needs_review'] = False
            prev_type = curr_type
            prev_value = curr_value
            continue

        # Type changed (e.g., roman → arabic at chapter 1)
        if curr_type != prev_type:
            row['sequence_status'] = 'type_change'
            row['sequence_gap'] = 0
            row['expected_value'] = f'{prev_value + 1} ({prev_type})'
            row['needs_review'] = False
            prev_type = curr_type
            prev_value = curr_value
            continue

        # Calculate gap
        gap = curr_value - prev_value
        row['sequence_gap'] = gap
        row['expected_value'] = str(prev_value + 1)

        # Validate sequence
        if gap < 0:
            # Backward jump - definite error
            row['sequence_status'] = 'backward_jump'
            row['needs_review'] = True
        elif gap == 1:
            # Perfect sequence
            row['sequence_status'] = 'ok'
            row['needs_review'] = False
        elif gap == 2:
            # Gap of 1 (one missing page, likely blank)
            row['sequence_status'] = 'gap_1'
            row['needs_review'] = False
        elif gap == 3:
            # Gap of 2 (two missing pages, could be blank spread)
            row['sequence_status'] = 'gap_2'
            row['needs_review'] = False
        else:
            # Gap of 3+ (suspicious)
            row['sequence_status'] = f'gap_{gap-1}'
            row['needs_review'] = True

        prev_type = curr_type
        prev_value = curr_value

    return report_rows


def generate_report(
    storage: BookStorage,
    logger: PipelineLogger,
    report_schema,
    stage_name: str,
):
    logger.info("Generating report.csv from page outputs")

    stage_storage = storage.stage(stage_name)

    page_nums = stage_storage.list_pages(extension='json')

    if not page_nums:
        logger.warning("No completed pages found")
        return

    report_rows = []
    for page_num in page_nums:
        try:
            page_data = stage_storage.load_page(page_num)
            if not page_data:
                continue

            # Extract observations from merged schema
            header = page_data.get('header', {})
            footer = page_data.get('footer', {})
            page_number = page_data.get('page_number', {})

            # Headings are now directly in page_data (from Pass 1)
            headings_present = page_data.get('headings_present', False)
            heading_items = page_data.get('headings', [])

            # Format headings for CSV
            headings_text = '|'.join(h.get('text', '') for h in heading_items) if heading_items else ''
            headings_levels = '|'.join(str(h.get('level', '')) for h in heading_items) if heading_items else ''

            report_row = report_schema(
                page_num=page_num,

                # Header
                header_present=header.get('present', False),
                header_text=header.get('text', '') or '',
                header_conf=header.get('confidence', 'low'),
                header_source=header.get('source_provider', ''),

                # Footer
                footer_present=footer.get('present', False),
                footer_text=footer.get('text', '') or '',
                footer_conf=footer.get('confidence', 'low'),
                footer_source=footer.get('source_provider', ''),

                # Page number
                page_num_present=page_number.get('present', False),
                page_num_value=page_number.get('number', '') or '',
                page_num_location=page_number.get('location', '') or '',
                page_num_conf=page_number.get('confidence', 'low'),
                page_num_source=page_number.get('source_provider', ''),

                # Headings (from Pass 1 mechanical extraction)
                headings_present=headings_present,
                headings_count=len(heading_items),
                headings_text=headings_text,
                headings_levels=headings_levels,
                headings_conf='high',  # Mechanical extraction is always high confidence
                headings_source='mistral-markdown',  # From Pass 1
            )
            report_rows.append(report_row.model_dump())
        except Exception as e:
            logger.warning(f"Failed to process page {page_num}", error=str(e))
            continue

    if not report_rows:
        logger.warning("No valid pages to write to report")
        return

    # Calculate sequence validation metrics
    report_rows = calculate_sequence_validation(report_rows)

    # Log validation summary
    status_counts = {}
    for row in report_rows:
        status = row.get('sequence_status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1

    needs_review_count = sum(1 for row in report_rows if row.get('needs_review', False))

    logger.info(f"Sequence validation: {needs_review_count} pages need review")
    for status, count in sorted(status_counts.items()):
        logger.info(f"  {status}: {count} pages")

    report_path = stage_storage.output_dir / "report.csv"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w', newline='') as f:
        fieldnames = list(report_rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    logger.info(f"Report written: {report_path} ({len(report_rows)} pages)")
