"""
Verify Agent - Phase 1 of Structure Stage

Verifies extraction quality by checking:
1. Word count (should be 85-95% of original after header removal)
2. Content preservation (no substantive text lost)
3. Structure integrity (paragraph breaks maintained)
"""

import json
from typing import Dict, List, Any
from llm_client import call_llm


def count_words(text: str) -> int:
    """Count words in text."""
    if not text:
        return 0
    return len(text.split())


def verify_extraction(original_pages: List[Dict], extraction_result: Dict) -> Dict[str, Any]:
    """
    Verify extraction quality.

    Args:
        original_pages: List of original page dicts
        extraction_result: Result from extract_agent

    Returns:
        Dict with:
        - quality_score: 0.0-1.0
        - issues: List of issues found
        - confidence: "high" | "medium" | "low"
        - word_count_ok: bool
        - needs_review: bool
    """

    # Calculate original word count from corrected_text or regions
    original_word_count = 0
    for page in original_pages:
        if 'llm_processing' in page and 'corrected_text' in page['llm_processing']:
            text = page['llm_processing']['corrected_text']
            original_word_count += count_words(text)
        else:
            # Fallback: count words in regions
            for region in page.get('regions', []):
                if region.get('type') in ['header', 'body', 'caption', 'footnote']:
                    original_word_count += count_words(region.get('text', ''))

    extracted_word_count = extraction_result.get('word_count', 0)

    # Get sample of original and extracted text
    original_sample = ""
    if original_pages:
        first_page = original_pages[0]
        if 'llm_processing' in first_page and 'corrected_text' in first_page['llm_processing']:
            original_sample = first_page['llm_processing']['corrected_text'][:500]
        else:
            regions = first_page.get('regions', [])
            if regions:
                original_sample = regions[0].get('text', '')[:500]

    extracted_sample = extraction_result.get('clean_text', '')[:500]

    system_prompt = """You are a quality verification specialist.

<task>
Verify that text extraction preserved substantive content while removing only repetitive headers/footers.
</task>

<verification_checklist>
1. Word count reasonable? (varies by book type - some have heavy headers, some minimal)
   - Red flag: >40% loss (likely removing body text by mistake)
   - Red flag: <5% loss (likely not removing headers at all)
   - Acceptable range varies: academic (60-85%), fiction (90-98%), etc.
2. No substantive content lost? (compare samples)
3. Paragraph structure preserved?
4. Only repetitive elements removed?
5. No unauthorized changes or "improvements"?
</verification_checklist>

<confidence_scoring>
- high: Samples match well, structure preserved, word count makes sense for this book type
- medium: Minor concerns, but generally acceptable
- low: Significant content loss, structural issues, or suspicious word count
</confidence_scoring>

<critical>
NO markdown code blocks (```json).
NO explanatory text before or after the JSON.
Start immediately with the opening brace {
</critical>"""

    user_prompt = f"""Verify this extraction:

<original_stats>
Pages: {len(original_pages)}
Word count: ~{original_word_count}
Sample (first 500 chars):
{original_sample}
</original_stats>

<extracted_stats>
Word count: {extracted_word_count}
Running header pattern removed: {extraction_result.get('running_header_pattern', 'none')}
Paragraphs extracted: {len(extraction_result.get('paragraphs', []))}
Sample (first 500 chars):
{extracted_sample}
</extracted_stats>

<verification_task>
Check if extraction preserved content while removing headers:
1. Word count ratio: {extracted_word_count}/{original_word_count} = {extracted_word_count/original_word_count if original_word_count > 0 else 0:.2%}
2. Evaluate if this ratio makes sense:
   - >95%: Check if headers were actually removed
   - 60-95%: Likely reasonable (depends on header density)
   - <60%: Check if body text was incorrectly removed
3. Compare samples to verify content preservation (this is more important than the ratio)
</verification_task>

<output_schema>
{{
  "quality_score": 0.95,
  "issues": ["issue description if any"],
  "confidence": "high" | "medium" | "low",
  "word_count_ok": true,
  "word_count_ratio": 0.92,
  "needs_review": false,
  "review_reason": "explanation if needs_review is true"
}}
</output_schema>"""

    # Call LLM
    try:
        response, usage, cost = call_llm(
            model="openai/gpt-4o-mini",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1
        )

        # Parse response
        import re
        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            json_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                raise ValueError(f"Failed to parse verification response as JSON")

        # Add calculated fields
        if original_word_count > 0:
            result['word_count_ratio'] = extracted_word_count / original_word_count
        else:
            result['word_count_ratio'] = 0

        # Set defaults
        result.setdefault('quality_score', 0.8)
        result.setdefault('issues', [])
        result.setdefault('confidence', 'medium')
        result.setdefault('word_count_ok', True)
        result.setdefault('needs_review', False)
        result.setdefault('review_reason', '')

        return result

    except Exception as e:
        # Return error result
        return {
            'quality_score': 0.0,
            'issues': [f"Verification failed: {str(e)}"],
            'confidence': 'low',
            'word_count_ok': False,
            'word_count_ratio': extracted_word_count / original_word_count if original_word_count > 0 else 0,
            'needs_review': True,
            'review_reason': f"Verification error: {str(e)}"
        }


def verify_extraction_simple(original_pages: List[Dict], extraction_result: Dict) -> Dict[str, Any]:
    """
    Simple verification without LLM (fallback or for testing).

    Just checks word counts and basic heuristics.
    """
    # Calculate original word count
    original_word_count = 0
    for page in original_pages:
        if 'llm_processing' in page and 'corrected_text' in page['llm_processing']:
            text = page['llm_processing']['corrected_text']
            original_word_count += count_words(text)
        else:
            for region in page.get('regions', []):
                if region.get('type') in ['header', 'body', 'caption', 'footnote']:
                    original_word_count += count_words(region.get('text', ''))

    extracted_word_count = extraction_result.get('word_count', 0)

    # Check word count ratio
    if original_word_count > 0:
        ratio = extracted_word_count / original_word_count
    else:
        ratio = 0

    # Determine if acceptable (flexible range based on red flags)
    word_count_ok = 0.60 <= ratio <= 0.98  # Wide range - most books fall here
    quality_score = ratio if word_count_ok else max(0, ratio - 0.2)

    issues = []
    if ratio < 0.60:
        issues.append(f"Excessive content loss: {ratio:.1%} retained (red flag: >40% loss)")
    elif ratio > 0.98:
        issues.append(f"Minimal text removed: {ratio:.1%} retained (check if headers were removed)")

    return {
        'quality_score': quality_score,
        'issues': issues,
        'confidence': 'high' if word_count_ok else 'low',
        'word_count_ok': word_count_ok,
        'word_count_ratio': ratio,
        'needs_review': not word_count_ok,
        'review_reason': issues[0] if issues else ''
    }
