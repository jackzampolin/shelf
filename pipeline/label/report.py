#!/usr/bin/env python3
"""
Label Stage Reporting

View label stage outputs as a clean table.

Usage:
    python pipeline/3_label/report.py <scan-id> [--json]

Displays:
- PDF page number (file number)
- Page region (front_matter, body, back_matter, toc_area, uncertain)
- Printed page number (roman numerals, arabic, or null)
- Has images (ILLUSTRATION_CAPTION, TABLE, MAP_LABEL, DIAGRAM_LABEL blocks)
"""

import json
import sys
import csv
from pathlib import Path
from collections import Counter


def has_image_content(label_data):
    """Check if page has image-related blocks."""
    image_types = {'ILLUSTRATION_CAPTION', 'TABLE', 'MAP_LABEL', 'DIAGRAM_LABEL', 'PHOTO_CREDIT'}
    for block in label_data.get('blocks', []):
        if block.get('classification') in image_types:
            return True
    return False


def format_report(scan_id, rows, region_counts):
    """Format label report as string."""
    lines = []

    lines.append(f"\n📊 Label Stage Output: {scan_id}")
    lines.append(f"   Total pages: {len(rows)}\n")

    # Header
    lines.append(f"{'PDF':>4} {'Region':>15} {'Conf':>5} {'Printed':>8} {'Img':>4}")
    lines.append("─" * 42)

    # Rows
    for row in rows:
        region_display = row['region'][:15]  # Truncate long names
        conf_display = f"{row['region_conf']:.2f}" if row['region_conf'] else "-"

        lines.append(
            f"{row['pdf_page']:>4} "
            f"{region_display:>15} "
            f"{conf_display:>5} "
            f"{str(row['printed_page']):>8} "
            f"{row['has_image']:>4}"
        )

    # Summary
    lines.append("\n" + "─" * 42)
    lines.append("Region Distribution:")
    for region, count in sorted(region_counts.items()):
        pct = (count / len(rows)) * 100
        lines.append(f"  {region:>15}: {count:>4} ({pct:>5.1f}%)")
    lines.append("")

    return "\n".join(lines)


def analyze_book(scan_id, output_json=False, storage_root=None, save_csv=True, silent=False, write_report=True):
    """
    Analyze label outputs and optionally save as CSV.

    Args:
        scan_id: Book scan identifier
        output_json: Output JSON to stdout instead of table
        storage_root: Storage root path
        save_csv: Save report as CSV file in labels directory (default: True)
        silent: If True, suppress terminal output
        write_report: If True, write report.txt to labels folder (default: True)

    Returns:
        Path to saved CSV file if save_csv=True, otherwise None
    """
    if storage_root is None:
        storage_root = Path("~/Documents/book_scans").expanduser()
    else:
        storage_root = Path(storage_root)

    book_dir = storage_root / scan_id
    label_dir = book_dir / "labels"

    if not label_dir.exists():
        if not silent:
            print(f"❌ No label output found for {scan_id}")
        return None

    label_files = sorted(label_dir.glob("page_*.json"))

    if not label_files:
        if not silent:
            print(f"❌ No labeled pages found in {label_dir}")
        return None

    # Collect data
    rows = []
    region_counts = Counter()

    for label_file in label_files:
        pdf_page = int(label_file.stem.split('_')[1])

        with open(label_file, 'r') as f:
            label_data = json.load(f)

        printed_num = label_data.get('printed_page_number') or '-'
        region = label_data.get('page_region') or 'unknown'
        region_conf = label_data.get('page_region_confidence', 0.0)
        has_image = '✓' if has_image_content(label_data) else ''

        region_counts[region] += 1

        rows.append({
            'pdf_page': pdf_page,
            'region': region,
            'region_conf': region_conf,
            'printed_page': printed_num,
            'has_image': has_image
        })

    # Write CSV report if requested
    csv_path = None
    if save_csv or write_report:
        csv_path = label_dir / "report.csv"

        with open(csv_path, 'w', newline='') as csvfile:
            fieldnames = ['pdf_page', 'region', 'region_conf', 'printed_page', 'has_image']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    # Output to terminal if not silent
    if not silent:
        if output_json:
            print(json.dumps(rows, indent=2))
        else:
            report_text = format_report(scan_id, rows, region_counts)
            print(report_text)

    return csv_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline/label/report.py <scan-id> [--json]")
        sys.exit(1)

    scan_id = sys.argv[1]
    output_json = '--json' in sys.argv

    analyze_book(scan_id, output_json=output_json)
