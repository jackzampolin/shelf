#!/usr/bin/env python3
"""
Analyze correction stage outputs for quality and common issues.

Usage:
    python tools/analyze_correction.py <scan-id> [--pages N]

Analyzes:
- Correction application rate (notes say fixed, text actually changed)
- Null text accuracy (notes say "No OCR errors", text is null)
- Note length distribution and verbosity issues
- Confidence score distribution
- Common failure patterns
"""

import json
import sys
from pathlib import Path
from collections import defaultdict, Counter


def load_page_data(scan_id, page_num, storage_root):
    """Load OCR input and corrected output for a page."""
    book_dir = storage_root / scan_id

    # Load OCR input
    ocr_file = book_dir / "ocr" / f"page_{page_num:04d}.json"
    if not ocr_file.exists():
        return None, None

    with open(ocr_file, 'r') as f:
        ocr_data = json.load(f)

    # Load corrected output
    corrected_file = book_dir / "2_corrected" / f"page_{page_num:04d}.json"
    if not corrected_file.exists():
        corrected_file = book_dir / "corrected" / f"page_{page_num:04d}.json"

    if not corrected_file.exists():
        return ocr_data, None

    with open(corrected_file, 'r') as f:
        corrected_data = json.load(f)

    return ocr_data, corrected_data


def analyze_paragraph(ocr_para, corr_para):
    """Analyze a single paragraph for issues."""
    issues = []

    ocr_text = ocr_para['text']
    corr_text = corr_para.get('text')
    notes = corr_para.get('notes', '')
    confidence = corr_para.get('confidence', 1.0)

    # Issue 1: Notes say "No OCR errors" but text is not null
    if notes == "No OCR errors detected":
        if corr_text is not None:
            issues.append({
                'type': 'null_text_violation',
                'severity': 'high',
                'description': 'Notes say "No OCR errors" but text is not null',
                'text_length': len(corr_text)
            })
        return issues, notes, confidence, (corr_text is None)

    # Issue 2: Notes describe corrections but text unchanged
    correction_keywords = ['Fixed', 'Removed', 'Corrected', 'Normalized']
    describes_correction = any(kw in notes for kw in correction_keywords)

    if describes_correction:
        if corr_text is None:
            issues.append({
                'type': 'correction_documented_but_null',
                'severity': 'critical',
                'description': 'Notes describe corrections but text is null',
                'notes': notes[:100]
            })
        elif corr_text == ocr_text:
            issues.append({
                'type': 'correction_not_applied',
                'severity': 'critical',
                'description': 'Notes describe corrections but text unchanged from OCR',
                'notes': notes[:100]
            })
        else:
            # Text changed - check if it's actually different
            if corr_text.replace(' ', '').replace('-', '') == ocr_text.replace(' ', '').replace('-', ''):
                issues.append({
                    'type': 'superficial_change',
                    'severity': 'medium',
                    'description': 'Text changed but only whitespace/hyphens',
                    'notes': notes[:100]
                })

    # Issue 3: Verbose/rambling notes
    if len(notes) > 300:
        issues.append({
            'type': 'verbose_notes',
            'severity': 'medium',
            'description': f'Notes are {len(notes)} chars (too verbose)',
            'notes_preview': notes[:150]
        })

    # Issue 4: Circular corrections (Fixed X to X)
    import re
    same_fix = re.findall(r"['\"]([^'\"]+)['\"]\\s+to\\s+['\"](\1)['\"]", notes)
    if same_fix:
        issues.append({
            'type': 'circular_correction',
            'severity': 'high',
            'description': f'Notes describe circular correction: {same_fix[0][0]} → {same_fix[0][0]}',
            'notes': notes[:100]
        })

    return issues, notes, confidence, (corr_text != ocr_text if corr_text else False)


def analyze_book(scan_id, max_pages=None, storage_root=None):
    """Analyze correction outputs for a book."""
    if storage_root is None:
        storage_root = Path("~/Documents/book_scans").expanduser()
    else:
        storage_root = Path(storage_root)

    book_dir = storage_root / scan_id

    # Find all corrected pages
    corrected_dir = book_dir / "2_corrected"
    if not corrected_dir.exists():
        corrected_dir = book_dir / "corrected"

    if not corrected_dir.exists():
        print(f"❌ No corrected output found for {scan_id}")
        return

    corrected_files = sorted(corrected_dir.glob("page_*.json"))
    if max_pages:
        corrected_files = corrected_files[:max_pages]

    print(f"\n📊 Analyzing Correction Stage: {scan_id}")
    print(f"   Pages to analyze: {len(corrected_files)}")
    print()

    # Statistics
    stats = {
        'total_pages': len(corrected_files),
        'total_paragraphs': 0,
        'paragraphs_with_no_errors': 0,
        'paragraphs_with_corrections': 0,
        'null_text_correct': 0,
        'null_text_violation': 0,
        'corrections_applied': 0,
        'corrections_not_applied': 0,
        'verbose_notes': 0,
        'circular_corrections': 0,
        'confidence_scores': [],
        'note_lengths': [],
        'issues_by_type': Counter()
    }

    all_issues = []

    # Analyze each page
    for corr_file in corrected_files:
        page_num = int(corr_file.stem.split('_')[1])

        ocr_data, corr_data = load_page_data(scan_id, page_num, storage_root)
        if not corr_data:
            continue

        # Match up blocks and paragraphs
        for block_idx, corr_block in enumerate(corr_data.get('blocks', [])):
            ocr_block = ocr_data['blocks'][block_idx] if block_idx < len(ocr_data['blocks']) else None

            for para_idx, corr_para in enumerate(corr_block.get('paragraphs', [])):
                stats['total_paragraphs'] += 1

                ocr_para = None
                if ocr_block:
                    ocr_paras = ocr_block['paragraphs']
                    if para_idx < len(ocr_paras):
                        ocr_para = ocr_paras[para_idx]

                if not ocr_para:
                    continue

                # Analyze this paragraph
                issues, notes, confidence, text_changed = analyze_paragraph(ocr_para, corr_para)

                stats['confidence_scores'].append(confidence)
                stats['note_lengths'].append(len(notes))

                if notes == "No OCR errors detected":
                    stats['paragraphs_with_no_errors'] += 1
                    if corr_para.get('text') is None:
                        stats['null_text_correct'] += 1
                    else:
                        stats['null_text_violation'] += 1
                else:
                    stats['paragraphs_with_corrections'] += 1
                    if text_changed:
                        stats['corrections_applied'] += 1
                    else:
                        stats['corrections_not_applied'] += 1

                # Track issues
                for issue in issues:
                    stats['issues_by_type'][issue['type']] += 1
                    all_issues.append({
                        **issue,
                        'page': page_num,
                        'block': corr_block['block_num'],
                        'para': corr_para['par_num']
                    })

    # Print summary
    print("=" * 70)
    print("SUMMARY STATISTICS")
    print("=" * 70)
    print()

    print(f"📄 Total Pages:      {stats['total_pages']}")
    print(f"📝 Total Paragraphs: {stats['total_paragraphs']}")
    print()

    # No errors analysis
    print("━" * 70)
    print("NO ERRORS ANALYSIS")
    print("━" * 70)
    no_error_total = stats['paragraphs_with_no_errors']
    if no_error_total > 0:
        correct_pct = (stats['null_text_correct'] / no_error_total) * 100
        violation_pct = (stats['null_text_violation'] / no_error_total) * 100

        print(f"Paragraphs with 'No OCR errors detected': {no_error_total}")
        print(f"  ✅ text=null (correct):    {stats['null_text_correct']:4d} ({correct_pct:5.1f}%)")
        print(f"  ❌ text=full (violation):  {stats['null_text_violation']:4d} ({violation_pct:5.1f}%)")

        if violation_pct > 5:
            print(f"\n⚠️  WARNING: {violation_pct:.1f}% of 'No OCR errors' have non-null text!")
    print()

    # Corrections analysis
    print("━" * 70)
    print("CORRECTIONS ANALYSIS")
    print("━" * 70)
    corr_total = stats['paragraphs_with_corrections']
    if corr_total > 0:
        applied_pct = (stats['corrections_applied'] / corr_total) * 100
        not_applied_pct = (stats['corrections_not_applied'] / corr_total) * 100

        print(f"Paragraphs with corrections documented: {corr_total}")
        print(f"  ✅ text changed (applied):    {stats['corrections_applied']:4d} ({applied_pct:5.1f}%)")
        print(f"  ❌ text unchanged (not applied): {stats['corrections_not_applied']:4d} ({not_applied_pct:5.1f}%)")

        if not_applied_pct > 10:
            print(f"\n⚠️  WARNING: {not_applied_pct:.1f}% of corrections not applied!")
    print()

    # Confidence scores
    print("━" * 70)
    print("CONFIDENCE SCORES")
    print("━" * 70)
    if stats['confidence_scores']:
        scores = stats['confidence_scores']
        avg_conf = sum(scores) / len(scores)
        high_conf = sum(1 for s in scores if s >= 0.95) / len(scores) * 100
        med_conf = sum(1 for s in scores if 0.85 <= s < 0.95) / len(scores) * 100
        low_conf = sum(1 for s in scores if s < 0.85) / len(scores) * 100

        print(f"Average confidence: {avg_conf:.3f}")
        print(f"  0.95-1.0 (high):    {high_conf:5.1f}%")
        print(f"  0.85-0.94 (medium): {med_conf:5.1f}%")
        print(f"  <0.85 (low):        {low_conf:5.1f}%")

        if high_conf > 85:
            print(f"\n⚠️  WARNING: {high_conf:.1f}% of paragraphs have 0.95+ confidence (over-confident)")
    print()

    # Note lengths
    print("━" * 70)
    print("NOTE LENGTHS")
    print("━" * 70)
    if stats['note_lengths']:
        lengths = stats['note_lengths']
        avg_len = sum(lengths) / len(lengths)
        verbose = sum(1 for l in lengths if l > 300) / len(lengths) * 100

        print(f"Average note length: {avg_len:.0f} chars")
        print(f"Notes > 300 chars (verbose): {verbose:.1f}%")

        if verbose > 5:
            print(f"\n⚠️  WARNING: {verbose:.1f}% of notes are excessively verbose")
    print()

    # Issues summary
    print("━" * 70)
    print("ISSUES FOUND")
    print("━" * 70)
    if stats['issues_by_type']:
        for issue_type, count in stats['issues_by_type'].most_common():
            print(f"  {issue_type:30s}: {count:4d}")
    else:
        print("  ✅ No issues found!")
    print()

    # Show examples of top issues
    if all_issues:
        print("=" * 70)
        print("EXAMPLE ISSUES (First 5)")
        print("=" * 70)
        print()

        for i, issue in enumerate(all_issues[:5], 1):
            print(f"Issue {i}: {issue['type']}")
            print(f"  Page {issue['page']}, Block {issue['block']}, Para {issue['para']}")
            print(f"  Severity: {issue['severity']}")
            print(f"  {issue['description']}")
            if 'notes' in issue:
                print(f"  Notes: {issue['notes'][:150]}...")
            print()

    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/analyze_correction.py <scan-id> [--pages N]")
        sys.exit(1)

    scan_id = sys.argv[1]
    max_pages = None

    if len(sys.argv) > 2 and sys.argv[2] == "--pages":
        max_pages = int(sys.argv[3])

    analyze_book(scan_id, max_pages=max_pages)
