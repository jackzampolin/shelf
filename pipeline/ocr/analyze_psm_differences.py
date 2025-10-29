#!/usr/bin/env python3
"""
Compare PSM outputs for a given page.

Usage:
    python tools/analyze_psm_differences.py <scan-id> <page-num>

Example:
    python tools/analyze_psm_differences.py admirals 42

Output:
    - Text differences highlighted
    - Confidence scores compared
    - Block structure differences
    - Agreement metrics
"""

import sys
import json
from pathlib import Path
from difflib import SequenceMatcher
from typing import Dict, List, Tuple

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.storage.book_storage import BookStorage
from infra.config import Config
from pipeline.ocr.schemas import OCRPageOutput


def load_psm_outputs(storage: BookStorage, page_num: int) -> Dict[str, OCRPageOutput]:
    """Load all PSM outputs for a page."""
    psm_outputs = {}

    for psm in [3, 4, 6]:
        # Load from nested ocr/psmN/ structure
        ocr_dir = storage.stage('ocr').output_dir
        psm_dir = ocr_dir / f'psm{psm}'
        psm_file = psm_dir / f'page_{page_num:04d}.json'

        try:
            if psm_file.exists():
                psm_data = OCRPageOutput.model_validate_json(psm_file.read_text())
                psm_outputs[f'psm{psm}'] = psm_data
            else:
                print(f"⚠️  Warning: PSM {psm} output not found for page {page_num}")
                psm_outputs[f'psm{psm}'] = None
        except Exception as e:
            print(f"⚠️  Warning: Failed to load PSM {psm} for page {page_num}: {e}")
            psm_outputs[f'psm{psm}'] = None

    return psm_outputs


def extract_full_text(page: OCRPageOutput) -> str:
    """Extract all text from a page."""
    if not page:
        return ""

    text_parts = []
    for block in page.blocks:
        for para in block.paragraphs:
            text_parts.append(para.text)

    return "\n\n".join(text_parts)


def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity ratio between two texts."""
    return SequenceMatcher(None, text1, text2).ratio()


def highlight_differences(text1: str, text2: str) -> Tuple[str, str]:
    """Highlight differences between two texts."""
    matcher = SequenceMatcher(None, text1, text2)

    result1 = []
    result2 = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            result1.append(text1[i1:i2])
            result2.append(text2[j1:j2])
        elif tag == 'replace':
            result1.append(f"[RED]{text1[i1:i2]}[/RED]")
            result2.append(f"[GREEN]{text2[j1:j2]}[/GREEN]")
        elif tag == 'delete':
            result1.append(f"[RED]{text1[i1:i2]}[/RED]")
        elif tag == 'insert':
            result2.append(f"[GREEN]{text2[j1:j2]}[/GREEN]")

    return ''.join(result1), ''.join(result2)


def get_structure_summary(page: OCRPageOutput) -> Dict:
    """Get structure summary for a page."""
    if not page:
        return {"blocks": 0, "paragraphs": 0, "avg_confidence": 0.0}

    total_para_conf = 0
    para_count = 0

    for block in page.blocks:
        for para in block.paragraphs:
            total_para_conf += para.avg_confidence
            para_count += 1

    return {
        "blocks": len(page.blocks),
        "paragraphs": para_count,
        "avg_confidence": total_para_conf / para_count if para_count > 0 else 0.0
    }


def compare_psm_outputs(storage: BookStorage, page_num: int):
    """Compare PSM outputs for a page and print analysis."""
    print(f"\n{'='*80}")
    print(f"PSM Comparison for {storage.scan_id} - Page {page_num}")
    print(f"{'='*80}\n")

    # Load all PSM outputs
    psm_outputs = load_psm_outputs(storage, page_num)

    # Check if we have all outputs
    available_psms = [psm for psm, data in psm_outputs.items() if data is not None]
    if len(available_psms) < 2:
        print("❌ Not enough PSM outputs available for comparison")
        return

    print(f"✅ Found outputs for: {', '.join(available_psms)}\n")

    # Extract text from each PSM
    texts = {psm: extract_full_text(data) for psm, data in psm_outputs.items() if data}

    # Structure summaries
    print("📊 Structure Summary:")
    print(f"{'PSM':<10} {'Blocks':<10} {'Paragraphs':<15} {'Avg Confidence':<20}")
    print("-" * 55)

    for psm, data in psm_outputs.items():
        if data:
            summary = get_structure_summary(data)
            print(f"{psm:<10} {summary['blocks']:<10} {summary['paragraphs']:<15} {summary['avg_confidence']:<20.3f}")

    print()

    # Text similarity matrix
    print("🔍 Text Similarity Matrix:")
    print(f"{'':>10} {'PSM3':>12} {'PSM4':>12} {'PSM6':>12}")
    print("-" * 50)

    for psm1 in available_psms:
        row = [f"{psm1:>10}"]
        for psm2 in ['psm3', 'psm4', 'psm6']:
            if psm2 in available_psms:
                if psm1 == psm2:
                    row.append(f"{'1.000':>12}")
                else:
                    similarity = calculate_similarity(texts[psm1], texts[psm2])
                    row.append(f"{similarity:>12.3f}")
            else:
                row.append(f"{'N/A':>12}")
        print(''.join(row))

    print()

    # Character and word counts
    print("📝 Text Length Comparison:")
    print(f"{'PSM':<10} {'Characters':<15} {'Words':<15}")
    print("-" * 40)

    for psm in available_psms:
        char_count = len(texts[psm])
        word_count = len(texts[psm].split())
        print(f"{psm:<10} {char_count:<15} {word_count:<15}")

    print()

    # Detailed text comparison (first 500 chars)
    print("📄 Text Comparison (first 500 characters):")
    print("-" * 80)

    for psm in available_psms:
        print(f"\n{psm.upper()}:")
        print(texts[psm][:500] + ("..." if len(texts[psm]) > 500 else ""))

    print()

    # Highlight differences between PSM3 and PSM4
    if 'psm3' in texts and 'psm4' in texts:
        print("🔴🟢 Differences: PSM3 vs PSM4 (first 500 chars)")
        print("-" * 80)

        diff1, diff2 = highlight_differences(texts['psm3'][:500], texts['psm4'][:500])

        print("\nPSM3:")
        print(diff1.replace('[RED]', '\033[91m').replace('[/RED]', '\033[0m'))

        print("\nPSM4:")
        print(diff2.replace('[GREEN]', '\033[92m').replace('[/GREEN]', '\033[0m'))

    print()

    # Confidence analysis by paragraph
    print("📊 Confidence by Paragraph:")
    print("-" * 80)

    for psm in available_psms:
        data = psm_outputs[psm]
        print(f"\n{psm.upper()}:")

        para_confidences = []
        for block_num, block in enumerate(data.blocks):
            for para_num, para in enumerate(block.paragraphs):
                para_confidences.append((block_num, para_num, para.avg_confidence, para.text[:50]))

        # Show low confidence paragraphs (< 0.85)
        low_conf = [p for p in para_confidences if p[2] < 0.85]

        if low_conf:
            print(f"  Low confidence paragraphs (< 0.85): {len(low_conf)}/{len(para_confidences)}")
            for block_num, para_num, conf, text_preview in low_conf[:3]:
                print(f"    Block {block_num}, Para {para_num}: {conf:.3f} - {text_preview}...")
        else:
            print(f"  All paragraphs have confidence >= 0.85")

    print("\n" + "="*80 + "\n")


def main():
    if len(sys.argv) != 3:
        print("Usage: python tools/analyze_psm_differences.py <scan-id> <page-num>")
        print("\nExample: python tools/analyze_psm_differences.py admirals 42")
        sys.exit(1)

    scan_id = sys.argv[1]
    page_num = int(sys.argv[2])

    # Initialize storage
    storage = BookStorage(scan_id=scan_id, storage_root=Config.book_storage_root)

    # Run comparison
    compare_psm_outputs(storage, page_num)


if __name__ == "__main__":
    main()
