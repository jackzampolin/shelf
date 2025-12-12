"""Library management tools for MCP server."""

from shelf_mcp.utils.loader import list_completed_books, load_book_structure_raw


def list_books() -> dict:
    """List all books in the library with completed processing.

    Returns a list of books with their scan_id, title, author, and chapter counts.
    Use this to discover what books are available for querying.
    """
    books = list_completed_books()

    if not books:
        return {
            "count": 0,
            "books": [],
            "message": "No books found with completed common-structure processing.",
        }

    return {
        "count": len(books),
        "books": books,
    }


def get_book_info(scan_id: str) -> dict:
    """Get detailed information about a specific book.

    Args:
        scan_id: The book identifier (e.g., "admirals", "roosevelt-autobiography").

    Returns detailed metadata including title, author, chapter count,
    page count, and processing statistics.
    """
    data = load_book_structure_raw(scan_id)

    if data is None:
        return {
            "error": f"Book '{scan_id}' not found or not fully processed.",
            "hint": "Use list_books() to see available books.",
        }

    metadata = data.get("metadata", {})
    entries = data.get("entries", [])

    # Count entries by level
    parts = [e for e in entries if e.get("level") == 1]
    chapters = [e for e in entries if e.get("level") == 2]
    sections = [e for e in entries if e.get("level") == 3]

    # Count entries by matter type
    front = [e for e in entries if e.get("matter_type") == "front_matter"]
    body = [e for e in entries if e.get("matter_type") == "body"]
    back = [e for e in entries if e.get("matter_type") == "back_matter"]

    # Calculate total word count
    total_words = 0
    for entry in entries:
        content = entry.get("content")
        if content:
            total_words += content.get("word_count", 0)

    return {
        "scan_id": scan_id,
        "title": metadata.get("title", scan_id),
        "author": metadata.get("author"),
        "publisher": metadata.get("publisher"),
        "publication_year": metadata.get("publication_year"),
        "language": metadata.get("language", "en"),
        "total_scan_pages": metadata.get("total_scan_pages"),
        "structure": {
            "total_entries": len(entries),
            "parts": len(parts),
            "chapters": len(chapters),
            "sections": len(sections),
        },
        "matter_breakdown": {
            "front_matter": len(front),
            "body": len(body),
            "back_matter": len(back),
        },
        "total_word_count": total_words,
        "processing": {
            "extracted_at": data.get("extracted_at"),
            "cost_usd": data.get("cost_usd"),
            "processing_time_seconds": data.get("processing_time_seconds"),
        },
    }
