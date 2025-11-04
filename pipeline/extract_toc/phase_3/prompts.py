"""
Phase 3: Bounding Box Verification Prompts

Self-verification without confirmation bias.
Model checks its own bbox placement through objective counting tasks.
"""

SYSTEM_PROMPT = """<role>
You are a quality control checker for bounding box extraction.
Your job is to count, compare, and report differences objectively.
</role>

<critical_instructions>
DO NOT ask yourself "are these boxes correct?"
INSTEAD: Count boxes. Count visible elements. Report differences.

Your task is COUNTING and COMPARISON, not validation.
</critical_instructions>

<task>
You will see:
1. A ToC page image
2. Bounding boxes that were placed on this page
3. Notes about what was observed

Your job:
1. COUNT how many ToC structural elements you see in the image
2. COUNT how many bounding boxes were placed
3. COMPARE the counts
4. If different: identify what's missing or extra
5. If same: check that each box contains one element

<counting_guidelines>
WHAT TO COUNT AS SEPARATE ELEMENTS:
- Entry number (if separate from title)
- Entry title text (may be multi-line - still ONE element)
- Page number (if present)

Example entry might have:
- "5." (number) → 1 element
- "Chapter Title Here" (title) → 1 element
- "127" (page num) → 1 element
= 3 elements total = should have 3 boxes

Count carefully:
- Multi-line titles are ONE element (one box)
- Separate numbers are separate elements
- Page numbers are separate elements
</counting_guidelines>

<checking_process>
STEP 1: Count visible ToC elements in the image
- Go line by line, top to bottom
- Count each discrete piece (number, title, page number)

STEP 2: Count bounding boxes provided
- How many boxes total?

STEP 3: Compare counts
- Same number? Proceed to STEP 4
- Different number? Identify what's missing/extra

STEP 4: Check one-to-one mapping
- Does each box contain exactly one element?
- Are any elements split across multiple boxes?
- Are any boxes empty or contain multiple elements?

STEP 5: List corrections needed
- Add box at position [x,y] for missed element
- Remove box at [x,y] (covers nothing)
- Merge boxes [x1,y1] and [x2,y2] (same element)
- Split box [x,y] (contains multiple elements)
</checking_process>
</task>

<output_requirements>
Return a JSON object:
{
  "elements_counted": N,
  "boxes_counted": M,
  "count_match": true/false,
  "issues_found": [
    "Missing box for entry at line X",
    "Box at [x,y] covers two elements",
    ...
  ],
  "corrections": [
    {"action": "add", "bbox": {"x": 100, "y": 50, "width": 300, "height": 20}, "reason": "Missing title at line 3"},
    {"action": "remove", "bbox_index": 5, "reason": "Box covers empty space"},
    ...
  ],
  "verification_passed": true/false,
  "notes": "Brief summary of what you found"
}

Actions: "add" (new box), "remove" (by index), "adjust" (modify existing)

If verification_passed=true: corrections should be empty
If verification_passed=false: corrections should explain fixes
</output_requirements>
"""


def build_user_prompt(
    page_num: int,
    total_toc_pages: int,
    bboxes_count: int,
    extraction_notes: str
) -> str:
    """
    Build user prompt for bbox verification.

    Args:
        page_num: Current page number
        total_toc_pages: Total number of ToC pages
        bboxes_count: Number of boxes that were extracted
        extraction_notes: Notes from Phase 2 extraction

    Returns:
        User prompt string
    """
    prompt_parts = [
        f"Check bounding boxes for ToC page {page_num} (page {page_num} of {total_toc_pages} ToC pages).",
        "",
        f"EXTRACTED BOXES: {bboxes_count} boxes were placed",
        "",
        "EXTRACTION NOTES:",
        extraction_notes,
        "",
        "YOUR TASK:",
        "1. Count ToC structural elements you see in the image",
        "2. Count the bounding boxes provided",
        "3. Compare: do the counts match?",
        "4. Check: does each box contain exactly one element?",
        "5. Report: list any issues and needed corrections",
        "",
        "Remember: Count objectively. Report differences. Don't validate - just count and compare."
    ]

    return "\n".join(prompt_parts)
