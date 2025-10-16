#!/usr/bin/env python3
"""
Analyze correction stage outputs for quality and common issues.

Usage:
    python tools/analyze_correction.py <scan-id> [--pages N] [--export csv|json] [--output PATH]
    python tools/analyze_correction.py --compare <scan-id1> <scan-id2> ... [--export csv]

Analyzes:
- Correction application rate (notes say fixed, text actually changed)
- Null text accuracy (notes say "No OCR errors", text is null)
- Note length distribution and verbosity issues
- Confidence score distribution
- Common failure patterns
- Quality metrics (edit distance, similarity)
- Cost efficiency
- Actionable review list
"""

import json
import sys
import csv
import argparse
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
import difflib


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


def analyze_correction_quality(ocr_text, corr_text):
    """Analyze quality metrics of corrections made."""
    if not corr_text or corr_text == ocr_text:
        return None

    metrics = {}

    # Sequence similarity
    sm = difflib.SequenceMatcher(None, ocr_text, corr_text)
    metrics['similarity_ratio'] = sm.ratio()

    # Character-level changes
    metrics['chars_changed'] = abs(len(corr_text) - len(ocr_text))
    metrics['length_change_pct'] = ((len(corr_text) - len(ocr_text)) / len(ocr_text) * 100) if len(ocr_text) > 0 else 0

    # Word-level changes
    ocr_words = ocr_text.split()
    corr_words = corr_text.split()
    metrics['words_changed'] = abs(len(corr_words) - len(ocr_words))

    # Hyphenation fixes (common OCR issue)
    metrics['hyphen_fixes'] = ocr_text.count('-\n') - corr_text.count('-\n')

    return metrics


def print_histogram(values, title, bins=10, max_width=40):
    """Print ASCII histogram."""
    if not values:
        return

    # Create bins
    min_val = min(values)
    max_val = max(values)
    if min_val == max_val:
        return

    bin_width = (max_val - min_val) / bins
    bin_counts = [0] * bins

    for val in values:
        bin_idx = min(int((val - min_val) / bin_width), bins - 1)
        bin_counts[bin_idx] += 1

    max_count = max(bin_counts) if bin_counts else 1

    print(f"\n{title}")
    print("─" * 70)

    for i in range(bins):
        bin_start = min_val + i * bin_width
        bin_end = bin_start + bin_width
        count = bin_counts[i]
        bar_width = int((count / max_count) * max_width) if max_count > 0 else 0
        bar = "█" * bar_width
        print(f"{bin_start:6.2f}-{bin_end:6.2f} │{bar} {count}")


def analyze_paragraph(ocr_para, corr_para):
    """Analyze a single paragraph for issues."""
    issues = []

    ocr_text = ocr_para['text']
    corr_text = corr_para.get('text')
    notes = corr_para.get('notes', '')
    confidence = corr_para.get('confidence', 1.0)

    # Calculate quality metrics if text changed
    quality_metrics = None
    if corr_text and corr_text != ocr_text:
        quality_metrics = analyze_correction_quality(ocr_text, corr_text)

        # Check for over-correction (too much change)
        if quality_metrics and quality_metrics['similarity_ratio'] < 0.70:
            issues.append({
                'type': 'over_correction',
                'severity': 'high',
                'description': f'Only {quality_metrics["similarity_ratio"]:.1%} similarity (possible over-correction)',
                'similarity': quality_metrics['similarity_ratio']
            })

    # Issue 1: Notes say "No OCR errors" but text is not null
    # NOTE: This is a schema preference, not a quality issue. Downgraded to informational.
    if notes == "No OCR errors detected":
        if corr_text is not None and corr_text != ocr_text:
            # Only flag if text was actually changed despite "no errors" claim
            issues.append({
                'type': 'contradictory_no_errors',
                'severity': 'high',
                'description': 'Notes say "No OCR errors" but text was changed from OCR',
                'text_length': len(corr_text)
            })
        # Don't flag as issue if text matches OCR (just a schema preference)
        return issues, notes, confidence, (corr_text is None), None

    # Issue 2: Notes describe corrections but text unchanged
    correction_keywords = ['Fixed', 'Removed', 'Corrected', 'Normalized']
    describes_correction = any(kw in notes for kw in correction_keywords) if notes else False

    if describes_correction:
        if corr_text is None:
            issues.append({
                'type': 'correction_documented_but_null',
                'severity': 'critical',
                'description': 'Notes describe corrections but text is null',
                'notes': notes[:100]
            })
        elif corr_text == ocr_text:
            # Only flag if the notes are very specific about changes
            specific_keywords = ['to "', 'to \'', '→', 'from "', 'from \'']
            is_specific_claim = any(kw in notes for kw in specific_keywords)

            if is_specific_claim:
                issues.append({
                    'type': 'hallucinated_correction',
                    'severity': 'high',
                    'description': 'Notes claim specific corrections but text unchanged (LLM hallucination)',
                    'notes': notes[:100]
                })
            else:
                # General "fixed" claims without specifics - likely just checking/validation notes
                issues.append({
                    'type': 'correction_claim_unverified',
                    'severity': 'low',
                    'description': 'Notes mention corrections but text unchanged (may be false alarm)',
                    'notes': notes[:100]
                })
        else:
            # Text changed - check if it's only whitespace/hyphens (which are VALID corrections)
            normalized_corr = corr_text.replace(' ', '').replace('-', '').replace('\n', '')
            normalized_ocr = ocr_text.replace(' ', '').replace('-', '').replace('\n', '')

            if normalized_corr == normalized_ocr:
                # This is actually a legitimate correction (hyphen/spacing fix)
                # Don't flag as an issue - these are valuable corrections
                pass
            elif len(corr_text) != len(ocr_text) and abs(len(corr_text) - len(ocr_text)) / len(ocr_text) < 0.05:
                # Very small length changes (< 5%) - likely legitimate minor corrections
                pass

    # Issue 3: Verbose/rambling notes (downgraded - not a quality issue)
    if notes and len(notes) > 500:  # Increased threshold, only flag extreme cases
        issues.append({
            'type': 'verbose_notes',
            'severity': 'low',  # Downgraded from medium
            'description': f'Notes are {len(notes)} chars (very verbose)',
            'notes_preview': notes[:150]
        })

    # Issue 4: Circular corrections (Fixed X to X)
    import re
    same_fix = re.findall(r"['\"]([^'\"]+)['\"]\\s+to\\s+['\"](\1)['\"]", notes) if notes else []
    if same_fix:
        issues.append({
            'type': 'circular_correction',
            'severity': 'high',
            'description': f'Notes describe circular correction: {same_fix[0][0]} → {same_fix[0][0]}',
            'notes': notes[:100]
        })

    return issues, notes, confidence, (corr_text != ocr_text if corr_text else False), quality_metrics


def analyze_book(scan_id, max_pages=None, storage_root=None, export_format=None, export_path=None, silent=False):
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
        if not silent:
            print(f"❌ No corrected output found for {scan_id}")
        return None, None

    corrected_files = sorted(corrected_dir.glob("page_*.json"))
    if max_pages:
        corrected_files = corrected_files[:max_pages]

    if not silent:
        print(f"\n📊 Analyzing Correction Stage: {scan_id}")
        print(f"   Pages to analyze: {len(corrected_files)}")
        print()

    # Statistics
    stats = {
        'scan_id': scan_id,
        'total_pages': len(corrected_files),
        'total_paragraphs': 0,
        'paragraphs_with_no_errors': 0,
        'paragraphs_with_corrections': 0,
        'null_text_correct': 0,
        'schema_preference_mismatch': 0,
        'corrections_applied': 0,
        'corrections_not_applied': 0,
        'verbose_notes': 0,
        'circular_corrections': 0,
        'confidence_scores': [],
        'note_lengths': [],
        'issues_by_type': Counter(),
        'quality_metrics': {
            'similarity_ratios': [],
            'chars_changed': [],
            'length_change_pcts': [],
            'words_changed': []
        },
        'cost_per_page': [],
        'total_cost': 0.0,
        'by_model': defaultdict(lambda: {
            'pages': 0,
            'total_cost': 0.0,
            'corrections_applied': 0,
            'avg_confidence': []
        })
    }

    all_issues = []

    # Analyze each page
    for corr_file in corrected_files:
        page_num = int(corr_file.stem.split('_')[1])

        ocr_data, corr_data = load_page_data(scan_id, page_num, storage_root)
        if not corr_data:
            continue

        # Track page-level cost
        page_cost = corr_data.get('processing_cost', 0.0)
        stats['cost_per_page'].append(page_cost)
        stats['total_cost'] += page_cost

        # Track model used
        model = corr_data.get('model_used', 'unknown')
        stats['by_model'][model]['pages'] += 1
        stats['by_model'][model]['total_cost'] += page_cost

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
                issues, notes, confidence, text_changed, quality_metrics = analyze_paragraph(ocr_para, corr_para)

                stats['confidence_scores'].append(confidence)
                stats['note_lengths'].append(len(notes) if notes else 0)

                # Track quality metrics
                if quality_metrics:
                    stats['quality_metrics']['similarity_ratios'].append(quality_metrics['similarity_ratio'])
                    stats['quality_metrics']['chars_changed'].append(quality_metrics['chars_changed'])
                    stats['quality_metrics']['length_change_pcts'].append(quality_metrics['length_change_pct'])
                    stats['quality_metrics']['words_changed'].append(quality_metrics['words_changed'])

                # Track model performance
                stats['by_model'][model]['avg_confidence'].append(confidence)

                if notes == "No OCR errors detected":
                    stats['paragraphs_with_no_errors'] += 1
                    if corr_para.get('text') is None:
                        stats['null_text_correct'] += 1
                    else:
                        # Only count as schema mismatch if text is unchanged from OCR
                        if corr_para.get('text') == ocr_para.get('text'):
                            stats['schema_preference_mismatch'] += 1
                        # If text changed despite "no errors", that's a real issue (caught elsewhere)
                else:
                    stats['paragraphs_with_corrections'] += 1
                    if text_changed:
                        stats['corrections_applied'] += 1
                        stats['by_model'][model]['corrections_applied'] += 1
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
    if not silent:
        print("=" * 70)
        print("SUMMARY STATISTICS")
        print("=" * 70)
        print()

        print(f"📄 Total Pages:      {stats['total_pages']}")
        print(f"📝 Total Paragraphs: {stats['total_paragraphs']}")
        print(f"💰 Total Cost:       ${stats['total_cost']:.4f}")
        if stats['total_pages'] > 0:
            print(f"   Cost per page:    ${stats['total_cost'] / stats['total_pages']:.4f}")
        print()

    # No errors analysis
    if not silent:
        print("━" * 70)
        print("NO ERRORS ANALYSIS")
        print("━" * 70)
        no_error_total = stats['paragraphs_with_no_errors']
        if no_error_total > 0:
            correct_pct = (stats['null_text_correct'] / no_error_total) * 100
            schema_mismatch_pct = (stats['schema_preference_mismatch'] / no_error_total) * 100

            print(f"Paragraphs with 'No OCR errors detected': {no_error_total}")
            print(f"  ✅ text=null (schema compliant): {stats['null_text_correct']:4d} ({correct_pct:5.1f}%)")
            print(f"  ℹ️  text=full (schema preference): {stats['schema_preference_mismatch']:4d} ({schema_mismatch_pct:5.1f}%)")

            if schema_mismatch_pct > 50:
                print(f"\n  Note: {schema_mismatch_pct:.1f}% return full text instead of null")
                print(f"  This is a schema preference issue, not a quality problem.")
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

    # Quality Metrics section
    if not silent and stats['quality_metrics']['similarity_ratios']:
        print("=" * 70)
        print("QUALITY METRICS (Text Changes)")
        print("=" * 70)
        print()

        sim_ratios = stats['quality_metrics']['similarity_ratios']
        avg_sim = sum(sim_ratios) / len(sim_ratios)
        print(f"Corrections made: {len(sim_ratios)}")
        print(f"Average similarity to original: {avg_sim:.3f}")

        # Check for over-corrections
        over_corrections = sum(1 for s in sim_ratios if s < 0.70)
        if over_corrections > 0:
            pct = (over_corrections / len(sim_ratios)) * 100
            print(f"⚠️  {over_corrections} corrections with <70% similarity ({pct:.1f}%)")

        # Character changes
        if stats['quality_metrics']['chars_changed']:
            avg_chars = sum(stats['quality_metrics']['chars_changed']) / len(stats['quality_metrics']['chars_changed'])
            print(f"\nAverage characters changed: {avg_chars:.1f}")

        # Histograms
        print_histogram(sim_ratios, "SIMILARITY DISTRIBUTION", bins=15)
        print()

    # Model Performance section
    if not silent and len(stats['by_model']) > 0:
        print("=" * 70)
        print("MODEL PERFORMANCE")
        print("=" * 70)
        print()

        for model, model_stats in stats['by_model'].items():
            print(f"Model: {model}")
            print(f"  Pages processed: {model_stats['pages']}")
            print(f"  Total cost:      ${model_stats['total_cost']:.4f}")
            if model_stats['pages'] > 0:
                print(f"  Cost per page:   ${model_stats['total_cost'] / model_stats['pages']:.4f}")
            if model_stats['avg_confidence']:
                avg_conf = sum(model_stats['avg_confidence']) / len(model_stats['avg_confidence'])
                print(f"  Avg confidence:  {avg_conf:.3f}")
            print(f"  Corrections:     {model_stats['corrections_applied']}")
            print()

    # Generate review list
    if not silent and all_issues:
        generate_review_list(scan_id, all_issues, max_items=15)

    # Export if requested
    if export_format == 'csv' and export_path:
        export_to_csv(scan_id, stats, all_issues, export_path)
        if not silent:
            print(f"\n✅ Exported to {export_path}")
    elif export_format == 'json' and export_path:
        export_to_json(scan_id, stats, all_issues, export_path)
        if not silent:
            print(f"\n✅ Exported to {export_path}")

    if not silent:
        print("=" * 70)
        print("ANALYSIS COMPLETE")
        print("=" * 70)

    return stats, all_issues


def generate_review_list(scan_id, all_issues, max_items=15):
    """Generate prioritized list of pages to manually review."""
    priority_order = {
        'correction_not_applied': 1,
        'over_correction': 2,
        'circular_correction': 3,
        'correction_documented_but_null': 4,
        'null_text_violation': 5,
        'low_confidence': 6
    }

    # Sort by priority and severity
    sorted_issues = sorted(all_issues,
                          key=lambda i: (priority_order.get(i['type'], 99),
                                        {'critical': 1, 'high': 2, 'medium': 3, 'low': 4}.get(i.get('severity', 'low'), 4)))

    print("=" * 70)
    print(f"🔍 TOP {max_items} PAGES TO REVIEW (Priority Order)")
    print("=" * 70)
    print(f"{'#':<4} {'Page':<7} {'Location':<15} {'Issue':<25} {'Severity':<10}")
    print("─" * 70)

    seen_combinations = set()
    displayed = 0

    for issue in sorted_issues:
        if displayed >= max_items:
            break

        page = issue['page']
        block = issue.get('block', '?')
        para = issue.get('para', '?')

        # Create unique key for this issue location
        key = (page, block, para, issue['type'])
        if key in seen_combinations:
            continue
        seen_combinations.add(key)

        location = f"b{block}/p{para}"
        issue_type = issue['type'][:24]

        displayed += 1
        print(f"{displayed:<4} p{page:<6} {location:<15} {issue_type:<25} {issue.get('severity', 'N/A'):<10}")

    print()
    print(f"💡 Review these pages in the correction output to verify quality")
    print()


def export_to_csv(scan_id, stats, all_issues, output_path):
    """Export analysis results to CSV files."""
    base_path = Path(output_path).with_suffix('')

    # Export issues
    issues_path = f"{base_path}_issues.csv"
    with open(issues_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'page', 'block', 'para', 'type', 'severity',
            'description', 'confidence', 'similarity'
        ])
        writer.writeheader()
        for issue in all_issues:
            writer.writerow({
                'page': issue['page'],
                'block': issue.get('block', ''),
                'para': issue.get('para', ''),
                'type': issue['type'],
                'severity': issue['severity'],
                'description': issue['description'],
                'confidence': issue.get('confidence', ''),
                'similarity': issue.get('similarity', '')
            })

    # Export summary stats
    summary_path = f"{base_path}_summary.csv"
    with open(summary_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['metric', 'value'])
        writer.writerow(['scan_id', scan_id])
        writer.writerow(['total_pages', stats['total_pages']])
        writer.writerow(['total_paragraphs', stats['total_paragraphs']])
        writer.writerow(['total_cost', f"${stats['total_cost']:.4f}"])
        writer.writerow(['corrections_applied', stats['corrections_applied']])
        writer.writerow(['corrections_not_applied', stats['corrections_not_applied']])
        writer.writerow(['schema_preference_mismatches', stats['schema_preference_mismatch']])

        if stats['confidence_scores']:
            avg_conf = sum(stats['confidence_scores']) / len(stats['confidence_scores'])
            writer.writerow(['avg_confidence', f"{avg_conf:.3f}"])

        if stats['quality_metrics']['similarity_ratios']:
            avg_sim = sum(stats['quality_metrics']['similarity_ratios']) / len(stats['quality_metrics']['similarity_ratios'])
            writer.writerow(['avg_similarity', f"{avg_sim:.3f}"])


def export_to_json(scan_id, stats, all_issues, output_path):
    """Export analysis results to JSON."""
    # Convert Counter objects to regular dicts for JSON serialization
    issues_by_type = dict(stats['issues_by_type'])

    # Calculate summary metrics
    summary = {
        'scan_id': scan_id,
        'analysis_timestamp': datetime.now().isoformat(),
        'total_pages': stats['total_pages'],
        'total_paragraphs': stats['total_paragraphs'],
        'total_cost': stats['total_cost'],
        'corrections_applied': stats['corrections_applied'],
        'corrections_not_applied': stats['corrections_not_applied'],
        'schema_mismatch_rate': (stats['schema_preference_mismatch'] / stats['paragraphs_with_no_errors']) if stats['paragraphs_with_no_errors'] > 0 else 0,
        'corrections_applied_rate': (stats['corrections_applied'] / stats['paragraphs_with_corrections']) if stats['paragraphs_with_corrections'] > 0 else 0,
    }

    if stats['confidence_scores']:
        summary['avg_confidence'] = sum(stats['confidence_scores']) / len(stats['confidence_scores'])

    if stats['quality_metrics']['similarity_ratios']:
        summary['avg_similarity'] = sum(stats['quality_metrics']['similarity_ratios']) / len(stats['quality_metrics']['similarity_ratios'])

    output = {
        'summary': summary,
        'issues_by_type': issues_by_type,
        'all_issues': all_issues[:100],  # Top 100 issues
        'model_performance': {
            model: {
                'pages': model_stats['pages'],
                'total_cost': model_stats['total_cost'],
                'avg_confidence': sum(model_stats['avg_confidence']) / len(model_stats['avg_confidence']) if model_stats['avg_confidence'] else 0,
                'corrections_applied': model_stats['corrections_applied']
            }
            for model, model_stats in stats['by_model'].items()
        }
    }

    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)


def compare_books(scan_ids, storage_root=None):
    """Compare correction quality across multiple books."""
    if storage_root is None:
        storage_root = Path("~/Documents/book_scans").expanduser()
    else:
        storage_root = Path(storage_root)

    print("\n" + "=" * 70)
    print("MULTI-BOOK CORRECTION ANALYSIS")
    print("=" * 70)
    print()

    results = []

    for scan_id in scan_ids:
        print(f"Analyzing {scan_id}...")
        stats, issues = analyze_book(scan_id, storage_root=storage_root, silent=True)

        if stats is None:
            print(f"  ❌ Skipped (no corrected output)")
            continue

        schema_mismatch_rate = (stats['schema_preference_mismatch'] / stats['paragraphs_with_no_errors']) if stats['paragraphs_with_no_errors'] > 0 else 0
        corrections_applied_rate = (stats['corrections_applied'] / stats['paragraphs_with_corrections']) if stats['paragraphs_with_corrections'] > 0 else 0
        avg_confidence = sum(stats['confidence_scores']) / len(stats['confidence_scores']) if stats['confidence_scores'] else 0
        avg_similarity = sum(stats['quality_metrics']['similarity_ratios']) / len(stats['quality_metrics']['similarity_ratios']) if stats['quality_metrics']['similarity_ratios'] else 0

        results.append({
            'scan_id': scan_id,
            'pages': stats['total_pages'],
            'cost': stats['total_cost'],
            'schema_mismatch_rate': schema_mismatch_rate,
            'corrections_applied_rate': corrections_applied_rate,
            'avg_confidence': avg_confidence,
            'avg_similarity': avg_similarity,
            'total_issues': len(issues)
        })

    # Print comparison table
    print("\n" + "=" * 120)
    print(f"{'Book':<25} {'Pages':<7} {'Cost':<10} {'Schema Δ%':<12} {'Corr Applied%':<15} {'Avg Conf':<10} {'Avg Sim':<10} {'Issues':<8}")
    print("─" * 120)

    for r in results:
        print(f"{r['scan_id']:<25} {r['pages']:<7} ${r['cost']:<9.4f} {r['schema_mismatch_rate']*100:<11.1f}% {r['corrections_applied_rate']*100:<14.1f}% {r['avg_confidence']:<10.3f} {r['avg_similarity']:<10.3f} {r['total_issues']:<8}")

    print("=" * 120)
    print()

    # Export to CSV
    output_path = storage_root / "library_correction_comparison.csv"
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys() if results else [])
        writer.writeheader()
        writer.writerows(results)

    print(f"✅ Comparison exported to: {output_path}")
    print()

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Analyze correction stage outputs for quality and common issues',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a single book
  python tools/analyze_correction.py accidental-president

  # Analyze with page limit
  python tools/analyze_correction.py accidental-president --pages 50

  # Export to CSV
  python tools/analyze_correction.py accidental-president --export csv --output results.csv

  # Export to JSON
  python tools/analyze_correction.py accidental-president --export json --output results.json

  # Compare multiple books
  python tools/analyze_correction.py --compare book1 book2 book3
        """
    )

    parser.add_argument('scan_id', nargs='?', help='Book scan ID to analyze')
    parser.add_argument('--pages', type=int, help='Limit analysis to first N pages')
    parser.add_argument('--export', choices=['csv', 'json'], help='Export format (csv or json)')
    parser.add_argument('--output', help='Output file path for export')
    parser.add_argument('--compare', nargs='+', metavar='SCAN_ID', help='Compare multiple books')
    parser.add_argument('--storage-root', help='Book storage root directory (default: ~/Documents/book_scans)')

    args = parser.parse_args()

    if args.compare:
        # Multi-book comparison mode
        compare_books(args.compare, storage_root=args.storage_root)
    elif args.scan_id:
        # Single book analysis mode
        analyze_book(
            args.scan_id,
            max_pages=args.pages,
            storage_root=args.storage_root,
            export_format=args.export,
            export_path=args.output
        )
    else:
        parser.print_help()
        sys.exit(1)
