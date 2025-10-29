#!/usr/bin/env python3
"""
Generate PSM analysis reports after OCR stage completes.

Called automatically by OCRStage.after() hook.
Generates three reports:
1. PSM differences (detailed page-by-page comparison)
2. Confidence distribution (quality metrics per PSM)
3. PSM agreement rates (how often PSMs agree)
"""

import sys
from pathlib import Path
from typing import List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger


def generate_all_reports(
    storage: BookStorage,
    logger: PipelineLogger,
    psm_modes: List[int] = [3, 4, 6]
):
    """
    Generate all PSM analysis reports for a book.

    Saves reports to {book_slug}/ocr/:
    - psm_confidence_report.json (confidence distributions per PSM)
    - psm_agreement_report.json (agreement statistics)

    Args:
        storage: BookStorage instance
        logger: PipelineLogger instance
        psm_modes: List of PSM modes to analyze
    """
    import json
    from pipeline.ocr.analyze_confidence import analyze_confidence_distribution
    from pipeline.ocr.analyze_psm_agreement import analyze_book_agreement

    logger.info("Generating PSM analysis reports...")
    ocr_dir = storage.stage('ocr').output_dir

    # 1. Confidence distribution analysis
    logger.info("  Analyzing confidence distributions...")
    confidence_report = {
        'scan_id': storage.scan_id,
        'psm_modes': psm_modes,
        'threshold': 0.85,
        'psm_results': {}
    }

    for psm in psm_modes:
        results = analyze_confidence_distribution(storage, psm, threshold=0.85)
        confidence_report['psm_results'][f'psm{psm}'] = results

        # Log summary
        if 'error' not in results:
            logger.info(
                f"  PSM {psm}",
                pages=results['pages_analyzed'],
                mean_conf=f"{results['mean_confidence']:.3f}",
                below_threshold=f"{results['below_threshold_percent']:.1f}%"
            )

    # Save confidence report
    confidence_file = ocr_dir / 'psm_confidence_report.json'
    confidence_file.write_text(json.dumps(confidence_report, indent=2))
    logger.info(f"  Saved: ocr/psm_confidence_report.json")

    # 2. PSM agreement analysis
    logger.info("  Analyzing PSM agreement rates...")
    agreement_stats = analyze_book_agreement(storage, psm_modes, sample_size=None)

    if 'error' not in agreement_stats:
        # Add metadata
        agreement_report = {
            'scan_id': storage.scan_id,
            'psm_modes': psm_modes,
            'statistics': agreement_stats
        }

        # Save agreement report (without full page details to keep file size small)
        agreement_report_slim = {
            'scan_id': storage.scan_id,
            'psm_modes': psm_modes,
            'statistics': {
                'total_pages': agreement_stats['total_pages'],
                'identical_count': agreement_stats['identical_count'],
                'identical_percent': agreement_stats['identical_percent'],
                'minor_diff_count': agreement_stats['minor_diff_count'],
                'minor_diff_percent': agreement_stats['minor_diff_percent'],
                'moderate_diff_count': agreement_stats['moderate_diff_count'],
                'moderate_diff_percent': agreement_stats['moderate_diff_percent'],
                'major_diff_count': agreement_stats['major_diff_count'],
                'major_diff_percent': agreement_stats['major_diff_percent'],
                'avg_similarity': agreement_stats['avg_similarity'],
            }
        }

        agreement_file = ocr_dir / 'psm_agreement_report.json'
        agreement_file.write_text(json.dumps(agreement_report_slim, indent=2))
        logger.info(f"  Saved: ocr/psm_agreement_report.json")

        # Save full agreement analysis with per-page categories (for vision selection)
        agreement_full_file = ocr_dir / 'psm_agreement.json'
        agreement_full_file.write_text(json.dumps(agreement_report, indent=2))
        logger.info(f"  Saved: ocr/psm_agreement.json (full details for vision selection)")

        # Log summary
        logger.info(
            "  Agreement summary",
            identical=f"{agreement_stats['identical_percent']:.1f}%",
            minor_diff=f"{agreement_stats['minor_diff_percent']:.1f}%",
            major_diff=f"{agreement_stats['major_diff_percent']:.1f}%"
        )

        # Log recommendation
        if agreement_stats['major_diff_percent'] > 20:
            logger.warning("  HIGH DISAGREEMENT: >20% pages have major differences - LLM merge recommended")
        elif agreement_stats['major_diff_percent'] > 10:
            logger.info("  MODERATE DISAGREEMENT: 10-20% pages differ - LLM merge may be valuable")
        else:
            logger.info("  LOW DISAGREEMENT: <10% pages differ - single PSM may suffice")

    logger.info("PSM analysis reports complete")


if __name__ == "__main__":
    # Allow running standalone for debugging
    if len(sys.argv) < 2:
        print("Usage: python pipeline/ocr/analyze_psm_reports.py <scan-id>")
        sys.exit(1)

    from infra.config import Config
    scan_id = sys.argv[1]

    storage = BookStorage(scan_id=scan_id, storage_root=Config.book_storage_root)

    # Create a simple logger
    class SimpleLogger:
        def info(self, msg, **kwargs):
            print(f"INFO: {msg}", kwargs if kwargs else "")
        def warning(self, msg, **kwargs):
            print(f"WARN: {msg}", kwargs if kwargs else "")

    logger = SimpleLogger()

    generate_all_reports(storage, logger)
