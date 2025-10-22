#!/usr/bin/env python3
"""
OCR Stage Reporting

Generates aggregate statistics and reports for OCR stage execution.
Provides useful metrics for quick quality assessment.
"""

import json
import csv
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OCRStageReport:
    """Report for OCR stage execution."""

    # Basic metrics
    total_pages: int = 0
    total_blocks: int = 0
    total_paragraphs: int = 0
    total_images: int = 0

    # Confidence metrics
    avg_confidence: float = 0.0
    min_confidence: float = 1.0
    max_confidence: float = 0.0
    low_confidence_pages: List[int] = field(default_factory=list)  # Pages with avg confidence < 0.8

    # Content distribution
    pages_with_images: int = 0
    pages_by_block_count: Dict[str, int] = field(default_factory=lambda: {
        "1-2": 0,    # Title pages, chapter starts
        "3-5": 0,    # Light content
        "6-10": 0,   # Normal content
        "11+": 0     # Dense content
    })

    # Text volume
    avg_paragraphs_per_page: float = 0.0
    avg_blocks_per_page: float = 0.0
    total_words: int = 0
    avg_words_per_page: float = 0.0

    # Processing metadata
    stage_complete: bool = False
    processing_date: Optional[str] = None

    def add_page_data(self, page_data: Dict[str, Any]):
        """Update report with data from a single page."""
        self.total_pages += 1

        # Count blocks and paragraphs
        blocks = page_data.get('blocks', [])
        self.total_blocks += len(blocks)

        page_paragraphs = 0
        page_confidences = []
        page_words = 0

        for block in blocks:
            paragraphs = block.get('paragraphs', [])
            page_paragraphs += len(paragraphs)

            for para in paragraphs:
                # Confidence tracking
                conf = para.get('avg_confidence', 0.0)
                page_confidences.append(conf)

                # Word count
                text = para.get('text', '')
                page_words += len(text.split())

        self.total_paragraphs += page_paragraphs
        self.total_words += page_words

        # Block count distribution
        block_count = len(blocks)
        if block_count <= 2:
            self.pages_by_block_count["1-2"] += 1
        elif block_count <= 5:
            self.pages_by_block_count["3-5"] += 1
        elif block_count <= 10:
            self.pages_by_block_count["6-10"] += 1
        else:
            self.pages_by_block_count["11+"] += 1

        # Image tracking
        images = page_data.get('images', [])
        self.total_images += len(images)
        if len(images) > 0:
            self.pages_with_images += 1

        # Confidence tracking
        if page_confidences:
            page_avg_conf = sum(page_confidences) / len(page_confidences)

            # Update global confidence stats
            self.avg_confidence = (
                (self.avg_confidence * (self.total_pages - 1) + page_avg_conf) / self.total_pages
            )
            self.min_confidence = min(self.min_confidence, min(page_confidences))
            self.max_confidence = max(self.max_confidence, max(page_confidences))

            # Track low confidence pages
            if page_avg_conf < 0.8:
                self.low_confidence_pages.append(page_data['page_number'])

    def finalize(self):
        """Calculate final aggregates after all pages processed."""
        if self.total_pages > 0:
            self.avg_paragraphs_per_page = self.total_paragraphs / self.total_pages
            self.avg_blocks_per_page = self.total_blocks / self.total_pages
            self.avg_words_per_page = self.total_words / self.total_pages

        self.stage_complete = True
        self.processing_date = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        return {
            'total_pages': self.total_pages,
            'total_blocks': self.total_blocks,
            'total_paragraphs': self.total_paragraphs,
            'total_images': self.total_images,
            'avg_confidence': round(self.avg_confidence, 3),
            'min_confidence': round(self.min_confidence, 3),
            'max_confidence': round(self.max_confidence, 3),
            'low_confidence_pages': self.low_confidence_pages,
            'pages_with_images': self.pages_with_images,
            'pages_by_block_count': self.pages_by_block_count,
            'avg_paragraphs_per_page': round(self.avg_paragraphs_per_page, 1),
            'avg_blocks_per_page': round(self.avg_blocks_per_page, 1),
            'total_words': self.total_words,
            'avg_words_per_page': round(self.avg_words_per_page, 1),
            'stage_complete': self.stage_complete,
            'processing_date': self.processing_date
        }

    def format_summary(self) -> str:
        """Format summary as string."""
        lines = []

        lines.append("\n" + "=" * 60)
        lines.append("OCR STAGE REPORT")
        lines.append("=" * 60)

        lines.append("\n📊 CONTENT METRICS")
        lines.append(f"   Pages Processed:        {self.total_pages:,}")
        lines.append(f"   Total Blocks:           {self.total_blocks:,}")
        lines.append(f"   Total Paragraphs:       {self.total_paragraphs:,}")
        lines.append(f"   Total Words:            {self.total_words:,}")
        lines.append(f"   Extracted Images:       {self.total_images}")

        lines.append("\n📈 AVERAGES")
        lines.append(f"   Blocks/Page:            {self.avg_blocks_per_page:.1f}")
        lines.append(f"   Paragraphs/Page:        {self.avg_paragraphs_per_page:.1f}")
        lines.append(f"   Words/Page:             {self.avg_words_per_page:.1f}")

        lines.append("\n✨ OCR CONFIDENCE")
        lines.append(f"   Average:                {self.avg_confidence:.1%}")
        lines.append(f"   Range:                  {self.min_confidence:.1%} - {self.max_confidence:.1%}")
        if self.low_confidence_pages:
            lines.append(f"   Low Confidence Pages:   {len(self.low_confidence_pages)} pages < 80%")
            if len(self.low_confidence_pages) <= 10:
                lines.append(f"                           {self.low_confidence_pages}")
            else:
                lines.append(f"                           {self.low_confidence_pages[:10]}... (showing first 10)")
        else:
            lines.append(f"   Low Confidence Pages:   None (all pages ≥ 80%)")

        lines.append("\n📄 PAGE DISTRIBUTION (by block count)")
        lines.append(f"   1-2 blocks:             {self.pages_by_block_count['1-2']:,} pages (title pages, chapter starts)")
        lines.append(f"   3-5 blocks:             {self.pages_by_block_count['3-5']:,} pages (light content)")
        lines.append(f"   6-10 blocks:            {self.pages_by_block_count['6-10']:,} pages (normal content)")
        lines.append(f"   11+ blocks:             {self.pages_by_block_count['11+']:,} pages (dense content)")

        lines.append("\n🖼️  IMAGES")
        lines.append(f"   Pages with Images:      {self.pages_with_images}")
        if self.pages_with_images > 0:
            pct = (self.pages_with_images / self.total_pages * 100) if self.total_pages > 0 else 0
            lines.append(f"   Image Coverage:         {pct:.1f}% of pages")

        lines.append("\n" + "=" * 60)

        return "\n".join(lines)

    def print_summary(self):
        """Print a formatted summary table to console."""
        print(self.format_summary())


def generate_ocr_report(ocr_dir: Path) -> OCRStageReport:
    """
    Generate OCR stage report by analyzing all OCR output files.

    Args:
        ocr_dir: Path to OCR output directory (e.g., {scan_id}/ocr/)

    Returns:
        OCRStageReport with aggregated statistics
    """
    report = OCRStageReport()

    # Find all OCR output files
    ocr_files = sorted(ocr_dir.glob("page_*.json"))

    for ocr_file in ocr_files:
        try:
            with open(ocr_file, 'r') as f:
                page_data = json.load(f)
            report.add_page_data(page_data)
        except Exception as e:
            # Skip files that can't be read
            continue

    report.finalize()
    return report


def save_report(report: OCRStageReport, output_dir: Path):
    """Save report to CSV file.

    Args:
        report: OCRStageReport to save
        output_dir: Directory to save report.csv in
    """
    csv_path = output_dir / "report.csv"

    # Write summary statistics as CSV
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['metric', 'value'])
        writer.writerow(['total_pages', report.total_pages])
        writer.writerow(['total_blocks', report.total_blocks])
        writer.writerow(['total_paragraphs', report.total_paragraphs])
        writer.writerow(['total_images', report.total_images])
        writer.writerow(['total_words', report.total_words])
        writer.writerow(['avg_blocks_per_page', f"{report.avg_blocks_per_page:.1f}"])
        writer.writerow(['avg_paragraphs_per_page', f"{report.avg_paragraphs_per_page:.1f}"])
        writer.writerow(['avg_words_per_page', f"{report.avg_words_per_page:.1f}"])
        writer.writerow(['avg_confidence', f"{report.avg_confidence:.3f}"])
        writer.writerow(['min_confidence', f"{report.min_confidence:.3f}"])
        writer.writerow(['max_confidence', f"{report.max_confidence:.3f}"])
        writer.writerow(['low_confidence_page_count', len(report.low_confidence_pages)])
        writer.writerow(['pages_with_images', report.pages_with_images])
        writer.writerow(['pages_1_2_blocks', report.pages_by_block_count['1-2']])
        writer.writerow(['pages_3_5_blocks', report.pages_by_block_count['3-5']])
        writer.writerow(['pages_6_10_blocks', report.pages_by_block_count['6-10']])
        writer.writerow(['pages_11plus_blocks', report.pages_by_block_count['11+']])
        writer.writerow(['processing_date', report.processing_date or ''])
