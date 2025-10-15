#!/usr/bin/env python3
"""
Analyze label stage outputs for quality and common issues.

Usage:
    python tools/analyze_label.py <scan-id> [--pages N]

Analyzes:
- Page number extraction accuracy (compare to expected page numbers)
- Block classification distribution (BODY, FOOTNOTE, QUOTE, etc.)
- OTHER usage rate (goal: <2%, currently ~4%)
- QUOTE detection quality (goal: >0.90 confidence, currently 0.86)
- Classification confidence distribution
- Common failure patterns
"""

import json
import sys
from pathlib import Path
from collections import defaultdict, Counter


def load_page_data(scan_id, page_num, storage_root):
    """Load OCR input and label output for a page."""
    book_dir = storage_root / scan_id

    # Load OCR input
    ocr_file = book_dir / "ocr" / f"page_{page_num:04d}.json"
    if not ocr_file.exists():
        return None, None

    with open(ocr_file, 'r') as f:
        ocr_data = json.load(f)

    # Load label output
    label_file = book_dir / "labels" / f"page_{page_num:04d}.json"
    if not label_file.exists():
        # Try old "3_labeled" directory
        label_file = book_dir / "3_labeled" / f"page_{page_num:04d}.json"

    if not label_file.exists():
        return ocr_data, None

    with open(label_file, 'r') as f:
        label_data = json.load(f)

    return ocr_data, label_data


def analyze_page_number(label_data, page_num):
    """Analyze page number extraction for a single page."""
    issues = []

    printed_num = label_data.get('printed_page_number')
    numbering_style = label_data.get('numbering_style', 'none')
    location = label_data.get('page_number_location', 'none')
    confidence = label_data.get('page_number_confidence', 1.0)

    # For now, we can't easily validate if the extracted page number is "correct"
    # since we don't have ground truth. But we can flag suspicious patterns:

    # Issue 1: High confidence but null page number (might be wrong)
    if printed_num is None and confidence > 0.95:
        issues.append({
            'type': 'high_confidence_null',
            'severity': 'low',
            'description': f'No page number found with high confidence ({confidence:.2f})',
            'page_number_confidence': confidence
        })

    # Issue 2: Low confidence extraction (unreliable)
    if printed_num is not None and confidence < 0.80:
        issues.append({
            'type': 'low_confidence_extraction',
            'severity': 'medium',
            'description': f'Page number "{printed_num}" extracted with low confidence ({confidence:.2f})',
            'printed_page_number': printed_num,
            'confidence': confidence
        })

    # Issue 3: Numbering style mismatch (e.g., says "roman" but printed_num is "123")
    if printed_num is not None and numbering_style == 'roman':
        # Check if it actually looks like a roman numeral
        roman_chars = set('ivxlcdmIVXLCDM')
        if not all(c in roman_chars for c in printed_num.strip()):
            issues.append({
                'type': 'style_mismatch',
                'severity': 'high',
                'description': f'Marked as roman but printed_num is "{printed_num}"',
                'printed_page_number': printed_num,
                'numbering_style': numbering_style
            })
    elif printed_num is not None and numbering_style == 'arabic':
        # Check if it actually looks like a number
        if not printed_num.strip().isdigit():
            issues.append({
                'type': 'style_mismatch',
                'severity': 'high',
                'description': f'Marked as arabic but printed_num is "{printed_num}"',
                'printed_page_number': printed_num,
                'numbering_style': numbering_style
            })

    return issues, printed_num, numbering_style, location, confidence


def analyze_block(block):
    """Analyze a single block for classification issues."""
    issues = []

    classification = block.get('classification', 'OTHER')
    confidence = block.get('classification_confidence', 0.5)
    block_num = block.get('block_num', 0)

    # Issue 1: OTHER usage (should be <2% overall)
    if classification == 'OTHER':
        issues.append({
            'type': 'other_usage',
            'severity': 'medium',
            'description': f'Block classified as OTHER (target: <2% usage)',
            'confidence': confidence
        })

    # Issue 2: Low confidence classification
    if confidence < 0.70:
        issues.append({
            'type': 'low_confidence_classification',
            'severity': 'high',
            'description': f'Block classified as {classification} with low confidence ({confidence:.2f})',
            'classification': classification,
            'confidence': confidence
        })

    # Issue 3: QUOTE with low confidence (currently under-detected at 0.86)
    if classification == 'QUOTE' and confidence < 0.85:
        issues.append({
            'type': 'low_confidence_quote',
            'severity': 'medium',
            'description': f'QUOTE block with low confidence ({confidence:.2f}) - may be misclassified',
            'confidence': confidence
        })

    # Issue 4: Very high confidence might indicate overconfidence
    if confidence > 0.99 and classification not in ['BODY', 'CHAPTER_HEADING']:
        issues.append({
            'type': 'overconfident_classification',
            'severity': 'low',
            'description': f'{classification} with very high confidence ({confidence:.2f}) - might be overconfident',
            'classification': classification,
            'confidence': confidence
        })

    return issues, classification, confidence


def analyze_book(scan_id, max_pages=None, storage_root=None):
    """Analyze label outputs for a book."""
    if storage_root is None:
        storage_root = Path("~/Documents/book_scans").expanduser()
    else:
        storage_root = Path(storage_root)

    book_dir = storage_root / scan_id

    # Find all labeled pages
    label_dir = book_dir / "labels"
    if not label_dir.exists():
        label_dir = book_dir / "3_labeled"

    if not label_dir.exists():
        print(f"❌ No label output found for {scan_id}")
        return

    label_files = sorted(label_dir.glob("page_*.json"))
    if max_pages:
        label_files = label_files[:max_pages]

    print(f"\n📊 Analyzing Label Stage: {scan_id}")
    print(f"   Pages to analyze: {len(label_files)}")
    print()

    # Statistics
    stats = {
        'total_pages': len(label_files),
        'total_blocks': 0,
        'page_numbers_extracted': 0,
        'page_numbers_null': 0,
        'page_number_confidences': [],
        'classification_counts': Counter(),
        'classification_confidences': defaultdict(list),
        'avg_classification_confidence': [],
        'issues_by_type': Counter()
    }

    all_issues = []

    # Analyze each page
    for label_file in label_files:
        page_num = int(label_file.stem.split('_')[1])

        ocr_data, label_data = load_page_data(scan_id, page_num, storage_root)
        if not label_data:
            continue

        # Analyze page number extraction
        pn_issues, printed_num, numbering_style, location, pn_confidence = analyze_page_number(label_data, page_num)

        if printed_num is not None:
            stats['page_numbers_extracted'] += 1
        else:
            stats['page_numbers_null'] += 1

        stats['page_number_confidences'].append(pn_confidence)

        for issue in pn_issues:
            stats['issues_by_type'][issue['type']] += 1
            all_issues.append({
                **issue,
                'page': page_num
            })

        # Analyze block classifications
        for block in label_data.get('blocks', []):
            stats['total_blocks'] += 1

            block_issues, classification, confidence = analyze_block(block)

            stats['classification_counts'][classification] += 1
            stats['classification_confidences'][classification].append(confidence)
            stats['avg_classification_confidence'].append(confidence)

            for issue in block_issues:
                stats['issues_by_type'][issue['type']] += 1
                all_issues.append({
                    **issue,
                    'page': page_num,
                    'block': block.get('block_num', 0)
                })

    # Print summary
    print("=" * 70)
    print("SUMMARY STATISTICS")
    print("=" * 70)
    print()

    print(f"📄 Total Pages:  {stats['total_pages']}")
    print(f"📦 Total Blocks: {stats['total_blocks']}")
    print()

    # Page number analysis
    print("━" * 70)
    print("PAGE NUMBER EXTRACTION")
    print("━" * 70)
    total_pages = stats['total_pages']
    if total_pages > 0:
        extracted_pct = (stats['page_numbers_extracted'] / total_pages) * 100
        null_pct = (stats['page_numbers_null'] / total_pages) * 100

        print(f"Pages with extracted numbers: {stats['page_numbers_extracted']:4d} ({extracted_pct:5.1f}%)")
        print(f"Pages with null (unnumbered): {stats['page_numbers_null']:4d} ({null_pct:5.1f}%)")

        if stats['page_number_confidences']:
            avg_conf = sum(stats['page_number_confidences']) / len(stats['page_number_confidences'])
            high_conf = sum(1 for c in stats['page_number_confidences'] if c >= 0.95) / len(stats['page_number_confidences']) * 100
            med_conf = sum(1 for c in stats['page_number_confidences'] if 0.85 <= c < 0.95) / len(stats['page_number_confidences']) * 100
            low_conf = sum(1 for c in stats['page_number_confidences'] if c < 0.85) / len(stats['page_number_confidences']) * 100

            print(f"\nPage number confidence:")
            print(f"  Average: {avg_conf:.3f}")
            print(f"  0.95-1.0 (high):    {high_conf:5.1f}%")
            print(f"  0.85-0.94 (medium): {med_conf:5.1f}%")
            print(f"  <0.85 (low):        {low_conf:5.1f}%")

            if low_conf > 10:
                print(f"\n⚠️  WARNING: {low_conf:.1f}% of page extractions have low confidence")
    print()

    # Block classification distribution
    print("━" * 70)
    print("BLOCK CLASSIFICATION DISTRIBUTION")
    print("━" * 70)
    if stats['classification_counts']:
        print(f"{'Classification':<25s} {'Count':>8s} {'%':>7s} {'Avg Conf':>10s}")
        print("─" * 70)

        total_blocks = stats['total_blocks']
        for classification, count in stats['classification_counts'].most_common():
            pct = (count / total_blocks) * 100
            avg_conf = sum(stats['classification_confidences'][classification]) / len(stats['classification_confidences'][classification])
            print(f"{classification:<25s} {count:>8d} {pct:>6.1f}% {avg_conf:>10.3f}")

        print()

        # Highlight key metrics
        other_count = stats['classification_counts'].get('OTHER', 0)
        other_pct = (other_count / total_blocks) * 100

        if other_pct > 2.0:
            print(f"⚠️  OTHER usage: {other_pct:.1f}% (target: <2%)")
        else:
            print(f"✅ OTHER usage: {other_pct:.1f}% (within target)")

        # QUOTE detection quality
        quote_confs = stats['classification_confidences'].get('QUOTE', [])
        if quote_confs:
            avg_quote_conf = sum(quote_confs) / len(quote_confs)
            print(f"{'✅' if avg_quote_conf >= 0.90 else '⚠️ '} QUOTE avg confidence: {avg_quote_conf:.3f} (target: >0.90)")

    print()

    # Overall classification confidence
    print("━" * 70)
    print("CLASSIFICATION CONFIDENCE")
    print("━" * 70)
    if stats['avg_classification_confidence']:
        confs = stats['avg_classification_confidence']
        avg_conf = sum(confs) / len(confs)
        high_conf = sum(1 for c in confs if c >= 0.95) / len(confs) * 100
        med_conf = sum(1 for c in confs if 0.85 <= c < 0.95) / len(confs) * 100
        low_conf = sum(1 for c in confs if c < 0.85) / len(confs) * 100

        print(f"Average confidence: {avg_conf:.3f}")
        print(f"  0.95-1.0 (high):    {high_conf:5.1f}%")
        print(f"  0.85-0.94 (medium): {med_conf:5.1f}%")
        print(f"  <0.85 (low):        {low_conf:5.1f}%")

        if high_conf > 90:
            print(f"\n⚠️  WARNING: {high_conf:.1f}% of blocks have 0.95+ confidence (might be overconfident)")
        if low_conf > 5:
            print(f"\n⚠️  WARNING: {low_conf:.1f}% of blocks have <0.85 confidence (uncertain classifications)")
    print()

    # Issues summary
    print("━" * 70)
    print("ISSUES FOUND")
    print("━" * 70)
    if stats['issues_by_type']:
        for issue_type, count in stats['issues_by_type'].most_common():
            print(f"  {issue_type:35s}: {count:4d}")
    else:
        print("  ✅ No issues found!")
    print()

    # Show examples of top issues
    if all_issues:
        print("=" * 70)
        print("EXAMPLE ISSUES (First 10)")
        print("=" * 70)
        print()

        for i, issue in enumerate(all_issues[:10], 1):
            print(f"Issue {i}: {issue['type']}")
            location = f"Page {issue['page']}"
            if 'block' in issue:
                location += f", Block {issue['block']}"
            print(f"  {location}")
            print(f"  Severity: {issue['severity']}")
            print(f"  {issue['description']}")
            if 'classification' in issue:
                print(f"  Classification: {issue['classification']}")
            if 'confidence' in issue:
                print(f"  Confidence: {issue['confidence']:.3f}")
            print()

    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/analyze_label.py <scan-id> [--pages N]")
        sys.exit(1)

    scan_id = sys.argv[1]
    max_pages = None

    if len(sys.argv) > 2 and sys.argv[2] == "--pages":
        max_pages = int(sys.argv[3])

    analyze_book(scan_id, max_pages=max_pages)
