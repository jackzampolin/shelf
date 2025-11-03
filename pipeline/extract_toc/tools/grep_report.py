"""
Grep-based keyword search tool for ToC finder.

Searches paragraph_correct outputs for common ToC and front matter keywords.
Returns page numbers where patterns appear, enabling strategic vision verification.
"""

import re
import json
from pathlib import Path
from typing import Dict, List, Set
from collections import defaultdict

from infra.storage.book_storage import BookStorage


# ToC-specific patterns (highest priority)
TOC_PATTERNS = [
    r"\bTable of Contents\b",
    r"\bTABLE OF CONTENTS\b",
    r"^Contents$",
    r"^CONTENTS$",
    r"\bT\.O\.C\.\b",
    r"\bTOC\b",
]

# Front matter patterns (appear near ToC)
FRONT_MATTER_PATTERNS = {
    "preface": [
        r"\bPreface\b",
        r"\bPREFACE\b",
        r"\bAuthor's Note\b",
        r"\bForeword\b",
    ],
    "introduction": [
        r"\bIntroduction\b",
        r"\bINTRODUCTION\b",
        r"\bPrologue\b",
    ],
    "acknowledgments": [
        r"\bAcknowledgments\b",
        r"\bAcknowledgements\b",
        r"\bACKNOWLEDGMENTS\b",
    ],
    "dedication": [
        r"\bDedication\b",
        r"\bDedicated to\b",
    ],
    "about_author": [
        r"\bAbout the Author\b",
        r"\bAbout The Author\b",
    ],
}

# Chapter/structure patterns (validate ToC completeness)
STRUCTURE_PATTERNS = {
    "chapter": [
        r"\bChapter\s+\d+",
        r"\bCHAPTER\s+\d+",
        r"^Chapter\s+[IVX]+",
    ],
    "part": [
        r"\bPart\s+\d+",
        r"\bPART\s+\d+",
        r"^Part\s+[IVX]+",
    ],
    "section": [
        r"\bSection\s+\d+",
    ],
}

# Back matter patterns (help identify ToC boundaries)
BACK_MATTER_PATTERNS = {
    "appendix": [
        r"\bAppendix\b",
        r"\bAPPENDIX\b",
    ],
    "bibliography": [
        r"\bBibliography\b",
        r"\bWorks Cited\b",
        r"\bReferences\b",
    ],
    "index": [
        r"\bIndex\b",
        r"\bINDEX\b",
    ],
    "epilogue": [
        r"\bEpilogue\b",
        r"\bAfterword\b",
    ],
    "notes": [
        r"\bEndnotes\b",
        r"\bNotes\b",
    ],
}


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


def search_patterns(text: str, patterns: List[str]) -> List[str]:
    """
    Search text for regex patterns.

    Args:
        text: Text to search
        patterns: List of regex patterns

    Returns:
        List of matched strings (deduplicated)
    """
    matches = []
    for pattern in patterns:
        found = re.findall(pattern, text, re.MULTILINE | re.IGNORECASE)
        matches.extend(found)
    return list(set(matches))  # Deduplicate


def generate_grep_report(storage: BookStorage, max_pages: int = 50) -> Dict:
    """
    Generate keyword search report for ToC finding.

    Searches paragraph_correct outputs for ToC and front matter keywords.
    Focuses on first N pages (ToC typically in front matter).

    Args:
        storage: BookStorage instance
        max_pages: Maximum pages to search (default: 50, ToC is usually early)

    Returns:
        Dict with structure:
        {
            "toc_candidates": [4, 5],  # Pages with ToC keywords
            "front_matter": {
                "preface": [8, 9],
                "introduction": [12]
            },
            "structure": {
                "chapter": [15, 30, 45],
                "part": [15, 100]
            },
            "back_matter": {
                "index": [350, 351]
            },
            "search_range": "1-50",
            "total_pages_searched": 50
        }
    """
    para_correct_stage = storage.stage("paragraph-correct")
    metadata = storage.load_metadata()
    total_pages = metadata.get("total_pages", 0)

    # Limit search to front section (ToC is rarely past page 50)
    search_end = min(max_pages, total_pages)

    toc_candidates: Set[int] = set()
    front_matter: Dict[str, Set[int]] = defaultdict(set)
    structure: Dict[str, Set[int]] = defaultdict(set)
    back_matter: Dict[str, Set[int]] = defaultdict(set)

    # Search each page in range
    for page_num in range(1, search_end + 1):
        try:
            text = extract_text_from_page(storage, page_num)

            # Search ToC patterns (highest priority)
            toc_matches = search_patterns(text, TOC_PATTERNS)
            if toc_matches:
                toc_candidates.add(page_num)

            # Search front matter patterns
            for category, patterns in FRONT_MATTER_PATTERNS.items():
                matches = search_patterns(text, patterns)
                if matches:
                    front_matter[category].add(page_num)

            # Search structure patterns (chapters/parts)
            for category, patterns in STRUCTURE_PATTERNS.items():
                matches = search_patterns(text, patterns)
                if matches:
                    structure[category].add(page_num)

            # Search back matter patterns
            for category, patterns in BACK_MATTER_PATTERNS.items():
                matches = search_patterns(text, patterns)
                if matches:
                    back_matter[category].add(page_num)

        except FileNotFoundError:
            # Page not found (may not be corrected yet)
            continue
        except Exception as e:
            # Log error but continue
            print(f"Warning: Error processing page {page_num}: {e}")
            continue

    # Convert sets to sorted lists for JSON serialization
    report = {
        "toc_candidates": sorted(list(toc_candidates)),
        "front_matter": {k: sorted(list(v)) for k, v in front_matter.items()},
        "structure": {k: sorted(list(v)) for k, v in structure.items()},
        "back_matter": {k: sorted(list(v)) for k, v in back_matter.items()},
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

    # ToC candidates
    toc_pages = report.get("toc_candidates", [])
    if toc_pages:
        lines.append(f"ToC keyword matches: {len(toc_pages)} pages → {toc_pages}")
    else:
        lines.append("ToC keyword matches: None found")

    # Front matter
    front = report.get("front_matter", {})
    if front:
        lines.append("")
        lines.append("Front matter detected:")
        for category, pages in sorted(front.items()):
            if pages:
                lines.append(f"  - {category}: {pages}")

    # Structure
    struct = report.get("structure", {})
    if struct:
        lines.append("")
        lines.append("Structure detected:")
        for category, pages in sorted(struct.items()):
            if pages:
                # Show first 5 pages to avoid clutter
                page_preview = pages[:5]
                more = f" (+{len(pages) - 5} more)" if len(pages) > 5 else ""
                lines.append(f"  - {category}: {page_preview}{more}")

    return "\n".join(lines)
