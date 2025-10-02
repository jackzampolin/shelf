#!/usr/bin/env python3
"""
Structure Detector - Phase 1-2

Uses Claude Sonnet 4.5 to detect document structure:
- Front matter, body, back matter boundaries
- Chapter detection with semantic understanding
- Section type classification
"""

import sys
import json
import re
from pathlib import Path
from typing import List, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from llm_client import LLMClient


class StructureDetector:
    """Detect document structure using Claude Sonnet 4.5."""

    def __init__(self, model: str = None):
        self.client = LLMClient()
        self.model = model or "anthropic/claude-sonnet-4.5"
        self.logger = None  # Will be set by parent BookStructurer

    def detect_structure(self, pages: List[Dict]) -> Dict:
        """
        Phase 1-2: Detect document boundaries and chapters.

        Args:
            pages: List of page dicts with 'scan_page' and 'text'

        Returns:
            Dict with:
                - document_map: Complete structure
                - chapters: List of chapter dicts
                - front_matter_sections: List of front matter sections
                - back_matter_sections: List of back matter sections
                - usage: Token usage stats
                - cost: Cost in USD
        """
        print("\n" + "="*70)
        print("🧠 Phase 1-2: Document Structure Detection (Claude Sonnet 4.5)")
        print("="*70)

        # Build full book text with page markers
        full_text_parts = []
        for page in pages:
            full_text_parts.append(f"<!-- PAGE {page['scan_page']} -->")
            full_text_parts.append(page['text'])
            full_text_parts.append("")

        full_text = "\n".join(full_text_parts)

        token_estimate = len(full_text.split())
        print(f"\n📊 Book stats:")
        print(f"   Pages: {len(pages)}")
        print(f"   Estimated tokens: ~{token_estimate:,}")
        print(f"   Model: {self.model}")
        print(f"\n🔄 Analyzing document structure...")
        sys.stdout.flush()

        system_prompt = """You are an expert book structure analyst. Analyze the complete book and identify:

1. Document boundaries (front matter, body, back matter)
2. Chapter structure within body
3. Section types in front/back matter

Return only valid JSON, no other text."""

        user_prompt = f"""Analyze this complete book and identify its structure.

COMPLETE BOOK TEXT:
{full_text}

Return JSON with this exact structure:
{{
  "book": {{
    "title": "extracted book title",
    "author": "extracted author name",
    "publisher": "publisher if found",
    "year": null or year as integer,
    "isbn": "ISBN if found",
    "total_scan_pages": {len(pages)}
  }},
  "front_matter": {{
    "start_page": scan page number,
    "end_page": scan page number,
    "sections": [
      {{"type": "title_page", "start_page": X, "end_page": Y}},
      {{"type": "copyright", "start_page": X, "end_page": Y}},
      {{"type": "dedication", "start_page": X, "end_page": Y}},
      {{"type": "contents", "start_page": X, "end_page": Y}},
      {{"type": "introduction", "start_page": X, "end_page": Y}}
    ]
  }},
  "body": {{
    "start_page": scan page number where main content begins,
    "end_page": scan page number where main content ends,
    "footnote_style": "inline_footnotes" or "chapter_endnotes" or "book_endnotes",
    "chapters": [
      {{
        "number": 1,
        "title": "actual chapter title from text",
        "start_page": scan page,
        "end_page": scan page,
        "summary": "2-3 sentence summary of chapter content"
      }}
    ]
  }},
  "back_matter": {{
    "start_page": scan page number,
    "end_page": scan page number,
    "sections": [
      {{"type": "epilogue", "start_page": X, "end_page": Y}},
      {{"type": "acknowledgments", "start_page": X, "end_page": Y}},
      {{"type": "notes", "start_page": X, "end_page": Y}},
      {{"type": "bibliography", "start_page": X, "end_page": Y}},
      {{"type": "index", "start_page": X, "end_page": Y}}
    ]
  }}
}}

CRITICAL REQUIREMENTS:
1. Detect TRUE boundaries by reading content (not just guessing)
2. Page markers like "<!-- PAGE 42 -->" show scan page numbers
3. Front matter typically has roman numerals or no page numbers
4. Body is the main narrative content with chapters
5. Back matter includes notes, bibliography, index
6. Chapter summaries should capture key events/arguments
7. Section types must be from this list: title_page, copyright, dedication, epigraph, contents, foreword, preface, acknowledgments, introduction, prologue, epilogue, conclusion, afterword, appendix, notes, bibliography, index, glossary, about_author

Return ONLY the JSON structure."""

        try:
            response, usage, cost = self.client.simple_call(
                self.model,
                system_prompt,
                user_prompt,
                temperature=0.0,
                stream=True
            )

            print("\n✅ Structure detection complete! Parsing JSON...\n")
            sys.stdout.flush()

            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                structure = json.loads(json_match.group(0))
            else:
                structure = json.loads(response)

            chapters = structure.get('body', {}).get('chapters', [])
            front_matter_sections = structure.get('front_matter', {}).get('sections', [])
            back_matter_sections = structure.get('back_matter', {}).get('sections', [])

            print(f"✅ Document structure detected:")
            print(f"   Chapters: {len(chapters)}")
            print(f"   Front matter sections: {len(front_matter_sections)}")
            print(f"   Back matter sections: {len(back_matter_sections)}")
            print(f"   Cost: ${cost:.4f}")

            return {
                'document_map': structure,
                'chapters': chapters,
                'front_matter_sections': front_matter_sections,
                'back_matter_sections': back_matter_sections,
                'usage': usage,
                'cost': cost
            }

        except Exception as e:
            print(f"\n❌ Structure detection failed: {e}")
            print(f"   Falling back to simple structure...")

            # Fallback: treat entire book as body
            structure = {
                "book": {
                    "title": "Unknown",
                    "author": "Unknown",
                    "total_scan_pages": len(pages)
                },
                "front_matter": {"sections": []},
                "body": {
                    "start_page": 1,
                    "end_page": len(pages),
                    "chapters": [{
                        "number": 1,
                        "title": "Full Book",
                        "start_page": 1,
                        "end_page": len(pages),
                        "summary": "Complete book content"
                    }]
                },
                "back_matter": {"sections": []}
            }

            return {
                'document_map': structure,
                'chapters': structure['body']['chapters'],
                'front_matter_sections': [],
                'back_matter_sections': [],
                'usage': {},
                'cost': 0.0
            }
