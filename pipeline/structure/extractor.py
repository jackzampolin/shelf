#!/usr/bin/env python3
"""
Content Extractor - Phases 3, 6, 7

Uses GPT-4o-mini for mechanical extraction tasks:
- Phase 3: Page number extraction (parallel)
- Phase 6: Footnote extraction
- Phase 7: Bibliography parsing
"""

import sys
import json
import re
from pathlib import Path
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from llm_client import LLMClient


class ContentExtractor:
    """Extract structured content using GPT-4o-mini."""

    def __init__(self):
        self.client = LLMClient()
        self.model = "openai/gpt-4o-mini"

    # =========================================================================
    # Phase 3: Page Number Extraction (parallel)
    # =========================================================================

    def extract_page_numbers(self, pages: List[Dict], document_map: Dict) -> Dict:
        """
        Phase 3: Extract page numbers from all pages in parallel.

        Args:
            pages: List of page dicts
            document_map: Document structure from detector

        Returns:
            Dict with:
                - page_mapping: List of page mapping entries
                - count: Number of pages with book page numbers
                - cost: Total cost in USD
        """
        print("\n" + "="*70)
        print("📖 Phase 3: Page Number Extraction (GPT-4o-mini, parallel)")
        print("="*70)

        print(f"\n🔄 Processing {len(pages)} pages with 30 workers...")

        total_cost = 0.0
        results = []

        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = {
                executor.submit(self._extract_single_page_number, page): page
                for page in pages
            }

            completed = 0
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                total_cost += result['cost']
                completed += 1

                if completed % 50 == 0:
                    print(f"  ✓ Processed {completed}/{len(pages)} pages...")

        # Sort by scan page
        results.sort(key=lambda x: x['scan_page'])

        # Build page mapping with section information
        page_mapping = []
        chapters = document_map.get('body', {}).get('chapters', [])
        front_matter_sections = document_map.get('front_matter', {}).get('sections', [])
        back_matter_sections = document_map.get('back_matter', {}).get('sections', [])

        for result in results:
            scan_page = result['scan_page']
            book_page = result['book_page']

            # Determine section
            section = "unknown"
            section_type = None
            chapter = None

            # Check front matter
            fm = document_map.get('front_matter', {})
            if fm.get('start_page', 0) <= scan_page <= fm.get('end_page', 0):
                section = "front_matter"
                for s in front_matter_sections:
                    if s['start_page'] <= scan_page <= s['end_page']:
                        section_type = s['type']
                        break

            # Check body
            body = document_map.get('body', {})
            if body.get('start_page', 0) <= scan_page <= body.get('end_page', 0):
                section = "body"
                for ch in chapters:
                    if ch['start_page'] <= scan_page <= ch['end_page']:
                        chapter = ch['number']
                        break

            # Check back matter
            bm = document_map.get('back_matter', {})
            if bm.get('start_page', 0) <= scan_page <= bm.get('end_page', 0):
                section = "back_matter"
                for s in back_matter_sections:
                    if s['start_page'] <= scan_page <= s['end_page']:
                        section_type = s['type']
                        break

            mapping_entry = {
                "scan_page": scan_page,
                "book_page": book_page,
                "section": section
            }

            if section_type:
                mapping_entry["section_type"] = section_type
            if chapter:
                mapping_entry["chapter"] = chapter

            page_mapping.append(mapping_entry)

        count = sum(1 for r in results if r['book_page'] is not None)

        print(f"\n✅ Page number extraction complete:")
        print(f"   Pages with numbers: {count}/{len(pages)}")
        print(f"   Cost: ${total_cost:.4f}")

        return {
            'page_mapping': page_mapping,
            'count': count,
            'cost': total_cost
        }

    def _extract_single_page_number(self, page_data: Dict) -> Dict:
        """Extract page number from a single page (called in parallel)."""
        scan_page = page_data['scan_page']
        text = page_data['text']

        # Look at first and last 200 chars (where page numbers usually are)
        header = text[:200]
        footer = text[-200:]

        system_prompt = "Extract page numbers from book text. Page numbers can be arabic (1, 2, 3) or roman (i, ii, iii). Return only the page number or 'none'."

        user_prompt = f"""Extract the page number from this page.

HEADER TEXT:
{header}

FOOTER TEXT:
{footer}

Return ONLY:
- The page number (e.g., "1", "42", "i", "iii", "xvii")
- OR "none" if no page number is visible

Response (page number or 'none'):"""

        try:
            response, usage, cost = self.client.simple_call(
                self.model,
                system_prompt,
                user_prompt,
                temperature=0.0,
                timeout=30
            )

            book_page = response.strip().lower()
            if book_page == 'none':
                book_page = None

            return {
                "scan_page": scan_page,
                "book_page": book_page,
                "cost": cost
            }

        except Exception as e:
            print(f"  ✗ Error extracting page number for scan page {scan_page}: {e}")
            return {
                "scan_page": scan_page,
                "book_page": None,
                "cost": 0.0
            }

    # =========================================================================
    # Phase 6: Footnote Extraction
    # =========================================================================

    def extract_footnotes(self, pages: List[Dict], document_map: Dict) -> Dict:
        """
        Phase 6: Extract footnotes from notes section.

        Args:
            pages: List of page dicts
            document_map: Document structure

        Returns:
            Dict with:
                - footnotes: List of footnote dicts
                - cost: Cost in USD
        """
        print("\n" + "="*70)
        print("📝 Phase 6: Footnote Extraction (GPT-4o-mini)")
        print("="*70)

        # Find notes section
        back_matter_sections = document_map.get('back_matter', {}).get('sections', [])
        notes_section = None
        for section in back_matter_sections:
            if section['type'] == 'notes':
                notes_section = section
                break

        if not notes_section:
            print("  ℹ️  No notes section found, skipping footnote extraction")
            return {'footnotes': [], 'cost': 0.0}

        # Get text from notes section
        notes_text_parts = []
        for page in pages:
            if notes_section['start_page'] <= page['scan_page'] <= notes_section['end_page']:
                notes_text_parts.append(page['text'])

        notes_text = "\n\n".join(notes_text_parts)

        print(f"  📄 Notes section: pages {notes_section['start_page']}-{notes_section['end_page']}")
        print(f"  🔄 Extracting footnotes...")

        system_prompt = """Extract footnotes/endnotes from the notes section. Return as JSON array."""

        user_prompt = f"""Extract all footnotes from this notes section.

NOTES TEXT:
{notes_text}

Return JSON array:
[
  {{
    "note_id": 1,
    "chapter": chapter number (integer),
    "text": "full note text",
    "source_page": scan page where note appears
  }}
]

Return ONLY the JSON array, nothing else."""

        try:
            response, usage, cost = self.client.simple_call(
                self.model,
                system_prompt,
                user_prompt,
                temperature=0.0,
                timeout=120
            )

            # Parse JSON
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                footnotes = json.loads(json_match.group(0))
            else:
                footnotes = json.loads(response)

            print(f"✅ Footnote extraction complete:")
            print(f"   Footnotes: {len(footnotes)}")
            print(f"   Cost: ${cost:.4f}")

            return {'footnotes': footnotes, 'cost': cost}

        except Exception as e:
            print(f"  ✗ Error extracting footnotes: {e}")
            return {'footnotes': [], 'cost': 0.0}

    # =========================================================================
    # Phase 7: Bibliography Parsing
    # =========================================================================

    def parse_bibliography(self, pages: List[Dict], document_map: Dict) -> Dict:
        """
        Phase 7: Parse bibliography into structured entries.

        Args:
            pages: List of page dicts
            document_map: Document structure

        Returns:
            Dict with:
                - bibliography: List of bibliography entry dicts
                - cost: Cost in USD
        """
        print("\n" + "="*70)
        print("📚 Phase 7: Bibliography Parsing (GPT-4o-mini)")
        print("="*70)

        # Find bibliography section
        back_matter_sections = document_map.get('back_matter', {}).get('sections', [])
        biblio_section = None
        for section in back_matter_sections:
            if section['type'] == 'bibliography':
                biblio_section = section
                break

        if not biblio_section:
            print("  ℹ️  No bibliography section found, skipping")
            return {'bibliography': [], 'cost': 0.0}

        # Get text from bibliography section
        biblio_text_parts = []
        for page in pages:
            if biblio_section['start_page'] <= page['scan_page'] <= biblio_section['end_page']:
                biblio_text_parts.append(page['text'])

        biblio_text = "\n\n".join(biblio_text_parts)

        print(f"  📄 Bibliography section: pages {biblio_section['start_page']}-{biblio_section['end_page']}")
        print(f"  🔄 Parsing bibliography...")

        system_prompt = """Parse bibliography entries into structured JSON. Extract author, title, publisher, year, and type (book/article/etc)."""

        user_prompt = f"""Parse this bibliography into structured entries.

BIBLIOGRAPHY TEXT:
{biblio_text}

Return JSON array:
[
  {{
    "id": 1,
    "author": "Author Name",
    "title": "Book or Article Title",
    "publisher": "Publisher Name" (for books),
    "publication": "Publication Name" (for articles),
    "year": year as integer,
    "pages": page count (for books) or null,
    "type": "book" or "article" or "other"
  }}
]

Return ONLY the JSON array, nothing else."""

        try:
            response, usage, cost = self.client.simple_call(
                self.model,
                system_prompt,
                user_prompt,
                temperature=0.0,
                timeout=120
            )

            # Parse JSON
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                bibliography = json.loads(json_match.group(0))
            else:
                bibliography = json.loads(response)

            print(f"✅ Bibliography parsing complete:")
            print(f"   Entries: {len(bibliography)}")
            print(f"   Cost: ${cost:.4f}")

            return {'bibliography': bibliography, 'cost': cost}

        except Exception as e:
            print(f"  ✗ Error parsing bibliography: {e}")
            return {'bibliography': [], 'cost': 0.0}
