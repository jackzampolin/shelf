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

    def load_pages(self) -> List[Dict]:
        """Load all corrected pages."""
        print("\n" + "="*70)
        print("📄 Loading Pages")
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
                raw_text = data.get('llm_processing', {}).get('corrected_text', '')

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
