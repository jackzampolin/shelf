"""
Reconcile Agent - Phase 1 of Structure Stage

Handles overlapping page regions between adjacent batches.
Uses consensus when extractions match, LLM arbitration when they differ.
"""

import json
from typing import Dict, List, Any, Tuple
from difflib import SequenceMatcher
from llm_client import LLMClient
from config import Config


def text_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity ratio between two texts.

    Returns: 0.0 to 1.0, where 1.0 is identical
    """
    if not text1 or not text2:
        return 0.0
    return SequenceMatcher(None, text1, text2).ratio()


def extract_overlap_text(extraction_result: Dict, overlap_pages: List[int]) -> str:
    """
    Extract text for specific pages from an extraction result.

    Args:
        extraction_result: Result from extract_agent
        overlap_pages: List of page numbers to extract

    Returns:
        Text from those pages only
    """
    overlap_pages_set = set(overlap_pages)

    # Get paragraphs from overlap pages only
    overlap_paragraphs = [
        p for p in extraction_result.get('paragraphs', [])
        if p.get('scan_page') in overlap_pages_set
    ]

    # Concatenate paragraph texts
    return '\n\n'.join(p['text'] for p in overlap_paragraphs)


def reconcile_overlaps(batch1_result: Dict, batch2_result: Dict,
                       overlap_pages: List[int],
                       similarity_threshold: float = 0.95) -> Dict[str, Any]:
    """
    Reconcile overlapping pages between two batch extractions.

    Args:
        batch1_result: Extraction result from first batch
        batch2_result: Extraction result from second batch
        overlap_pages: List of page numbers that overlap
        similarity_threshold: Minimum similarity to accept consensus (default 0.95)

    Returns:
        Dict with:
        - status: "consensus" | "disagreement"
        - overlap_text: Reconciled text for overlap region
        - similarity: Similarity score
        - confidence: "high" | "medium" | "low"
        - resolution_method: "consensus" | "llm_arbitration" | "batch1_preferred"
    """

    # Extract overlap text from each batch
    batch1_overlap = extract_overlap_text(batch1_result, overlap_pages)
    batch2_overlap = extract_overlap_text(batch2_result, overlap_pages)

    # Calculate similarity
    similarity = text_similarity(batch1_overlap, batch2_overlap)

    # If extractions match closely, use consensus
    if similarity >= similarity_threshold:
        return {
            'status': 'consensus',
            'overlap_text': batch1_overlap,  # Use either, they're nearly identical
            'similarity': similarity,
            'confidence': 'high',
            'resolution_method': 'consensus',
            'overlap_pages': overlap_pages
        }

    # If significantly different, use LLM arbitration
    else:
        # For now, use batch1 and flag for review
        # TODO: Implement LLM arbitration if needed
        return {
            'status': 'disagreement',
            'overlap_text': batch1_overlap,  # Default to batch1
            'similarity': similarity,
            'confidence': 'low',
            'resolution_method': 'batch1_preferred',
            'overlap_pages': overlap_pages,
            'needs_review': True,
            'review_reason': f"Batch extractions differ significantly: {similarity:.1%} similarity"
        }


def reconcile_overlaps_with_llm(batch1_result: Dict, batch2_result: Dict,
                                overlap_pages: List[int]) -> Dict[str, Any]:
    """
    Reconcile overlapping pages using LLM arbitration.

    This is called when automatic reconciliation fails (similarity < threshold).

    Args:
        batch1_result: Extraction result from first batch
        batch2_result: Extraction result from second batch
        overlap_pages: List of page numbers that overlap

    Returns:
        Dict with reconciled overlap information
    """

    batch1_overlap = extract_overlap_text(batch1_result, overlap_pages)
    batch2_overlap = extract_overlap_text(batch2_result, overlap_pages)

    system_prompt = """You are a text reconciliation specialist.

<task>
Two extractions of the same pages differ. Determine which is more accurate or merge them.
</task>

<rules>
1. Compare both extractions carefully
2. Look for differences in:
   - Header removal (which removed more accurately?)
   - Content preservation (which kept more body text?)
   - Paragraph breaks (which maintained structure better?)
3. Choose the better extraction OR create a merged version
4. Explain your reasoning
</rules>

<critical>
NO markdown code blocks (```json).
NO explanatory text before or after the JSON.
Start immediately with the opening brace {
</critical>"""

    user_prompt = f"""Reconcile these two extractions of pages {overlap_pages[0]}-{overlap_pages[-1]}:

<batch1_extraction>
{batch1_overlap}
</batch1_extraction>

<batch2_extraction>
{batch2_overlap}
</batch2_extraction>

<instructions>
Compare both extractions and decide:
1. Use batch1 (if it's more accurate)
2. Use batch2 (if it's more accurate)
3. Create merged version (if both have issues)
</instructions>

<output_schema>
{{
  "best_extraction": "batch1" | "batch2" | "merged",
  "reconciled_text": "the text to use",
  "reason": "explanation of choice",
  "confidence": "high" | "medium" | "low"
}}
</output_schema>"""

    # Define JSON parser with markdown fallback
    def parse_reconcile_response(response):
        import re
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            json_match = re.search(r'```(?:json)?\s*(\{.*\})\s*```', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))
            else:
                raise ValueError("Failed to parse LLM reconciliation response")

    # Overlap boundary reconciliation with automatic JSON retry
    try:
        llm_client = LLMClient()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        result, usage, cost = llm_client.call_with_json_retry(
            model=Config.EXTRACT_MODEL,
            messages=messages,
            json_parser=parse_reconcile_response,
            temperature=0.1,
            max_retries=2
        )

        # Build return dict
        return {
            'status': 'llm_arbitrated',
            'overlap_text': result.get('reconciled_text', batch1_overlap),
            'similarity': text_similarity(batch1_overlap, batch2_overlap),
            'confidence': result.get('confidence', 'medium'),
            'resolution_method': 'llm_arbitration',
            'overlap_pages': overlap_pages,
            'arbitration_reason': result.get('reason', ''),
            'chosen_extraction': result.get('best_extraction', 'batch1')
        }

    except Exception as e:
        # Fallback: use batch1
        return {
            'status': 'error',
            'overlap_text': batch1_overlap,
            'similarity': text_similarity(batch1_overlap, batch2_overlap),
            'confidence': 'low',
            'resolution_method': 'batch1_fallback',
            'overlap_pages': overlap_pages,
            'error': str(e),
            'needs_review': True
        }


def merge_batch_results(batch1_result: Dict, batch2_result: Dict,
                       overlap_pages: List[int],
                       reconciliation: Dict) -> Dict[str, Any]:
    """
    Merge two batch results into a single result.

    Takes non-overlapping parts from batch1, reconciled overlap, and
    non-overlapping parts from batch2.

    Args:
        batch1_result: First batch extraction result
        batch2_result: Second batch extraction result
        overlap_pages: Pages that overlap
        reconciliation: Result from reconcile_overlaps

    Returns:
        Merged extraction result
    """

    overlap_set = set(overlap_pages)

    # Get paragraphs from each batch
    batch1_pages = set(batch1_result.get('scan_pages', []))
    batch2_pages = set(batch2_result.get('scan_pages', []))

    # Non-overlapping parts
    batch1_only_pages = batch1_pages - overlap_set
    batch2_only_pages = batch2_pages - overlap_set

    # Build merged paragraphs list
    merged_paragraphs = []

    # Add batch1 non-overlap paragraphs
    for p in batch1_result.get('paragraphs', []):
        if p.get('scan_page') in batch1_only_pages:
            merged_paragraphs.append(p)

    # Add reconciled overlap paragraphs
    # (For now, just use batch1's overlap paragraphs from reconciliation)
    for p in batch1_result.get('paragraphs', []):
        if p.get('scan_page') in overlap_set:
            merged_paragraphs.append(p)

    # Add batch2 non-overlap paragraphs
    for p in batch2_result.get('paragraphs', []):
        if p.get('scan_page') in batch2_only_pages:
            merged_paragraphs.append(p)

    # Sort by scan_page to maintain order
    merged_paragraphs.sort(key=lambda p: p.get('scan_page', 0))

    # Build merged result
    merged_text = '\n\n'.join(p['text'] for p in merged_paragraphs)
    merged_word_count = len(merged_text.split())

    # Merge chapter markers and footnotes
    merged_chapters = (batch1_result.get('chapter_markers', []) +
                      batch2_result.get('chapter_markers', []))
    merged_footnotes = (batch1_result.get('footnotes', []) +
                       batch2_result.get('footnotes', []))

    # Deduplicate by scan_page
    seen_chapters = set()
    unique_chapters = []
    for ch in merged_chapters:
        page = ch.get('scan_page')
        if page not in seen_chapters:
            seen_chapters.add(page)
            unique_chapters.append(ch)

    return {
        'clean_text': merged_text,
        'paragraphs': merged_paragraphs,
        'word_count': merged_word_count,
        'scan_pages': sorted(batch1_pages | batch2_pages),
        'chapter_markers': unique_chapters,
        'footnotes': merged_footnotes,
        'reconciliation_info': {
            'overlap_pages': overlap_pages,
            'similarity': reconciliation.get('similarity'),
            'resolution_method': reconciliation.get('resolution_method')
        }
    }
