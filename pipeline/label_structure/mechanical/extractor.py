import re
from collections import Counter
from typing import Tuple
from ..schemas.mechanical import (
    HeadingItem,
    PatternHints,
    MechanicalExtractionOutput,
)

HEADING_PATTERN = re.compile(r'^(#{1,6})\s+(.+)$')
FOOTNOTE_PATTERN = re.compile(r'\[\^(\d+)\]')
IMAGE_PATTERN = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
ENDNOTE_PATTERNS = [
    r'\$\{[^\}]*\}\^\{(\d+)\}\$',
    r'\$\^\{(\d+)\}\$',
    r'\$\{(\d+)\}\$',
]
FOOTNOTE_SYMBOLS = ['*', '†', '‡', '§', '¶', '‖', '#']


def extract_headings(markdown: str) -> Tuple[bool, list[HeadingItem]]:
    headings = []
    for line_num, line in enumerate(markdown.split('\n'), start=1):
        match = HEADING_PATTERN.match(line.strip())
        if match:
            text = match.group(2).strip()
            if re.search(r'[a-zA-Z0-9]', text):
                headings.append(HeadingItem(
                    level=len(match.group(1)),
                    text=text,
                    line_number=line_num
                ))
    return len(headings) > 0, headings


def detect_footnote_refs(markdown: str) -> Tuple[bool, int]:
    matches = FOOTNOTE_PATTERN.findall(markdown)
    return len(matches) > 0, len(matches)


def detect_repeated_symbols(text: str) -> Tuple[bool, str, int]:
    symbol_counts = Counter()
    for symbol in FOOTNOTE_SYMBOLS:
        count = text.count(symbol)
        if count >= 2:
            symbol_counts[symbol] = count

    if symbol_counts:
        most_common_symbol, count = symbol_counts.most_common(1)[0]
        return True, most_common_symbol, count
    return False, "", 0


def detect_endnote_refs(markdown: str) -> Tuple[bool, list[str]]:
    markers = []
    for pattern in ENDNOTE_PATTERNS:
        markers.extend(re.findall(pattern, markdown))

    if not markers:
        return False, []
    unique_markers = sorted(set(markers), key=int)
    return len(unique_markers) > 0, unique_markers


def detect_images(markdown: str) -> Tuple[bool, list[str]]:
    matches = IMAGE_PATTERN.findall(markdown)
    image_refs = [filename for alt, filename in matches]
    return len(image_refs) > 0, image_refs


def extract_mechanical_patterns(blended_markdown: str) -> MechanicalExtractionOutput:
    blended_markdown = blended_markdown or ""

    headings_present, headings = extract_headings(blended_markdown)
    pattern_hints = PatternHints()

    has_fn_refs, fn_count = detect_footnote_refs(blended_markdown)
    pattern_hints.has_footnote_refs = has_fn_refs
    pattern_hints.footnote_count = fn_count

    has_symbols, symbol, symbol_count = detect_repeated_symbols(blended_markdown)
    pattern_hints.has_repeated_symbols = has_symbols
    pattern_hints.repeated_symbol = symbol
    pattern_hints.repeated_symbol_count = symbol_count

    has_en_refs, en_markers = detect_endnote_refs(blended_markdown)
    pattern_hints.has_endnote_refs = has_en_refs
    pattern_hints.endnote_markers = en_markers

    has_images, image_refs = detect_images(blended_markdown)
    pattern_hints.has_images = has_images
    pattern_hints.image_refs = image_refs

    return MechanicalExtractionOutput(
        headings_present=headings_present,
        headings=headings,
        pattern_hints=pattern_hints,
    )
