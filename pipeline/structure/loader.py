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
        """Extract text from body regions only, excluding headers/footers."""
        # Get the best available text (agent4 fixes > corrected > raw)
        llm_proc = data.get('llm_processing', {})
        agent4_fixes = llm_proc.get('agent4_fixes', {})

        # Use fixed text if available, otherwise corrected text
        full_text = agent4_fixes.get('fixed_text') or llm_proc.get('corrected_text', '')

        if not full_text:
            return ''

        # Get regions - filter to body text only (exclude headers, footers, page numbers)
        regions = data.get('regions', [])
        if not regions:
            # No region info - return full text as fallback
            return full_text

        # Extract text from body regions only
        body_text_parts = []
        for region in sorted(regions, key=lambda r: r.get('reading_order', 0)):
            region_type = region.get('type', 'body')
            # Include body, caption, footnote - exclude header, footer, page_number
            if region_type in ['body', 'caption', 'footnote']:
                region_text = region.get('text', '')
                if region_text:
                    body_text_parts.append(region_text)

        # If we have body regions, use them; otherwise fall back to full text
        return '\n\n'.join(body_text_parts) if body_text_parts else full_text

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
