"""
Grep-based keyword search tool for ToC finder.

Searches paragraph_correct outputs for common ToC and book structure keywords.
Returns matches grouped by page with context, enabling strategic vision verification.
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

from infra.storage.book_storage import BookStorage


# All search patterns (no categorization - let the agent interpret)
SEARCH_PATTERNS = [
    # ToC-specific patterns
    r"\bTable of Contents\b",
    r"\bTABLE OF CONTENTS\b",
    r"\bContents\b",  # Match "Contents" word boundary (handles "Contents —" etc)
    r"\bCONTENTS\b",

    # Front matter
    r"\bPreface\b",
    r"\bPREFACE\b",
    r"\bAuthor's Note\b",
    r"\bForeword\b",
    r"\bIntroduction\b",
    r"\bINTRODUCTION\b",
    r"\bPrologue\b",
    r"\bAcknowledgments\b",
    r"\bAcknowledgements\b",
    r"\bACKNOWLEDGMENTS\b",
    r"\bDedication\b",
    r"\bDedicated to\b",
    r"\bAbout the Author\b",
    r"\bAbout The Author\b",

    # Structure patterns
    r"\bChapter\s+\d+",
    r"\bCHAPTER\s+\d+",
    r"^Chapter\s+[IVX]+",
    r"\bPart\s+\d+",
    r"\bPART\s+\d+",
    r"^Part\s+[IVX]+",
    r"\bSection\s+\d+",

    # Back matter
    r"\bAppendix\b",
    r"\bAPPENDIX\b",
    r"\bBibliography\b",
    r"\bWorks Cited\b",
    r"\bReferences\b",
    r"\bIndex\b",
    r"\bINDEX\b",
    r"\bEpilogue\b",
    r"\bAfterword\b",
    r"\bEndnotes\b",
    r"\bNotes\b",
]


def extract_text_from_page(storage: BookStorage, page_num: int) -> str:
    """
    Extract all text from a page (OCR + paragraph corrections merged).

    Args:
        storage: BookStorage instance
        page_num: Page number

    Returns:
        Combined text with corrections applied
    """
    from pipeline.paragraph_correct.tools import get_merged_page_text
    return get_merged_page_text(storage, page_num)


def extract_context(text: str, match: str, match_pos: int, context_chars: int = 100) -> str:
    """
    Extract context around a match.

    Args:
        text: Full text
        match: The matched string
        match_pos: Position of match in text
        context_chars: Characters to include before/after match

    Returns:
        Context string with match highlighted
    """
    start = max(0, match_pos - context_chars)
    end = min(len(text), match_pos + len(match) + context_chars)

    context = text[start:end]

    # Clean up whitespace for readability
    context = ' '.join(context.split())

    # Truncate if too long
    if len(context) > 200:
        context = context[:200] + "..."

    return context


def search_patterns_with_context(text: str, patterns: List[str]) -> List[Dict[str, str]]:
    """
    Search text for regex patterns and return matches with context.

    Args:
        text: Text to search
        patterns: List of regex patterns

    Returns:
        List of dicts with {keyword, context}
    """
    matches = []
    seen = set()  # Deduplicate by (keyword, context) tuple

    for pattern in patterns:
        for match in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE):
            keyword = match.group(0)
            context = extract_context(text, keyword, match.start())

            # Deduplicate
            key = (keyword, context)
            if key not in seen:
                seen.add(key)
                matches.append({
                    "keyword": keyword,
                    "context": context
                })

    return matches


def generate_grep_report(storage: BookStorage, max_pages: int = 50) -> Dict:
    """
    Generate keyword search report for ToC finding.

    Searches paragraph_correct outputs for book structure keywords.
    Focuses on first N pages (ToC typically in front matter).

    Args:
        storage: BookStorage instance
        max_pages: Maximum pages to search (default: 50, ToC is usually early)

    Returns:
        Dict with structure:
        {
            "pages": [
                {
                    "page": 18,
                    "matches": [
                        {"keyword": "Contents", "context": "Contents — Part I The BACKGROUND..."}
                    ]
                },
                {
                    "page": 19,
                    "matches": [
                        {"keyword": "BIBLIOGRAPHY", "context": "BIBLIOGRAPHY OF CITED SOURCES"},
                        {"keyword": "INDEX", "context": "INDEX"}
                    ]
                }
            ],
            "search_range": "1-50",
            "total_pages_searched": 50
        }
    """
    metadata = storage.load_metadata()
    total_pages = metadata.get("total_pages", 0)

    # Limit search to front section (ToC is rarely past page 50)
    search_end = min(max_pages, total_pages)

    # Collect matches by page
    pages_with_matches = []

    for page_num in range(1, search_end + 1):
        try:
            text = extract_text_from_page(storage, page_num)
            matches = search_patterns_with_context(text, SEARCH_PATTERNS)

            if matches:
                pages_with_matches.append({
                    "page": page_num,
                    "matches": matches
                })

        except FileNotFoundError:
            # Page not found (may not be corrected yet)
            continue
        except Exception as e:
            # Log error but continue
            print(f"Warning: Error processing page {page_num}: {e}")
            continue

    report = {
        "pages": pages_with_matches,
        "search_range": f"1-{search_end}",
        "total_pages_searched": search_end,
    }

    return report


def summarize_grep_report(report: Dict) -> str:
    """
    Create human-readable summary of grep report.

    Args:
        report: Output from generate_grep_report()

    Returns:
        Formatted string summary
    """
    lines = []
    lines.append(f"Searched pages: {report['search_range']}")
    lines.append("")

    pages = report.get("pages", [])
    if pages:
        lines.append(f"Found matches on {len(pages)} pages:")
        for page_data in pages[:10]:  # Show first 10 pages
            page_num = page_data["page"]
            match_count = len(page_data["matches"])
            keywords = [m["keyword"] for m in page_data["matches"]]
            lines.append(f"  Page {page_num}: {match_count} matches → {', '.join(keywords[:5])}")
            if len(keywords) > 5:
                lines.append(f"             (+{len(keywords) - 5} more)")

        if len(pages) > 10:
            lines.append(f"  ... and {len(pages) - 10} more pages")
    else:
        lines.append("No matches found")

    return "\n".join(lines)
