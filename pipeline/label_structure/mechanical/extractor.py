import re
from collections import Counter
from typing import Dict, Tuple
from ..schemas.mechanical import (
    HeadingItem,
    PatternHints,
    MechanicalExtractionOutput,
)


def extract_headings(mistral_markdown: str) -> Tuple[bool, list[HeadingItem]]:
    headings = []
    lines = mistral_markdown.split('\n')
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


def detect_mistral_footnote_refs(mistral_markdown: str) -> Tuple[bool, int]:
    pattern = re.compile(r'\[\^(\d+)\]')
    matches = pattern.findall(mistral_markdown)
    return len(matches) > 0, len(matches)


def detect_repeated_symbols(text: str) -> Tuple[bool, str, int]:
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


def detect_mistral_endnote_refs(mistral_markdown: str) -> Tuple[bool, list[str]]:
    patterns = [
        r'\$\{[^\}]*\}\^\{(\d+)\}\$',
        r'\$\^\{(\d+)\}\$',
        r'\$\{(\d+)\}\$',
    ]

    markers = []
    for pattern in patterns:
        matches = re.findall(pattern, mistral_markdown)
        markers.extend(matches)

    unique_markers = sorted(set(markers), key=int)
    return len(unique_markers) > 0, unique_markers


def detect_olm_chart_tags(olm_text: str) -> Tuple[bool, int]:
    pattern = re.compile(r'<></>')
    matches = pattern.findall(olm_text)
    return len(matches) > 0, len(matches)


def detect_mistral_images(mistral_markdown: str) -> Tuple[bool, list[str]]:
    pattern = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
    matches = pattern.findall(mistral_markdown)
    image_refs = [filename for alt, filename in matches]
    return len(image_refs) > 0, image_refs


def extract_mechanical_patterns(
    mistral_markdown: str,
    olm_text: str,
    paddle_text: str
) -> MechanicalExtractionOutput:
    # Guard against None inputs (should be caught earlier, but defensive)
    mistral_markdown = mistral_markdown or ""
    olm_text = olm_text or ""
    paddle_text = paddle_text or ""

    headings_present, headings = extract_headings(mistral_markdown)
    pattern_hints = PatternHints()

    has_fn_refs, fn_count = detect_mistral_footnote_refs(mistral_markdown)
    pattern_hints.has_mistral_footnote_refs = has_fn_refs
    pattern_hints.mistral_footnote_count = fn_count

    combined_text = f"{mistral_markdown}\n{olm_text}\n{paddle_text}"
    has_symbols, symbol, symbol_count = detect_repeated_symbols(combined_text)
    pattern_hints.has_repeated_symbols = has_symbols
    pattern_hints.repeated_symbol = symbol
    pattern_hints.repeated_symbol_count = symbol_count

    has_en_refs, en_markers = detect_mistral_endnote_refs(mistral_markdown)
    pattern_hints.has_mistral_endnote_refs = has_en_refs
    pattern_hints.mistral_endnote_markers = en_markers

    has_charts, chart_count = detect_olm_chart_tags(olm_text)
    pattern_hints.has_olm_chart_tags = has_charts
    pattern_hints.olm_chart_count = chart_count

    has_images, image_refs = detect_mistral_images(mistral_markdown)
    pattern_hints.has_mistral_images = has_images
    pattern_hints.mistral_image_refs = image_refs

    return MechanicalExtractionOutput(
        headings_present=headings_present,
        headings=headings,
        pattern_hints=pattern_hints,
    )
