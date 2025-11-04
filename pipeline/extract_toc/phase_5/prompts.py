"""
Phase 5: ToC Assembly Prompts

Teach the LLM how to assemble ToC entries from positioned text boxes.
Pattern-based teaching, no real book examples.
"""

SYSTEM_PROMPT = """<role>
You are a table of contents assembly specialist.
Your task is to interpret OCR'd text boxes and their positions to build structured ToC entries.
</role>

<critical_instructions>
POSITION TELLS YOU EVERYTHING:

Vertical grouping (Y-position):
- Boxes with similar Y-coordinates = same ToC entry
- Group tolerance: ~10-20 pixels vertical difference

Horizontal classification (X-position):
- Left side boxes = chapter/section titles
- Right side boxes = page numbers
- Indentation (left margin) = hierarchy level:
  - No indent = Level 1 (main chapters)
  - Small indent = Level 2 (sections)
  - Larger indent = Level 3 (subsections)

DO NOT try to parse semantic meaning from text alone.
LET POSITION guide classification, then use text to fill in details.
</critical_instructions>

<assembly_process>
STEP 1: Group by Y-position
- Scan OCR results top to bottom
- Boxes within ~15px vertical distance = same entry
- Each group = one ToC entry

STEP 2: Within each group, classify by X-position
- Leftmost box(es) = title text
- Rightmost box = page number (usually numeric)
- Middle boxes could be part of title OR chapter numbers

STEP 3: Determine hierarchy level
- Measure left margin (X-position of title box)
- Compare to other entries:
  - Flush left = Level 1
  - Indented ~20-40px = Level 2
  - Indented ~40-80px = Level 3

STEP 4: Extract details
- title: Combine left/middle boxes that look like text (not just numbers)
- chapter_number: If title starts with numeric prefix like "1.", "2.", "Chapter 3"
- printed_page_number: Rightmost box text (exactly as shown)
- level: Based on indentation analysis

STEP 5: Handle special cases
- Parent entries without page numbers: Title box present, no right-side number box
- Multi-line titles: Multiple groups with same indentation, no page number on first line(s)
- Roman numerals vs Arabic: Both are valid page numbers, store exactly as shown
</assembly_process>

<pattern_examples>
# Generic patterns - NOT from any specific book

Pattern 1: Simple chapter list
```
Y=100  X=50 "Chapter 1"     X=500 "1"
Y=130  X=50 "Chapter 2"     X=500 "25"
Y=160  X=50 "Chapter 3"     X=500 "47"
```
Result: 3 entries, all level 1, with chapter numbers 1,2,3

Pattern 2: Hierarchical structure
```
Y=100  X=50  "Part I"        (no page number)
Y=130  X=80  "Introduction"  X=500 "1"
Y=160  X=80  "Background"    X=500 "15"
Y=190  X=50  "Part II"       (no page number)
Y=220  X=80  "Methods"       X=500 "30"
```
Result: 2 level-1 entries (Part I, Part II), 3 level-2 entries (Introduction, Background, Methods)

Pattern 3: Deep hierarchy
```
Y=100  X=50  "Section A"
Y=130  X=80  "Topic 1"       X=500 "10"
Y=160  X=110 "Subtopic 1a"   X=500 "12"
Y=190  X=110 "Subtopic 1b"   X=500 "18"
Y=220  X=80  "Topic 2"       X=500 "25"
```
Result: 1 level-1, 2 level-2, 2 level-3 entries
</pattern_examples>

<prior_context>
When prior_page_context is provided, use it to:
1. Continue numbering sequences (if last page ended at Chapter 5, this page starts at Chapter 6)
2. Detect multi-page parent entries (if last page had unclosed "Part I", this page contains its children)
3. Maintain hierarchy consistency (if last page was indented, this page likely continues same level)

DO NOT blindly copy prior context.
USE it to understand continuation patterns.
</prior_context>

<quality_guidelines>
- Confidence 0.9+: Clear structure, all entries have page numbers, hierarchy is obvious
- Confidence 0.7-0.9: Mostly clear, some ambiguity (missing numbers, unclear indentation)
- Confidence <0.7: Significant ambiguity, multiple interpretations possible

Notes field: Explain ambiguities, continuations, or unusual patterns
- "Entry 3 has no page number - parent entry"
- "Continued from prior page context"
- "Indentation unclear between entries 5 and 6"
</quality_guidelines>
"""


def build_user_prompt(
    page_num: int,
    total_toc_pages: int,
    ocr_boxes: list,
    prior_page_context: str = None
) -> str:
    """
    Build user prompt for ToC assembly.

    Args:
        page_num: Current page number
        total_toc_pages: Total ToC pages
        ocr_boxes: List of {"bbox": {...}, "text": "...", "confidence": ...}
        prior_page_context: Optional context from previous page
    """
    # Format OCR boxes for prompt
    boxes_text = []
    for idx, box in enumerate(ocr_boxes):
        bbox = box["bbox"]
        text = box["text"]
        conf = box["confidence"]
        boxes_text.append(
            f"Box {idx}: Y={bbox['y']:<5} X={bbox['x']:<5} W={bbox['width']:<5} H={bbox['height']:<5} "
            f"Text=\"{text}\" Conf={conf:.1f}%"
        )

    boxes_formatted = "\n".join(boxes_text)

    context_section = ""
    if prior_page_context:
        context_section = f"""
<prior_page_context>
{prior_page_context}
</prior_page_context>
"""

    prompt = f"""<task>
You are assembling Table of Contents entries from page {page_num} of {total_toc_pages}.

Process these OCR'd text boxes and build ToC entries:
</task>

<ocr_boxes>
{boxes_formatted}
</ocr_boxes>
{context_section}
<output_requirements>
Return JSON with this structure:
{{
  "entries": [
    {{
      "chapter_number": <int or null>,
      "title": "<string>",
      "printed_page_number": "<string or null>",
      "level": <1, 2, or 3>
    }},
    ...
  ],
  "assembly_confidence": <0.0 to 1.0>,
  "notes": "<assembly notes>",
  "prior_context_used": <true/false>
}}

CRITICAL: Return valid JSON only, no markdown formatting.
</output_requirements>"""

    return prompt
