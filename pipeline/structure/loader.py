#!/usr/bin/env python3
"""
Page Loader - Phase 0

Loads and cleans corrected pages from disk.
"""

import json
import re
from pathlib import Path
from typing import List, Dict


class PageLoader:
    """Load and clean corrected pages."""

    def __init__(self, book_dir: Path):
        self.book_dir = book_dir
        self.corrected_dir = book_dir / "corrected"

    def clean_text(self, text: str) -> str:
        """Remove correction markers and LLM artifacts."""
        # Remove correction markers
        text = re.sub(r'\[CORRECTED:\d+\]', '', text)
        text = re.sub(r'\[FIXED:A4-\d+\]', '', text)

        # Remove LLM instruction artifacts
        text = re.sub(r"Here's the text with.*?marked:", '', text, flags=re.IGNORECASE)
        text = re.sub(r"Here are the.*?corrections:", '', text, flags=re.IGNORECASE)

        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        text = text.strip()

        return text

    def extract_body_text(self, data: Dict) -> str:
        """
        Extract corrected text from body regions only, excluding headers/footers.

        Pipeline Architecture (as of region correction fix):
        1. OCR stage creates regions with raw text
        2. Correction stage updates regions with corrected text + [CORRECTED:id] markers
        3. Fix stage updates regions with fixes + [FIXED:A4-id] markers
        4. Structure stage extracts body regions (this method)

        This ensures:
        - Headers/footers/page numbers are excluded via region type filtering
        - Corrections and fixes are applied to region text
        - No need to use full_text (which includes headers)
        """
        regions = data.get('regions', [])

        if not regions:
            # Should not happen - all pages should have regions from OCR
            # If it does, return empty rather than falling back to full_text with headers
            return ''

        # Extract text from body regions only
        # These regions have corrections/fixes applied by correction and fix stages
        body_text_parts = []
        for region in sorted(regions, key=lambda r: r.get('reading_order', 0)):
            region_type = region.get('type', 'body')

            # Include body, caption, footnote - exclude header, footer, page_number
            if region_type in ['body', 'caption', 'footnote']:
                region_text = region.get('text', '')
                if region_text:
                    body_text_parts.append(region_text)

        if not body_text_parts:
            # Page has no body content (e.g., blank page, image-only page, title page)
            return ''

        return '\n\n'.join(body_text_parts)

    def load_pages(self) -> List[Dict]:
        """Load all corrected pages, filtering headers from region data."""
        print("\n" + "="*70)
        print("📄 Loading Pages (filtering headers via OCR regions)")
        print("="*70)

        pages = []
        page_files = sorted(self.corrected_dir.glob("page_*.json"))

        for page_file in page_files:
            if 'metadata' in page_file.name:
                continue

            try:
                with open(page_file) as f:
                    data = json.load(f)

                page_num = data.get('page_number')
                raw_text = self.extract_body_text(data)

                if not raw_text:
                    continue

                cleaned_text = self.clean_text(raw_text)

                pages.append({
                    "scan_page": page_num,
                    "text": cleaned_text
                })

                if page_num % 100 == 0:
                    print(f"  ✓ Loaded {len(pages)} pages...")

            except Exception as e:
                print(f"  ✗ Error loading {page_file.name}: {e}")

        print(f"\n✅ Loaded {len(pages)} pages")
        return pages
