"""
Vision-based PSM selection prompts.

Prompts for LLM to select best OCR output by comparing multiple PSM modes
against the original page image.
"""

import json
from pipeline.ocr_v2.tools.downsample import downsample_ocr_for_vision, calculate_ocr_summary_stats

SYSTEM_PROMPT = """<role>
You are an OCR quality evaluator for book digitization. Your job is to select the best OCR output for a book page by comparing multiple page segmentation modes against the original image.
</role>

<critical_instructions>
You must pick the output with the BEST STRUCTURAL CORRECTNESS - blocks and paragraphs that match the visual layout you see in the image.
</critical_instructions>

<task>
You will be shown:
1. The original page image (your source of truth)
2. Three OCR outputs from different Tesseract PSM (Page Segmentation Mode) settings:
   - PSM 3: Fully automatic page segmentation (no OSD)
   - PSM 4: Single column text
   - PSM 6: Uniform block of text

Each output has different block/paragraph structures. Your task is to select which PSM produced the most accurate structural representation of the page.

<evaluation_criteria>
Rank these criteria in order of importance:

1. **Structural Correctness** (MOST IMPORTANT)
   - Do the blocks match the visual layout boundaries in the image?
   - Are columns correctly identified?
   - Are headers/footers/body text properly separated?
   - Are footnotes/sidebars correctly distinguished?

2. **Completeness**
   - Is all visible text captured?
   - Are any text regions missing?
   - Are page numbers included?

3. **Reading Order**
   - Do blocks follow logical reading sequence?
   - Are multi-column pages handled correctly (left-to-right, top-to-bottom)?
   - Are page elements in natural reading order?

4. **Confidence** (tie-breaker only)
   - When other factors are equal, prefer higher mean confidence
   - Low confidence across all PSMs suggests difficult page
</evaluation_criteria>
</task>

<output_requirements>
You MUST return a JSON object with exactly these fields:
{
  "selected_psm": 3 | 4 | 6,
  "confidence": 0.0 to 1.0,
  "reason": "One sentence explaining why this PSM is best (max 200 chars)"
}

Your "reason" should focus on structural advantages, NOT confidence scores.

Examples of good reasons:
- "Correctly identified two-column layout with proper column boundaries"
- "Better separation of header and body text regions"
- "Captured all text including footnote at page bottom"
- "Proper single-column structure matches visual layout"

Examples of bad reasons:
- "Higher confidence score" (too vague)
- "PSM 4 is usually best" (not page-specific)
- "Looks good" (not specific)
</output_requirements>"""


def build_user_prompt(
    page_num: int,
    total_pages: int,
    book_metadata: dict = None,
    psm_outputs: dict = None,
    agreement_metrics: dict = None
) -> str:
    """
    Build page-specific vision selection prompt.

    Args:
        page_num: Current page number
        total_pages: Total pages in book
        book_metadata: Optional book metadata (title, author, etc.)
        psm_outputs: Dict mapping PSM mode to OCRPageOutput dict
        agreement_metrics: Optional agreement analysis metrics

    Returns:
        Formatted user prompt string
    """
    # Build context (metadata optional)
    prompt_parts = [
        f"**Page {page_num} of {total_pages}**",
    ]

    if book_metadata:
        title = book_metadata.get('title', 'Unknown')
        author = book_metadata.get('author', 'Unknown')
        prompt_parts.extend([
            f"Book: {title}",
            f"Author: {author}",
        ])

    prompt_parts.extend([
        "",
        "**Instructions:**",
        "1. First, carefully examine the page image below",
        "2. Identify the visual layout: columns, headers, footers, body text, footnotes",
        "3. Then review the three OCR outputs and compare their block/paragraph structure to what you see",
        "4. Select the PSM mode whose structure best matches the visual layout",
        ""
    ])

    # Note: We intentionally do NOT include agreement_metrics here
    # The LLM should make decisions based purely on visual inspection,
    # not be biased by knowing these pages "disagreed"

    # Add each PSM output with summary
    for psm_mode in [3, 4, 6]:
        if psm_mode not in psm_outputs:
            continue

        ocr_data = psm_outputs[psm_mode]

        # Calculate summary stats using utility function
        stats = calculate_ocr_summary_stats(ocr_data)

        prompt_parts.append(f"### PSM {psm_mode}")
        prompt_parts.append(f"- Blocks: {stats['num_blocks']}")
        prompt_parts.append(f"- Paragraphs: {stats['num_paragraphs']}")
        prompt_parts.append(f"- Mean confidence: {stats['mean_confidence']:.3f}")
        prompt_parts.append("")

        # Include structural summary (NO TEXT - just metadata for layout evaluation)
        # This keeps prompts small and focuses LLM on visual structure vs text comparison
        structure_summary = downsample_ocr_for_vision(ocr_data, text_preview_chars=100)

        prompt_parts.append("```json")
        prompt_parts.append(json.dumps(structure_summary, indent=2))
        prompt_parts.append("```")
        prompt_parts.append("")

    prompt_parts.append("**Your Task**: Select the best PSM mode based on structural correctness.")

    return "\n".join(prompt_parts)
