"""
Verify Agent - Phase 1 of Structure Stage

Verifies extraction quality by checking:
1. Word count (should be 85-95% of original after header removal)
2. Content preservation (no substantive text lost)
3. Structure integrity (paragraph breaks maintained)
"""

import json
from typing import Dict, List, Any
from llm_client import LLMClient
from config import Config


def count_words(text: str) -> int:
    """Count words in text."""
    if not text:
        return 0
    return len(text.split())


def verify_extraction(original_pages: List[Dict], extraction_result: Dict) -> Dict[str, Any]:
    """
    Verify extraction quality using LLM to compare FULL original vs extracted text.

    With 3-page batches, we can send complete text to LLM for thorough verification.

    Args:
        original_pages: List of original page dicts (typically 3 pages)
        extraction_result: Result from extract_agent

    Returns:
        Dict with:
        - quality_score: 0.0-1.0
        - issues: List of issues found
        - confidence: "high" | "medium" | "low"
        - needs_review: bool
        - headers_removed_correctly: bool
        - body_text_preserved: bool
    """

    # Build FULL original text (what the extract_agent saw)
    original_texts = []
    for page in original_pages:
        page_num = page['page_number']

        # Get corrected_text if available (this is what extract_agent receives)
        if 'llm_processing' in page and 'corrected_text' in page['llm_processing']:
            text = page['llm_processing']['corrected_text']
        else:
            # Fallback: concatenate regions
            regions = sorted(page.get('regions', []), key=lambda r: r.get('reading_order', 0))
            text = '\n\n'.join(r['text'] for r in regions if 'text' in r)

        original_texts.append(f"[PAGE {page_num}]\n{text}")

    original_full_text = '\n\n'.join(original_texts)
    extracted_text = extraction_result.get('clean_text', '')

    # Calculate word counts using Python (facts for LLM)
    original_word_count = count_words(original_full_text)
    extracted_word_count = count_words(extracted_text)
    word_count_ratio = extracted_word_count / original_word_count if original_word_count > 0 else 0

    system_prompt = """You are a text extraction quality verification specialist.

<task>
Compare the COMPLETE original text (with headers) to the COMPLETE extracted clean text.
Verify that headers/footers were removed correctly while preserving all body content.
</task>

<verification_checklist>
1. Headers removed correctly?
   - Check if repetitive page numbers removed (e.g., "62", "63")
   - Check if running headers removed (e.g., "CHAPTER 3", "PRACTICAL POLITICS")
   - Check if book title headers removed (e.g., "THEODORE ROOSEVELT—AN AUTOBIOGRAPHY")

2. Body text preserved?
   - All paragraphs present?
   - No missing sentences?
   - Text flows naturally?

3. Word count ratio makes sense?
   - Given what you see removed, does the ratio seem appropriate?
   - Heavy headers → lower ratio (60-80%) is acceptable
   - Light headers → higher ratio (85-95%) expected

4. Overall quality
   - Paragraph structure maintained?
   - No unauthorized changes?
   - Reading flow intact?
</verification_checklist>

<critical>
NO markdown code blocks (```json).
NO explanatory text before or after the JSON.
Start immediately with the opening brace {
</critical>"""

    user_prompt = f"""Verify this extraction by comparing COMPLETE original to COMPLETE extracted text.

<original_text>
Pages: {len(original_pages)}
Word count: {original_word_count}

FULL TEXT:
{original_full_text}
</original_text>

<extracted_text>
Word count: {extracted_word_count}
Word count ratio: {word_count_ratio:.1%} (extracted/original)

FULL TEXT:
{extracted_text}
</extracted_text>

<verification_task>
Compare the COMPLETE texts above:
1. Were headers removed correctly? List what was removed.
2. Was body text preserved completely? Any missing content?
3. Does the {word_count_ratio:.1%} ratio make sense given what was removed?
4. Overall assessment: Is this a good extraction?
</verification_task>

<output_schema>
{{
  "quality_score": 0.95,
  "headers_removed_correctly": true,
  "body_text_preserved": true,
  "issues": ["list any problems found"],
  "headers_identified": ["list headers that were removed"],
  "confidence": "high" | "medium" | "low",
  "needs_review": false,
  "review_reason": "explanation if needs_review is true"
}}
</output_schema>"""

    # Define JSON parser with markdown fallback
    def parse_verify_response(response):
        import re
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            json_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            else:
                raise ValueError(f"Failed to parse verification response as JSON")

    # Call LLM with automatic JSON retry
    try:
        llm_client = LLMClient()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        result, usage, cost = llm_client.call_with_json_retry(
            model=Config.EXTRACT_MODEL,
            messages=messages,
            json_parser=parse_verify_response,
            temperature=0.1,
            max_retries=2
        )

        # Add Python-calculated metrics
        result['word_count_ratio'] = word_count_ratio
        result['original_word_count'] = original_word_count
        result['extracted_word_count'] = extracted_word_count

        # Set defaults
        result.setdefault('quality_score', 0.8)
        result.setdefault('issues', [])
        result.setdefault('confidence', 'medium')
        result.setdefault('headers_removed_correctly', True)
        result.setdefault('body_text_preserved', True)
        result.setdefault('needs_review', False)
        result.setdefault('review_reason', '')
        result.setdefault('headers_identified', [])

        return result

    except Exception as e:
        # Return error result
        return {
            'quality_score': 0.0,
            'issues': [f"Verification failed: {str(e)}"],
            'confidence': 'low',
            'headers_removed_correctly': False,
            'body_text_preserved': False,
            'word_count_ratio': word_count_ratio,
            'original_word_count': original_word_count,
            'extracted_word_count': extracted_word_count,
            'needs_review': True,
            'review_reason': f"Verification error: {str(e)}"
        }
