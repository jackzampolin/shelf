"""Search tools for MCP server."""

from typing import Optional

from shelf_mcp.utils.loader import list_completed_books, load_book_structure_raw


def _get_context_snippet(text: str, query: str, context_chars: int = 150) -> list[dict]:
    """Find all occurrences of query in text and return context snippets with highlighting."""
    matches = []
    query_lower = query.lower()
    text_lower = text.lower()

    start = 0
    while True:
        pos = text_lower.find(query_lower, start)
        if pos == -1:
            break

        # Get context around match
        snippet_start = max(0, pos - context_chars)
        snippet_end = min(len(text), pos + len(query) + context_chars)

        # Extend to word boundaries
        if snippet_start > 0:
            while snippet_start > 0 and text[snippet_start - 1] not in ' \n':
                snippet_start -= 1
        if snippet_end < len(text):
            while snippet_end < len(text) and text[snippet_end] not in ' \n':
                snippet_end += 1

        snippet = text[snippet_start:snippet_end].strip()

        # Add ellipsis markers
        prefix = "..." if snippet_start > 0 else ""
        suffix = "..." if snippet_end < len(text) else ""

        # Create highlighted version with **markers** around the match
        # Find match position within snippet
        match_start_in_snippet = pos - snippet_start
        if snippet_start > 0:
            # Adjust for stripped whitespace at start
            original_snippet = text[snippet_start:snippet_end]
            stripped_start = len(original_snippet) - len(original_snippet.lstrip())
            match_start_in_snippet -= stripped_start

        # Build highlighted snippet
        snippet_text = f"{prefix}{snippet}{suffix}"

        # Find the actual match in the final snippet and highlight it
        match_pos_in_final = snippet_text.lower().find(query_lower)
        if match_pos_in_final >= 0:
            highlighted = (
                snippet_text[:match_pos_in_final] +
                "**" + snippet_text[match_pos_in_final:match_pos_in_final + len(query)] + "**" +
                snippet_text[match_pos_in_final + len(query):]
            )
        else:
            highlighted = snippet_text

        matches.append({
            "position": pos,
            "snippet": snippet_text,
            "highlighted": highlighted,
        })

        start = pos + 1

    return matches


def search_book(
    scan_id: str,
    query: str,
    case_sensitive: bool = False,
    limit: int = 10,
    offset: int = 0,
    snippets_per_entry: int = 3,
) -> dict:
    """Search for text within a specific book with pagination.

    Args:
        scan_id: The book identifier.
        query: Text to search for (minimum 2 characters).
        case_sensitive: Whether to match case (default: False).
        limit: Maximum entries to return (default: 10).
        offset: Number of entries to skip (default: 0). Use for pagination.
        snippets_per_entry: Max snippets per entry (default: 3).

    Returns matching entries with context snippets and pagination info.
    Use offset to paginate through results.
    """
    if len(query) < 2:
        return {"error": "Query must be at least 2 characters."}

    data = load_book_structure_raw(scan_id)

    if data is None:
        return {
            "error": f"Book '{scan_id}' not found.",
            "hint": "Use list_books() to see available books.",
        }

    entries = data.get("entries", [])
    all_results = []

    # Find all matching entries
    for entry in entries:
        content = entry.get("content")
        if not content:
            continue

        text = content.get("final_text", "")
        if not text:
            continue

        # Perform search
        search_text = text if case_sensitive else text.lower()
        search_query = query if case_sensitive else query.lower()

        if search_query in search_text:
            snippets = _get_context_snippet(text, query)
            all_results.append({
                "entry_id": entry.get("entry_id"),
                "title": entry.get("title"),
                "level": entry.get("level"),
                "matter_type": entry.get("matter_type"),
                "match_count": len(snippets),
                "snippets": snippets[:snippets_per_entry],
            })

    total_entries = len(all_results)
    total_matches = sum(r["match_count"] for r in all_results)

    # Apply pagination
    paginated_results = all_results[offset:offset + limit]
    has_more = (offset + limit) < total_entries

    return {
        "scan_id": scan_id,
        "query": query,
        "total_matches": total_matches,
        "total_entries_matched": total_entries,
        "pagination": {
            "offset": offset,
            "limit": limit,
            "returned": len(paginated_results),
            "has_more": has_more,
            "next_offset": offset + limit if has_more else None,
        },
        "results": paginated_results,
    }


def search_library(
    query: str,
    case_sensitive: bool = False,
    limit_per_book: int = 5,
    offset: int = 0,
    limit_books: int = 10,
    snippets_per_entry: int = 2,
) -> dict:
    """Search for text across all books in the library with pagination.

    Args:
        query: Text to search for (minimum 2 characters).
        case_sensitive: Whether to match case (default: False).
        limit_per_book: Max entries per book (default: 5).
        offset: Number of books to skip (default: 0). Use for pagination.
        limit_books: Max number of books to return (default: 10).
        snippets_per_entry: Max snippets per entry (default: 2).

    Returns matching entries from books with pagination info.
    Use offset to paginate through books with matches.
    """
    if len(query) < 2:
        return {"error": "Query must be at least 2 characters."}

    books = list_completed_books()
    if not books:
        return {
            "query": query,
            "total_matches": 0,
            "books_searched": 0,
            "results": [],
            "message": "No books found in library.",
        }

    # First pass: find all books with matches
    books_with_matches = []
    total_matches_all = 0

    for book in books:
        scan_id = book["scan_id"]
        # Search without pagination to get totals
        result = search_book(scan_id, query, case_sensitive, limit=1000, offset=0, snippets_per_entry=snippets_per_entry)

        if "error" in result:
            continue

        if result.get("total_entries_matched", 0) > 0:
            total_matches_all += result.get("total_matches", 0)
            books_with_matches.append({
                "scan_id": scan_id,
                "title": book.get("title", scan_id),
                "total_matches": result.get("total_matches", 0),
                "entries_matched": result.get("total_entries_matched", 0),
                "results": result.get("results", [])[:limit_per_book],
            })

    total_books_matched = len(books_with_matches)

    # Apply pagination to books
    paginated_books = books_with_matches[offset:offset + limit_books]
    has_more = (offset + limit_books) < total_books_matched

    return {
        "query": query,
        "books_searched": len(books),
        "total_books_with_matches": total_books_matched,
        "total_matches": total_matches_all,
        "pagination": {
            "offset": offset,
            "limit_books": limit_books,
            "returned_books": len(paginated_books),
            "has_more": has_more,
            "next_offset": offset + limit_books if has_more else None,
        },
        "results": paginated_books,
    }
