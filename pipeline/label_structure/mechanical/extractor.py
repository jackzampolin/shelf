import re
from collections import Counter
from typing import Tuple, Optional
from ..schemas.mechanical import (
    HeadingItem,
    PatternHints,
    MechanicalExtractionOutput,
)


def extract_headings(markdown: str) -> Tuple[bool, list[HeadingItem]]:
    """Extract markdown headings (# syntax) from text."""
    headings = []
    lines = markdown.split('\n')
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$')

    for line_num, line in enumerate(lines, start=1):
        match = heading_pattern.match(line.strip())
        if match:
            hashes = match.group(1)
            text = match.group(2).strip()
            level = len(hashes)

            if re.search(r'[a-zA-Z0-9]', text):
                headings.append(HeadingItem(
                    level=level,
                    text=text,
                    line_number=line_num
                ))

    return len(headings) > 0, headings


def detect_footnote_refs(markdown: str) -> Tuple[bool, int]:
    """Detect [^N] style footnote references."""
    pattern = re.compile(r'\[\^(\d+)\]')
    matches = pattern.findall(markdown)
    return len(matches) > 0, len(matches)


def detect_repeated_symbols(text: str) -> Tuple[bool, str, int]:
    """Detect repeated footnote symbols (*, †, ‡, etc.)."""
    footnote_symbols = ['*', '†', '‡', '§', '¶', '‖', '#']
    symbol_counts = Counter()

    for symbol in footnote_symbols:
        count = text.count(symbol)
        if count >= 2:
            symbol_counts[symbol] = count

    if symbol_counts:
        most_common_symbol, count = symbol_counts.most_common(1)[0]
        return True, most_common_symbol, count

    return False, "", 0


def detect_endnote_refs(markdown: str) -> Tuple[bool, list[str]]:
    """Detect LaTeX-style endnote references (${}^{N}$)."""
    patterns = [
        r'\$\{[^\}]*\}\^\{(\d+)\}\$',
        r'\$\^\{(\d+)\}\$',
        r'\$\{(\d+)\}\$',
    ]

    markers = []
    for pattern in patterns:
        matches = re.findall(pattern, markdown)
        markers.extend(matches)

    if not markers:
        return False, []

    unique_markers = sorted(set(markers), key=int)
    return len(unique_markers) > 0, unique_markers


def detect_olm_chart_tags(olm_text: str) -> Tuple[bool, int]:
    """Detect OLM-specific chart tags (<></>)."""
    pattern = re.compile(r'<></>')
    matches = pattern.findall(olm_text)
    return len(matches) > 0, len(matches)


def detect_images(markdown: str) -> Tuple[bool, list[str]]:
    """Detect markdown image references (![alt](file))."""
    pattern = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
    matches = pattern.findall(markdown)
    image_refs = [filename for alt, filename in matches]
    return len(image_refs) > 0, image_refs


def extract_mechanical_patterns(
    blended_markdown: str,
    olm_text: Optional[str] = None,
) -> MechanicalExtractionOutput:
    """Extract mechanical patterns from blended OCR output.

    Uses the blended markdown as primary source for pattern detection.
    OLM text is optional, used only for OLM-specific chart tag detection.

    Args:
        blended_markdown: High-quality synthesized markdown from blend stage
        olm_text: Optional raw OLM OCR output for chart tag detection
    """
    blended_markdown = blended_markdown or ""
    olm_text = olm_text or ""

    headings_present, headings = extract_headings(blended_markdown)
    pattern_hints = PatternHints()

    # Footnote refs from blended markdown
    has_fn_refs, fn_count = detect_footnote_refs(blended_markdown)
    pattern_hints.has_mistral_footnote_refs = has_fn_refs
    pattern_hints.mistral_footnote_count = fn_count

    # Repeated symbols from blended markdown
    has_symbols, symbol, symbol_count = detect_repeated_symbols(blended_markdown)
    pattern_hints.has_repeated_symbols = has_symbols
    pattern_hints.repeated_symbol = symbol
    pattern_hints.repeated_symbol_count = symbol_count

    # Endnote refs from blended markdown
    has_en_refs, en_markers = detect_endnote_refs(blended_markdown)
    pattern_hints.has_mistral_endnote_refs = has_en_refs
    pattern_hints.mistral_endnote_markers = en_markers

    # OLM chart tags (only if OLM text provided)
    if olm_text:
        has_charts, chart_count = detect_olm_chart_tags(olm_text)
        pattern_hints.has_olm_chart_tags = has_charts
        pattern_hints.olm_chart_count = chart_count

    # Image refs from blended markdown
    has_images, image_refs = detect_images(blended_markdown)
    pattern_hints.has_mistral_images = has_images
    pattern_hints.mistral_image_refs = image_refs

    return MechanicalExtractionOutput(
        headings_present=headings_present,
        headings=headings,
        pattern_hints=pattern_hints,
    )
