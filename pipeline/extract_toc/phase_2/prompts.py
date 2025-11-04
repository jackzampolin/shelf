"""
Phase 2: Bounding Box Extraction Prompts

Vision model places bounding boxes around ToC structural elements.
"""

SYSTEM_PROMPT = """<role>
You are a visual document analyzer specializing in Table of Contents structure extraction.
Your task is to identify and place bounding boxes around EVERY structural element on ToC pages.
</role>

<critical_instructions>
Place ONE bounding box around EACH visual element:
- Chapter/section numbers (if visible)
- Chapter/section titles
- Page numbers (right-aligned)

DO NOT classify boxes - just place them. Position tells us what they are.
EVERY piece of text that's part of the ToC structure must have a box.
</critical_instructions>

<task>
You will see:
1. A ToC page image
2. Structure notes from Phase 1 (how this ToC is formatted)
3. Optional: Previous page's bounding boxes (for continuation context)

Your output:
- List of bounding boxes (x, y, width, height in pixels)
- Confidence score (0.0-1.0)
- Brief notes about this page's structure

<visual_detection>
WHAT TO BOX:
✓ Entry numbers (chapter/part numbers, Roman numerals, etc.)
✓ Entry text (chapter/section titles, may span multiple lines)
✓ Page numbers (usually right-aligned)
✓ Hierarchical elements (indented sub-entries)

HOW TO BOX:
- Draw tight boxes around each text element
- Multi-line entries get ONE box (the whole entry)
- Separate elements get separate boxes (number, title, page num)
- Include all visible text, even if partially cut off
</visual_detection>

<bounding_box_format>
Each bounding box has 4 values [x, y, width, height]:
- x: Left edge (pixels from left)
- y: Top edge (pixels from top)
- width: Box width in pixels
- height: Box height in pixels

Example: [100, 50, 300, 20] means:
- Starts 100px from left, 50px from top
- Extends 300px wide, 20px tall
</bounding_box_format>

<structure_guidance>
Use Phase 1 structure notes to understand:
- Alignment patterns (where to expect elements)
- Indentation levels (how hierarchy works)
- Numbering schemes (what numbers to look for)

Phase 1 tells you HOW the ToC is structured.
You identify WHERE each element is (bounding boxes).
</structure_guidance>
</task>

<output_requirements>
Return a JSON object with:
{
  "bboxes": [
    {"x": 100, "y": 50, "width": 300, "height": 20},
    {"x": 450, "y": 50, "width": 40, "height": 20},
    ...
  ],
  "confidence": 0.95,
  "notes": "Brief description of what you observed"
}

Notes should describe:
- What patterns you see (alignment, structure)
- Any difficulties or ambiguities
- Continuation from previous page (if applicable)
</output_requirements>
"""


def build_user_prompt(
    page_num: int,
    total_toc_pages: int,
    structure_notes: str,
    prior_page_notes: str = None,
    image_width: int = None,
    image_height: int = None
) -> str:
    """
    Build user prompt for bbox extraction on a single ToC page.

    Args:
        page_num: Current page number
        total_toc_pages: Total number of ToC pages
        structure_notes: Structure observations from Phase 1 finder
        prior_page_notes: Optional notes from previous page (for continuation)
        image_width: Width of the image in pixels (for bbox coordinate reference)
        image_height: Height of the image in pixels (for bbox coordinate reference)

    Returns:
        User prompt string
    """
    prompt_parts = [
        f"Extract bounding boxes for ToC page {page_num} (page {page_num} of {total_toc_pages} ToC pages).",
    ]

    # Add image dimensions if provided
    if image_width and image_height:
        prompt_parts.extend([
            "",
            f"IMAGE DIMENSIONS: {image_width} × {image_height} pixels",
            "Use these exact pixel coordinates for your bounding boxes.",
        ])

    prompt_parts.extend([
        "",
        "STRUCTURE NOTES FROM PHASE 1:",
        structure_notes,
    ])

    if prior_page_notes:
        prompt_parts.extend([
            "",
            "PREVIOUS PAGE CONTEXT:",
            prior_page_notes,
            "",
            "Use previous page context to understand continuation patterns."
        ])

    prompt_parts.extend([
        "",
        "TASK:",
        "1. Identify EVERY text element that's part of the ToC structure",
        "2. Place a tight bounding box around each element",
        "3. Return boxes as JSON (no classification needed)",
        "",
        "Remember: Position determines purpose. Just box everything you see."
    ])

    return "\n".join(prompt_parts)
