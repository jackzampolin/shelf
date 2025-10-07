"""
Extract Agent - Phase 1 of Structure Stage

Removes running headers/footers while preserving body text.
Detects chapter markers and footnotes organically during extraction.
"""

import json
import re
from typing import Dict, List, Any
from llm_client import call_llm
from config import Config


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

4. PAGE BOUNDARIES (critical for consistency):
   - Text often flows across page breaks - stitch it together naturally
   - Assign paragraphs to pages based on where they START, not where they end
   - If a paragraph spans pages, attribute it to the first page
   - At page boundaries, ask: "Does this header/text make sense HERE?"
   - Running headers (e.g., "CHAPTER 3" at top) should be removed EVEN if they appear mid-batch
   - Section headers that introduce new content should be KEPT
   - When uncertain about a page boundary, preserve the text (over-preserve vs under-preserve)

5. DETECT structural markers (if present):
   - Chapter/section divisions (format varies: numbered, titled, or both)
   - Footnote references
   - Part divisions
   - Note: Some books have NO chapters - that's fine

6. OUTPUT requirements:
   - Each paragraph as separate entry with type
   - Types: "body" (main text), "footnote", "caption", "heading", "quote"
   - Track scan_page as INTEGER (e.g., 77, not "PAGE 77")
   - Count total words in clean text
</instructions>

<output_schema>
{{
  "clean_text": "all extracted text with paragraphs separated by \\n\\n",
  "paragraphs": [
    {{
      "text": "paragraph content",
      "scan_page": 77,
      "type": "body"
    }}
  ],
  "running_header_pattern": "pattern found (null if none)",
  "chapter_markers": [
    {{"chapter_number": 3, "title": "Chapter Title", "scan_page": 75}}
  ],
  "footnotes": [
    {{"number": "1", "text": "footnote text", "scan_page": 76}}
  ]
}}

CRITICAL: scan_page MUST be an integer (77), NOT a string ("PAGE 77").
Note: chapter_markers and footnotes arrays may be empty if not present. That's expected.
DO NOT include word_count - this will be calculated automatically.
</output_schema>"""

    # Call LLM (with extended timeout for large batches)
    response, usage, cost = call_llm(
        model=Config.EXTRACT_MODEL,
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
    required_fields = ['clean_text', 'paragraphs']
    for field in required_fields:
        if field not in result:
            raise ValueError(f"Missing required field in extraction result: {field}")

    # Set defaults for optional fields
    result.setdefault('running_header_pattern', None)
    result.setdefault('chapter_markers', [])
    result.setdefault('footnotes', [])

    # Calculate word count in Python (don't trust LLM to count)
    clean_text = result.get('clean_text', '')
    result['word_count'] = len(clean_text.split()) if clean_text else 0

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
