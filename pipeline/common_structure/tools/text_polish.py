"""
LLM-based text polish for common-structure stage.

Takes mechanically cleaned text and returns a list of edits to apply.
This mimics what a human editor would do: spot-fix issues rather than rewrite.
"""

from typing import List, Optional

from infra.llm.single import LLMSingleCall, LLMSingleCallConfig
from infra.pipeline.status import PhaseStatusTracker
from infra.config import Config

from ..schemas import TextEdit, SectionText


POLISH_SYSTEM_PROMPT = """You are a text editor cleaning up OCR output from a scanned book.

Your job is to identify and fix issues in the text, returning a list of specific edits.

Common issues to fix:
1. OCR artifacts (stray characters, garbled text)
2. Page-break join issues (words split incorrectly, missing spaces)
3. Hyphenation artifacts (de-hyphenate words split across pages)
4. Inconsistent formatting (normalize markdown headers, lists)
5. Image caption remnants that don't belong in flowing text
6. Repeated headers/footers that weren't fully removed

Rules:
- ONLY return edits for actual problems
- Keep edits minimal and precise
- NEVER change the meaning or content
- NEVER rewrite sentences for style
- Preserve all substantive text
- If text looks fine, return empty edits list

Return JSON with this exact structure:
{
  "edits": [
    {
      "old_text": "exact text to find",
      "new_text": "replacement text",
      "reason": "brief explanation"
    }
  ]
}"""


def build_polish_prompt(section_title: str, text: str) -> str:
    """Build the user prompt for text polishing."""
    # Truncate if very long to avoid token limits
    max_chars = 15000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... text truncated for length ...]"

    return f"""Section: "{section_title}"

Text to review:
---
{text}
---

Analyze this text and return a JSON list of edits to fix any OCR or formatting issues.
If the text looks clean, return {{"edits": []}}."""


def polish_section_text(
    tracker: PhaseStatusTracker,
    section_title: str,
    section_text: SectionText,
    model: Optional[str] = None
) -> SectionText:
    """
    Polish section text using LLM to generate edits.

    Args:
        tracker: Phase tracker for metrics and logging
        section_title: Title of the section (for context)
        section_text: SectionText with mechanical_text populated
        model: Optional model override

    Returns:
        Updated SectionText with edits_applied and final_text
    """
    model = model or Config.default_model
    logger = tracker.logger

    if not section_text.mechanical_text:
        logger.warning(f"No mechanical text for section '{section_title}'")
        return section_text

    llm = LLMSingleCall(LLMSingleCallConfig(
        tracker=tracker,
        model=model,
        call_name=f"polish_{section_title[:20]}",
        metric_key="text_polish"
    ))

    result = llm.call(
        messages=[
            {"role": "system", "content": POLISH_SYSTEM_PROMPT},
            {"role": "user", "content": build_polish_prompt(section_title, section_text.mechanical_text)}
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "text_edits",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "edits": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "old_text": {"type": "string"},
                                    "new_text": {"type": "string"},
                                    "reason": {"type": "string"}
                                },
                                "required": ["old_text", "new_text", "reason"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["edits"],
                    "additionalProperties": False
                }
            }
        },
        max_tokens=2000,
    )

    if not result.success or not result.parsed_json:
        logger.warning(f"Polish LLM call failed for '{section_title}': {result.error_message}")
        section_text.final_text = section_text.mechanical_text
        return section_text

    # Parse edits
    edits_data = result.parsed_json.get("edits", [])
    edits: List[TextEdit] = []

    for edit_data in edits_data:
        try:
            edits.append(TextEdit(
                old_text=edit_data["old_text"],
                new_text=edit_data["new_text"],
                reason=edit_data["reason"]
            ))
        except (KeyError, TypeError) as e:
            logger.warning(f"Failed to parse edit: {e}")

    # Apply edits
    final_text = apply_edits(section_text.mechanical_text, edits, logger)

    # Update section text
    section_text.edits_applied = edits
    section_text.final_text = final_text
    section_text.word_count = len(final_text.split())

    logger.info(f"Section '{section_title}': {len(edits)} edits applied")

    return section_text


def apply_edits(text: str, edits: List[TextEdit], logger) -> str:
    """Apply a list of edits to text."""
    result = text

    for edit in edits:
        if edit.old_text in result:
            result = result.replace(edit.old_text, edit.new_text, 1)
        else:
            logger.warning(f"Edit not applied - old_text not found: '{edit.old_text[:50]}...'")

    return result
