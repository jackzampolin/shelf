"""
Extract Agent - Phase 1 of Structure Stage

Removes running headers/footers while preserving body text.
Detects chapter markers and footnotes organically during extraction.
"""

import json
import re
from typing import Dict, List, Any
from llm_client import call_llm


def concatenate_pages(pages: List[Dict]) -> str:
    """Concatenate page texts with page number markers."""
    page_texts = []

    for page in pages:
        page_num = page['page_number']

        # Use corrected_text if available, otherwise concatenate regions
        if 'llm_processing' in page and 'corrected_text' in page['llm_processing']:
            text = page['llm_processing']['corrected_text']
        else:
            # Fallback: concatenate regions in reading order
            regions = sorted(page.get('regions', []),
                           key=lambda r: r.get('reading_order', 0))
            text = '\n\n'.join(r['text'] for r in regions)

        page_texts.append(f"[PAGE {page_num}]\n{text}\n")

    return '\n'.join(page_texts)


def extract_batch(pages: List[Dict]) -> Dict[str, Any]:
    """
    Extract clean body text from a batch of pages.

    Args:
        pages: List of page dicts (typically 10 pages)

    Returns:
        Dict with:
        - clean_text: Extracted text with headers removed
        - paragraphs: List of paragraph dicts with provenance
        - running_header_pattern: Pattern identified and removed
        - chapter_markers: List of chapter markers found
        - footnotes: List of footnotes found
        - word_count: Total words in clean text
        - scan_pages: List of page numbers processed
    """

    if not pages:
        raise ValueError("No pages provided to extract_batch")

    # Concatenate pages with markers
    batch_text = concatenate_pages(pages)

    start_page = pages[0]['page_number']
    end_page = pages[-1]['page_number']

    system_prompt = """You are a book text extractor.

<task>
Extract clean body text from scanned pages, removing repetitive headers/footers while preserving all substantive content.
</task>

<rules>
1. Be CONSERVATIVE: Only remove text that clearly repeats across multiple pages
2. When in doubt, KEEP the text (better to over-preserve than lose content)
3. Preserve ALL substantive content (body text, footnotes, captions, quotes)
4. Maintain paragraph structure
5. Note structural elements (chapters, sections, footnotes) organically
6. Do NOT make assumptions about book structure - each book is different
</rules>

<critical>
NO markdown code blocks (```json).
NO explanatory text before or after the JSON.
Start immediately with the opening brace {
</critical>"""

    user_prompt = f"""Extract clean body text from pages {start_page}-{end_page}.

<input>
{batch_text}
</input>

<instructions>
1. REMOVE repetitive elements (only if they appear on multiple pages):
   - Running headers (e.g., page numbers, book title, chapter name at top of pages)
   - Page numbers (scan numbers or original book page numbers)
   - Repetitive footers
   - DO NOT remove if uncertain - err on side of preservation

2. PRESERVE all substantive content:
   - All body text paragraphs
   - Footnotes (may be numbered, lettered, or use symbols)
   - Image captions
   - Block quotes
   - Headings (chapter titles, section headers, etc.)
   - Epigraphs, dedications
   - ANY text that varies from page to page

3. STRUCTURE preservation:
   - Maintain paragraph breaks (separate with \\n\\n)
   - Keep reading order intact

4. DETECT structural markers (if present):
   - Chapter/section divisions (format varies: numbered, titled, or both)
   - Footnote references
   - Part divisions
   - Note: Some books have NO chapters - that's fine

5. OUTPUT requirements:
   - Each paragraph as separate entry with type
   - Types: "body" (main text), "footnote", "caption", "heading", "quote"
   - Track scan_page for each element
   - Count total words in clean text
</instructions>

<output_schema>
{{
  "clean_text": "all extracted text with paragraphs separated by \\n\\n",
  "paragraphs": [
    {{
      "text": "paragraph content",
      "scan_page": PAGE_NUMBER,
      "type": "body" | "footnote" | "caption" | "heading" | "quote"
    }}
  ],
  "running_header_pattern": "pattern found (null if none)",
  "chapter_markers": [
    {{"chapter_number": N, "title": "...", "scan_page": PAGE}}
  ],
  "footnotes": [
    {{"number": "1", "text": "...", "scan_page": PAGE}}
  ],
  "word_count": TOTAL_WORDS_IN_CLEAN_TEXT
}}

Note: chapter_markers and footnotes arrays may be empty if not present. That's expected.
</output_schema>"""

    # Call LLM (with extended timeout for large batches)
    response, usage, cost = call_llm(
        model="openai/gpt-4o-mini",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.1,
        timeout=300  # 5 minutes for 10-page batches
    )

    # Parse response
    try:
        result = json.loads(response)
    except json.JSONDecodeError as e:
        # Try to extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', response, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(1))
        else:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}\nResponse: {response[:500]}")

    # Add scan_pages list
    result['scan_pages'] = [p['page_number'] for p in pages]

    # Validate result
    required_fields = ['clean_text', 'paragraphs', 'word_count']
    for field in required_fields:
        if field not in result:
            raise ValueError(f"Missing required field in extraction result: {field}")

    # Set defaults for optional fields
    result.setdefault('running_header_pattern', None)
    result.setdefault('chapter_markers', [])
    result.setdefault('footnotes', [])

    return result


def extract_batch_safe(pages: List[Dict]) -> Dict[str, Any]:
    """
    Safe wrapper around extract_batch with error handling.

    Returns extraction result or error dict.
    """
    try:
        return extract_batch(pages)
    except Exception as e:
        return {
            'error': str(e),
            'scan_pages': [p['page_number'] for p in pages],
            'clean_text': '',
            'paragraphs': [],
            'word_count': 0,
            'running_header_pattern': None,
            'chapter_markers': [],
            'footnotes': []
        }
