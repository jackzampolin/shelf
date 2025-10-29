#!/usr/bin/env python3
"""
Analyze confidence score distribution across PSM outputs.

Usage:
    python tools/analyze_confidence.py <scan-id> [--threshold 0.85] [--psm 3,4,7]

Example:
    python tools/analyze_confidence.py admirals --threshold 0.85
    python tools/analyze_confidence.py admirals --psm 4 --threshold 0.80

Output:
    - % paragraphs below threshold (by PSM)
    - Confidence histogram
    - Low-confidence page list
    - Statistical summary
"""

import sys
import argparse
from pathlib import Path
from typing import Dict, List
from collections import defaultdict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.storage.book_storage import BookStorage
from infra.config import Config
from pipeline.ocr.schemas import OCRPageOutput


def analyze_confidence_distribution(storage: BookStorage, psm: int, threshold: float) -> Dict:
    """Analyze confidence distribution for a PSM output."""
    # Load from nested ocr/psmN/ structure
    ocr_dir = storage.stage('ocr').output_dir
    psm_dir = ocr_dir / f'psm{psm}'

    # Get all pages
    pages = sorted([int(f.stem.split('_')[1]) for f in psm_dir.glob('page_*.json')])

    if not pages:
        return {
            "psm": psm,
            "pages_analyzed": 0,
            "error": "No output pages found"
        }

    # Collect confidence scores
    all_para_confidences = []
    page_confidences = {}
    low_confidence_pages = []

    for page_num in pages:
        try:
            psm_file = psm_dir / f'page_{page_num:04d}.json'
            page_data = OCRPageOutput.model_validate_json(psm_file.read_text())

            para_confs = []
            for block in page_data.blocks:
                for para in block.paragraphs:
                    para_confs.append(para.avg_confidence)
                    all_para_confidences.append(para.avg_confidence)

            # Average confidence for page
            page_avg = sum(para_confs) / len(para_confs) if para_confs else 0.0
            page_confidences[page_num] = page_avg

            # Track low confidence pages
            if page_avg < threshold:
                low_confidence_pages.append((page_num, page_avg))

        except Exception as e:
            print(f"⚠️  Warning: Failed to process page {page_num}: {e}")
            continue

    # Calculate statistics
    if not all_para_confidences:
        return {
            "psm": psm,
            "pages_analyzed": 0,
            "error": "No paragraphs found"
        }

    total_paras = len(all_para_confidences)
    below_threshold = sum(1 for c in all_para_confidences if c < threshold)

    # Histogram bins
    bins = [0.0, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
    histogram = defaultdict(int)

    for conf in all_para_confidences:
        for i in range(len(bins) - 1):
            if bins[i] <= conf < bins[i + 1]:
                histogram[f"{bins[i]:.2f}-{bins[i+1]:.2f}"] += 1
                break
        else:
            if conf >= bins[-1]:
                histogram[f"{bins[-2]:.2f}-{bins[-1]:.2f}"] += 1

    return {
        "psm": psm,
        "pages_analyzed": len(pages),
        "total_paragraphs": total_paras,
        "below_threshold": below_threshold,
        "below_threshold_percent": (below_threshold / total_paras * 100),
        "mean_confidence": sum(all_para_confidences) / total_paras,
        "min_confidence": min(all_para_confidences),
        "max_confidence": max(all_para_confidences),
        "histogram": dict(histogram),
        "low_confidence_pages": sorted(low_confidence_pages, key=lambda x: x[1])[:10]
    }


def print_analysis(results: Dict, threshold: float):
    """Print confidence analysis results."""
    psm = results['psm']

    print(f"\n{'='*80}")
    print(f"Confidence Analysis for PSM {psm}")
    print(f"{'='*80}\n")

    if 'error' in results:
        print(f"❌ Error: {results['error']}")
        return

    # Summary statistics
    print("📊 Summary Statistics:")
    print(f"  Pages analyzed: {results['pages_analyzed']}")
    print(f"  Total paragraphs: {results['total_paragraphs']}")
    print(f"  Mean confidence: {results['mean_confidence']:.3f}")
    print(f"  Min confidence: {results['min_confidence']:.3f}")
    print(f"  Max confidence: {results['max_confidence']:.3f}")
    print()

    # Threshold analysis
    print(f"📉 Below Threshold ({threshold}):")
    print(f"  Paragraphs: {results['below_threshold']} / {results['total_paragraphs']} ({results['below_threshold_percent']:.1f}%)")
    print()

    # Histogram
    print("📊 Confidence Distribution:")
    histogram = results['histogram']
    max_count = max(histogram.values()) if histogram else 1

    for bin_range in sorted(histogram.keys()):
        count = histogram[bin_range]
        bar_length = int(50 * count / max_count)
        bar = '█' * bar_length
        print(f"  {bin_range}: {bar} {count} ({count / results['total_paragraphs'] * 100:.1f}%)")

    print()

    # Low confidence pages
    if results['low_confidence_pages']:
        print(f"📄 Pages with Lowest Average Confidence (< {threshold}):")
        for page_num, conf in results['low_confidence_pages'][:10]:
            print(f"  Page {page_num:4d}: {conf:.3f}")
    else:
        print(f"✅ No pages with average confidence below {threshold}")

    print()


def compare_psms(storage: BookStorage, psms: List[int], threshold: float):
    """Compare confidence across multiple PSMs."""
    results = {}

    for psm in psms:
        results[psm] = analyze_confidence_distribution(storage, psm, threshold)

    # Print individual analyses
    for psm in psms:
        print_analysis(results[psm], threshold)

    # Comparison summary
    if len(psms) > 1:
        print(f"\n{'='*80}")
        print("PSM Comparison Summary")
        print(f"{'='*80}\n")

        print(f"{'PSM':<10} {'Pages':<10} {'Paragraphs':<15} {'Mean Conf':<15} {'Below {:.2f}'.format(threshold):<20}")
        print("-" * 70)

        for psm in psms:
            r = results[psm]
            if 'error' not in r:
                print(f"{psm:<10} {r['pages_analyzed']:<10} {r['total_paragraphs']:<15} {r['mean_confidence']:<15.3f} {r['below_threshold_percent']:<20.1f}%")

        print()


def main():
    parser = argparse.ArgumentParser(
        description="Analyze confidence distribution across PSM outputs"
    )
    parser.add_argument("scan_id", help="Book scan ID")
    parser.add_argument("--threshold", type=float, default=0.85, help="Confidence threshold (default: 0.85)")
    parser.add_argument("--psm", type=str, default="3,4,6", help="PSMs to analyze (comma-separated, default: 3,4,6)")

    args = parser.parse_args()

    # Parse PSMs
    psms = [int(p.strip()) for p in args.psm.split(',')]

    # Initialize storage
    storage = BookStorage(scan_id=args.scan_id, storage_root=Config.book_storage_root)

    print(f"\n📚 Analyzing confidence for: {args.scan_id}")
    print(f"🔍 PSMs: {', '.join(map(str, psms))}")
    print(f"📏 Threshold: {args.threshold}")

    # Run analysis
    compare_psms(storage, psms, args.threshold)


if __name__ == "__main__":
    main()
