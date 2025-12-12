"""Content access tools for MCP server."""

import math
from typing import Optional

from shelf_mcp.utils.loader import load_book_structure_raw


def get_toc(scan_id: str) -> dict:
    """Get the table of contents for a book.

    Args:
        scan_id: The book identifier.

    Returns the hierarchical structure of the book with entry IDs, titles,
    and levels. Use entry_ids with get_chapter() to retrieve full text.
    """
    data = load_book_structure_raw(scan_id)

    if data is None:
        return {
            "error": f"Book '{scan_id}' not found.",
            "hint": "Use list_books() to see available books.",
        }

    entries = data.get("entries", [])
    toc = []

    for entry in entries:
        content = entry.get("content")
        word_count = content.get("word_count", 0) if content else 0

        toc.append({
            "entry_id": entry.get("entry_id"),
            "title": entry.get("title"),
            "level": entry.get("level"),
            "parent_id": entry.get("parent_id"),
            "matter_type": entry.get("matter_type"),
            "semantic_type": entry.get("semantic_type"),
            "pages": f"{entry.get('scan_page_start')}-{entry.get('scan_page_end')}",
            "word_count": word_count,
        })

    return {
        "scan_id": scan_id,
        "title": data.get("metadata", {}).get("title", scan_id),
        "entries": toc,
    }


def _find_entry(scan_id: str, entry_id: Optional[str] = None, title_search: Optional[str] = None) -> tuple[Optional[dict], Optional[dict], Optional[dict]]:
    """Find an entry by ID or title search.

    Returns: (entry, data, error_dict)
    """
    if not entry_id and not title_search:
        return None, None, {
            "error": "Must provide either entry_id or title_search.",
            "hint": "Use get_toc() to find entry IDs, or provide a title to search for.",
        }

    data = load_book_structure_raw(scan_id)

    if data is None:
        return None, None, {
            "error": f"Book '{scan_id}' not found.",
            "hint": "Use list_books() to see available books.",
        }

    entries = data.get("entries", [])
    entry = None

    if entry_id:
        for e in entries:
            if e.get("entry_id") == entry_id:
                entry = e
                break
    elif title_search:
        title_lower = title_search.lower()
        matches = []
        for e in entries:
            if title_lower in e.get("title", "").lower():
                matches.append(e)

        if len(matches) == 1:
            entry = matches[0]
        elif len(matches) > 1:
            return None, data, {
                "error": f"Multiple entries match '{title_search}'.",
                "matches": [{"entry_id": m.get("entry_id"), "title": m.get("title")} for m in matches],
                "hint": "Use entry_id for exact match.",
            }

    if entry is None:
        search_term = entry_id or title_search
        return None, data, {
            "error": f"Entry not found: '{search_term}'.",
            "hint": "Use get_toc() to see available entries.",
        }

    return entry, data, None


def get_chapter(
    scan_id: str,
    entry_id: Optional[str] = None,
    title_search: Optional[str] = None,
    chunk_size: int = 0,
    chunk_number: int = 1,
    overlap: int = 0,
) -> dict:
    """Get the text of a chapter or section, optionally in chunks.

    Args:
        scan_id: The book identifier.
        entry_id: The entry ID (e.g., "ch_006", "part_001"). Use get_toc() to find IDs.
        title_search: Alternative: search by title (case-insensitive partial match).
        chunk_size: Characters per chunk. 0 = return full text (default).
                    Recommended: 8000 for ~2000 tokens.
        chunk_number: Which chunk to return (1-indexed). Default: 1.
        overlap: Characters to overlap between chunks (default: 0).
                 Recommended: 200 to avoid losing context at boundaries.

    Returns the chapter's text content along with metadata and chunking info.
    Provide either entry_id OR title_search, not both.
    """
    entry, data, error = _find_entry(scan_id, entry_id, title_search)
    if error:
        return error

    content = entry.get("content")
    if content is None:
        return {
            "entry_id": entry.get("entry_id"),
            "title": entry.get("title"),
            "error": "No text content available for this entry.",
        }

    full_text = content.get("final_text", "")
    total_chars = len(full_text)
    word_count = content.get("word_count", 0)

    # Build base response
    result = {
        "scan_id": scan_id,
        "entry_id": entry.get("entry_id"),
        "title": entry.get("title"),
        "level": entry.get("level"),
        "parent_id": entry.get("parent_id"),
        "matter_type": entry.get("matter_type"),
        "semantic_type": entry.get("semantic_type"),
        "pages": f"{entry.get('scan_page_start')}-{entry.get('scan_page_end')}",
        "word_count": word_count,
        "total_characters": total_chars,
    }

    # Handle chunking
    if chunk_size > 0 and total_chars > chunk_size:
        # Calculate effective stride (chunk_size minus overlap)
        stride = max(chunk_size - overlap, 1)  # Ensure at least 1 char progress
        total_chunks = math.ceil((total_chars - overlap) / stride) if total_chars > overlap else 1

        if chunk_number < 1 or chunk_number > total_chunks:
            return {
                **result,
                "error": f"Invalid chunk_number {chunk_number}. Valid range: 1-{total_chunks}.",
                "total_chunks": total_chunks,
            }

        # Calculate start position (first chunk starts at 0, subsequent chunks back up by overlap)
        start_idx = (chunk_number - 1) * stride
        end_idx = min(start_idx + chunk_size, total_chars)

        # Try to break at word boundaries (but not for the overlap portion)
        if end_idx < total_chars:
            # Look for space within last 100 chars (but keep at least chunk_size - 100)
            for i in range(end_idx, max(start_idx + chunk_size - 100, start_idx), -1):
                if full_text[i] in ' \n':
                    end_idx = i
                    break

        chunk_text = full_text[start_idx:end_idx]

        result["text"] = chunk_text
        result["chunking"] = {
            "chunk_number": chunk_number,
            "total_chunks": total_chunks,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "chunk_start": start_idx,
            "chunk_end": end_idx,
            "has_more": chunk_number < total_chunks,
        }
    else:
        result["text"] = full_text
        result["chunking"] = {
            "chunk_number": 1,
            "total_chunks": 1,
            "chunk_size": total_chars,
            "overlap": 0,
            "chunk_start": 0,
            "chunk_end": total_chars,
            "has_more": False,
        }

    return result


def get_chapter_metadata(scan_id: str, entry_id: str) -> dict:
    """Get chapter metadata without full text (for quick overview).

    Args:
        scan_id: The book identifier.
        entry_id: The entry ID (e.g., "ch_006", "part_001").

    Returns metadata about the chapter including word count and page range,
    but not the full text content.
    """
    entry, data, error = _find_entry(scan_id, entry_id=entry_id)
    if error:
        return error

    content = entry.get("content")
    word_count = content.get("word_count", 0) if content else 0
    char_count = len(content.get("final_text", "")) if content else 0
    page_count = entry.get("scan_page_end", 0) - entry.get("scan_page_start", 0) + 1

    # Calculate recommended chunks for 8000 char chunks
    recommended_chunk_size = 8000
    total_chunks = math.ceil(char_count / recommended_chunk_size) if char_count > 0 else 1

    return {
        "scan_id": scan_id,
        "entry_id": entry.get("entry_id"),
        "title": entry.get("title"),
        "level": entry.get("level"),
        "parent_id": entry.get("parent_id"),
        "matter_type": entry.get("matter_type"),
        "semantic_type": entry.get("semantic_type"),
        "scan_page_start": entry.get("scan_page_start"),
        "scan_page_end": entry.get("scan_page_end"),
        "page_count": page_count,
        "word_count": word_count,
        "character_count": char_count,
        "recommended_chunks": total_chunks,
        "confidence": entry.get("confidence"),
        "source": entry.get("source"),
    }


def summarize_chapter(scan_id: str, entry_id: str, max_words: int = 500) -> dict:
    """Generate an LLM-powered summary of a chapter.

    Args:
        scan_id: The book identifier.
        entry_id: The entry ID (e.g., "ch_006", "part_001").
        max_words: Target summary length (default: 500 words).

    Returns a ~500 word summary generated by the configured LLM model.
    Note: This incurs API costs via OpenRouter.
    """
    import os
    from infra.llm.client import LLMClient

    entry, data, error = _find_entry(scan_id, entry_id=entry_id)
    if error:
        return error

    content = entry.get("content")
    if content is None:
        return {
            "entry_id": entry.get("entry_id"),
            "title": entry.get("title"),
            "error": "No text content available for this entry.",
        }

    full_text = content.get("final_text", "")
    if not full_text:
        return {
            "entry_id": entry.get("entry_id"),
            "title": entry.get("title"),
            "error": "Chapter has empty text content.",
        }

    # Get model from environment
    model = os.getenv("VISION_MODEL_PRIMARY", "")
    if not model:
        # Fall back to a reasonable default
        model = "google/gemini-2.0-flash-001"

    book_title = data.get("metadata", {}).get("title", scan_id)
    chapter_title = entry.get("title", "Unknown")

    prompt = f"""Summarize this chapter in approximately {max_words} words.

Book: {book_title}
Chapter: {chapter_title}

Focus on:
- Key events, arguments, or themes
- Important people, places, or concepts mentioned
- The chapter's role in the broader narrative

Chapter text:
{full_text}

Write a clear, informative summary:"""

    try:
        client = LLMClient()
        result = client.call(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1500,
        )

        if not result.success:
            return {
                "scan_id": scan_id,
                "entry_id": entry_id,
                "title": chapter_title,
                "error": f"LLM call failed: {result.error_message}",
            }

        return {
            "scan_id": scan_id,
            "entry_id": entry_id,
            "title": chapter_title,
            "word_count": content.get("word_count", 0),
            "summary": result.response,
            "model_used": result.model_used,
            "cost_usd": result.cost_usd,
        }

    except Exception as e:
        return {
            "scan_id": scan_id,
            "entry_id": entry_id,
            "title": chapter_title,
            "error": f"Failed to generate summary: {str(e)}",
        }
