import re
import json
from pathlib import Path
from typing import Dict, List
from collections import defaultdict

from infra.pipeline.storage.book_storage import BookStorage


# Categorized search patterns
KEYWORD_CATEGORIES = {
    "toc": [
        r"\bTable of Contents\b",
        r"\bTABLE OF CONTENTS\b",
        r"\bContents\b",
        r"\bCONTENTS\b",
    ],
    "front_matter": [
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
    ],
    "structure": [
        r"\bChapter\s+\d+",
        r"\bCHAPTER\s+\d+",
        r"^Chapter\s+[IVX]+",
        r"\bPart\s+\d+",
        r"\bPART\s+\d+",
        r"^Part\s+[IVX]+",
        r"\bSection\s+\d+",
    ],
    "back_matter": [
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
    ],
}


def extract_text_from_page(storage: BookStorage, page_num: int) -> str:
    """Extract OCR text from olm-ocr stage."""
    from pipeline.olm_ocr.schemas import OlmOcrPageOutput

    ocr_stage_storage = storage.stage('olm-ocr')
    page_data = ocr_stage_storage.load_page(page_num, schema=OlmOcrPageOutput)
    if not page_data:
        raise FileNotFoundError(f"OCR data for page {page_num} not found")
    return page_data.get("text", "")


def search_categorized_patterns(text: str) -> Dict[str, List[str]]:
    """Search for patterns and return categorized keyword matches."""
    categories = defaultdict(set)

    for category, patterns in KEYWORD_CATEGORIES.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.MULTILINE | re.IGNORECASE):
                keyword = match.group(0)
                categories[category].add(keyword)

    # Convert sets to sorted lists for JSON serialization
    return {category: sorted(keywords) for category, keywords in categories.items()}


def generate_grep_report(storage: BookStorage, max_pages: int = 50) -> Dict:
    """Generate categorized keyword report for front matter region."""
    metadata = storage.load_metadata()
    total_pages = metadata.get("total_pages", 0)

    search_end = min(max_pages, total_pages)

    # Categorized results: {category: [page_nums]}
    categorized_pages = defaultdict(list)

    # Page-level details: {page_num: {category: [keywords]}}
    page_details = {}

    for page_num in range(1, search_end + 1):
        try:
            text = extract_text_from_page(storage, page_num)
            categories = search_categorized_patterns(text)

            if categories:
                page_details[page_num] = categories

                for category in categories.keys():
                    categorized_pages[category].append(page_num)

        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"Warning: Error processing page {page_num}: {e}")
            continue

    report = {
        "search_range": f"1-{search_end}",
        "total_pages_searched": search_end,
        "categorized_pages": dict(categorized_pages),
        "page_details": page_details,
    }

    return report


def _identify_clusters(pages: List[int], min_cluster_size: int = 3, max_gap: int = 2) -> List[List[int]]:
    """Identify clusters of pages (consecutive or near-consecutive)."""
    if not pages:
        return []

    sorted_pages = sorted(pages)
    clusters = []
    current_cluster = [sorted_pages[0]]

    for page in sorted_pages[1:]:
        if page - current_cluster[-1] <= max_gap:
            current_cluster.append(page)
        else:
            if len(current_cluster) >= min_cluster_size:
                clusters.append(current_cluster)
            current_cluster = [page]

    if len(current_cluster) >= min_cluster_size:
        clusters.append(current_cluster)

    return clusters


def summarize_grep_report(report: Dict) -> str:
    """Generate actionable summary of grep findings."""
    lines = []
    lines.append(f"Searched: {report['search_range']}")
    lines.append("")

    categorized = report.get("categorized_pages", {})
    page_details = report.get("page_details", {})

    if not categorized:
        lines.append("No keywords found in search range.")
        return "\n".join(lines)

    # ToC keywords (highest priority)
    if "toc" in categorized:
        pages = categorized["toc"]
        lines.append(f"✓ TOC KEYWORDS: pages {pages}")
        lines.append("  → Check these pages first (direct ToC indicators)")
        lines.append("")

    # Structure keywords (strong signal if clustered in front matter)
    if "structure" in categorized:
        pages = categorized["structure"]
        clusters = _identify_clusters(pages, min_cluster_size=3, max_gap=2)

        if clusters:
            lines.append(f"✓ STRUCTURE CLUSTERING: {len(clusters)} cluster(s) found")
            for cluster in clusters:
                page_range = f"{cluster[0]}-{cluster[-1]}" if len(cluster) > 1 else str(cluster[0])
                lines.append(f"  → Pages {page_range} ({len(cluster)} pages)")

                # Show what keywords appear in this cluster
                cluster_keywords = set()
                for page in cluster:
                    if page in page_details and "structure" in page_details[page]:
                        cluster_keywords.update(page_details[page]["structure"])

                if cluster_keywords:
                    lines.append(f"     Keywords: {', '.join(sorted(cluster_keywords)[:5])}")

            lines.append("  Note: Dense clustering of Chapter/Part = likely ToC listing")
            lines.append("")
        else:
            lines.append(f"• Structure keywords: scattered across {len(pages)} pages (not clustered)")
            lines.append("")

    # Front matter keywords
    if "front_matter" in categorized:
        pages = categorized["front_matter"]
        lines.append(f"• Front matter: pages {pages[:5]}")
        if len(pages) > 5:
            lines.append(f"  (+{len(pages) - 5} more)")
        lines.append("")

    # Back matter keywords
    if "back_matter" in categorized:
        pages = categorized["back_matter"]
        lines.append(f"• Back matter: pages {pages[:5]}")
        if len(pages) > 5:
            lines.append(f"  (+{len(pages) - 5} more)")
        lines.append("")

    # Summary guidance
    lines.append("RECOMMENDATION:")
    if "toc" in categorized:
        lines.append("  Start with TOC keyword pages")
    elif "structure" in categorized and _identify_clusters(categorized["structure"]):
        clusters = _identify_clusters(categorized["structure"])
        first_cluster = clusters[0]
        page_range = f"{first_cluster[0]}-{first_cluster[-1]}"
        lines.append(f"  Check structure cluster: pages {page_range}")
    elif "front_matter" in categorized:
        lines.append(f"  Scan front matter region around pages {categorized['front_matter'][:3]}")
    else:
        lines.append("  Sequential scan of front matter (pages 1-20)")

    return "\n".join(lines)
