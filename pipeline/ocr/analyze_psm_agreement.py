#!/usr/bin/env python3
"""
Calculate PSM agreement rates across a book.

Usage:
    python tools/analyze_psm_agreement.py <scan-id> [--sample-size 20]

Example:
    python tools/analyze_psm_agreement.py admirals --sample-size 50

Output:
    - % pages where all PSMs identical
    - % pages with minor differences (<10 words)
    - % pages with major differences
    - Examples of each category
    - Disagreement patterns
"""

import sys
import argparse
import random
from pathlib import Path
from typing import Dict, List, Tuple
from difflib import SequenceMatcher

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.storage.book_storage import BookStorage
from infra.config import Config
from pipeline.ocr.schemas import OCRPageOutput


def extract_full_text(page: OCRPageOutput) -> str:
    """Extract all text from a page."""
    if not page:
        return ""

    text_parts = []
    for block in page.blocks:
        for para in block.paragraphs:
            text_parts.append(para.text)

    return "\n\n".join(text_parts)


def count_word_differences(text1: str, text2: str) -> int:
    """Count number of different words between two texts."""
    words1 = set(text1.split())
    words2 = set(text2.split())

    # Symmetric difference
    return len(words1.symmetric_difference(words2))


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity ratio between two texts."""
    return SequenceMatcher(None, text1, text2).ratio()


def analyze_page_agreement(storage: BookStorage, page_num: int, psms: List[int]) -> Dict:
    """Analyze agreement between PSMs for a single page."""
    texts = {}
    page_data = {}
    ocr_dir = storage.stage('ocr').output_dir

    # Load all PSM outputs
    for psm in psms:
        psm_dir = ocr_dir / f'psm{psm}'
        psm_file = psm_dir / f'page_{page_num:04d}.json'
        try:
            if psm_file.exists():
                data = OCRPageOutput.model_validate_json(psm_file.read_text())
                texts[psm] = extract_full_text(data)
                page_data[psm] = data
            else:
                return {"error": f"Missing PSM {psm} output"}
        except Exception as e:
            return {"error": f"Failed to load PSM {psm}: {e}"}

    # Calculate pairwise similarities
    similarities = {}
    word_diffs = {}

    for i, psm1 in enumerate(psms):
        for psm2 in psms[i+1:]:
            key = f"psm{psm1}_vs_psm{psm2}"
            similarities[key] = calculate_similarity(texts[psm1], texts[psm2])
            word_diffs[key] = count_word_differences(texts[psm1], texts[psm2])

    # Average similarity
    avg_similarity = sum(similarities.values()) / len(similarities) if similarities else 0.0
    max_word_diff = max(word_diffs.values()) if word_diffs else 0

    # Categorize agreement level
    if avg_similarity >= 0.99:
        category = "identical"
    elif avg_similarity >= 0.95 and max_word_diff <= 10:
        category = "minor_differences"
    elif avg_similarity >= 0.85:
        category = "moderate_differences"
    else:
        category = "major_differences"

    return {
        "page_num": page_num,
        "category": category,
        "avg_similarity": avg_similarity,
        "max_word_diff": max_word_diff,
        "similarities": similarities,
        "word_diffs": word_diffs,
        "text_lengths": {psm: len(texts[psm]) for psm in psms}
    }


def analyze_book_agreement(storage: BookStorage, psms: List[int], sample_size: int = None) -> Dict:
    """Analyze agreement across entire book."""
    # Get all pages from first PSM
    ocr_dir = storage.stage('ocr').output_dir
    psm_dir = ocr_dir / f'psm{psms[0]}'
    all_pages = sorted([int(f.stem.split('_')[1]) for f in psm_dir.glob('page_*.json')])

    if not all_pages:
        return {"error": "No pages found"}

    # Sample pages if requested
    if sample_size and sample_size < len(all_pages):
        pages_to_analyze = sorted(random.sample(all_pages, sample_size))
    else:
        pages_to_analyze = all_pages

    # Analyze each page
    results = []
    categories = {
        "identical": [],
        "minor_differences": [],
        "moderate_differences": [],
        "major_differences": [],
        "errors": []
    }

    # Silent processing (no progress output when called from pipeline)
    for i, page_num in enumerate(pages_to_analyze):
        result = analyze_page_agreement(storage, page_num, psms)

        if "error" in result:
            categories["errors"].append((page_num, result["error"]))
        else:
            results.append(result)
            categories[result["category"]].append(result)

    # Calculate statistics
    total = len(results)

    if total == 0:
        return {"error": "No valid page analyses"}

    stats = {
        "total_pages": total,
        "identical_count": len(categories["identical"]),
        "minor_diff_count": len(categories["minor_differences"]),
        "moderate_diff_count": len(categories["moderate_differences"]),
        "major_diff_count": len(categories["major_differences"]),
        "error_count": len(categories["errors"]),
        "identical_percent": len(categories["identical"]) / total * 100,
        "minor_diff_percent": len(categories["minor_differences"]) / total * 100,
        "moderate_diff_percent": len(categories["moderate_differences"]) / total * 100,
        "major_diff_percent": len(categories["major_differences"]) / total * 100,
        "avg_similarity": sum(r["avg_similarity"] for r in results) / total,
        "categories": categories
    }

    return stats


def print_analysis(stats: Dict, storage: BookStorage):
    """Print agreement analysis results."""
    print(f"\n{'='*80}")
    print(f"PSM Agreement Analysis for {storage.scan_id}")
    print(f"{'='*80}\n")

    if "error" in stats:
        print(f"❌ Error: {stats['error']}")
        return

    # Summary statistics
    print("📊 Agreement Summary:")
    print(f"  Total pages analyzed: {stats['total_pages']}")
    print(f"  Average similarity: {stats['avg_similarity']:.3f}")
    print()

    # Category breakdown
    print("📈 Agreement Categories:")
    print(f"  {'Category':<25} {'Count':<10} {'Percentage':<15}")
    print("-" * 50)
    print(f"  {'Identical (≥99%)':<25} {stats['identical_count']:<10} {stats['identical_percent']:<15.1f}%")
    print(f"  {'Minor diff (95-99%)':<25} {stats['minor_diff_count']:<10} {stats['minor_diff_percent']:<15.1f}%")
    print(f"  {'Moderate diff (85-95%)':<25} {stats['moderate_diff_count']:<10} {stats['moderate_diff_percent']:<15.1f}%")
    print(f"  {'Major diff (<85%)':<25} {stats['major_diff_count']:<10} {stats['major_diff_percent']:<15.1f}%")

    if stats['error_count'] > 0:
        print(f"  {'Errors':<25} {stats['error_count']:<10}")

    print()

    # Examples from each category
    categories = stats['categories']

    def print_examples(category_name: str, display_name: str, examples: List, count: int = 5):
        if examples:
            print(f"📄 Example pages - {display_name}:")
            for result in examples[:count]:
                if isinstance(result, dict) and 'page_num' in result:
                    page_num = result['page_num']
                    sim = result.get('avg_similarity', 0)
                    word_diff = result.get('max_word_diff', 0)
                    print(f"  Page {page_num:4d}: similarity={sim:.3f}, max_word_diff={word_diff}")
            print()

    print_examples("identical", "Identical text", categories['identical'])
    print_examples("minor_differences", "Minor differences", categories['minor_differences'])
    print_examples("moderate_differences", "Moderate differences", categories['moderate_differences'])
    print_examples("major_differences", "Major differences (⚠️  investigate these!)", categories['major_differences'])

    # Error summary
    if categories['errors']:
        print("⚠️  Errors encountered:")
        for page_num, error in categories['errors'][:5]:
            print(f"  Page {page_num}: {error}")
        print()

    # Recommendations
    print("💡 Recommendations:")

    if stats['major_diff_percent'] > 20:
        print("  ⚠️  HIGH DISAGREEMENT: >20% of pages have major differences between PSMs")
        print("     → LLM-guided merge likely valuable")
        print("     → Investigate pages with major differences")
    elif stats['major_diff_percent'] > 10:
        print("  ⚡ MODERATE DISAGREEMENT: 10-20% of pages have major differences")
        print("     → LLM-guided merge may be valuable")
        print("     → Analyze cost-benefit")
    else:
        print("  ✅ LOW DISAGREEMENT: <10% of pages have major differences")
        print("     → Single PSM may be sufficient")
        print("     → LLM merge may not justify cost")

    if stats['identical_percent'] > 70:
        print("  ✅ HIGH AGREEMENT: >70% of pages are identical")
        print("     → Consider confidence-based selective merge")
        print("     → Only merge pages with differences")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Calculate PSM agreement rates across a book"
    )
    parser.add_argument("scan_id", help="Book scan ID")
    parser.add_argument("--sample-size", type=int, default=None, help="Number of pages to sample (default: all pages)")
    parser.add_argument("--psm", type=str, default="3,4,6", help="PSMs to compare (comma-separated, default: 3,4,6)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling (default: 42)")

    args = parser.parse_args()

    # Set random seed for reproducibility
    random.seed(args.seed)

    # Parse PSMs
    psms = [int(p.strip()) for p in args.psm.split(',')]

    # Initialize storage
    storage = BookStorage(scan_id=args.scan_id, storage_root=Config.book_storage_root)

    print(f"\n📚 Analyzing PSM agreement for: {args.scan_id}")
    print(f"🔍 Comparing PSMs: {', '.join(map(str, psms))}")

    # Run analysis
    stats = analyze_book_agreement(storage, psms, args.sample_size)

    # Print results
    print_analysis(stats, storage)


if __name__ == "__main__":
    main()
