"""LLM-based classification of entries as front matter, body, or back matter."""

from typing import List, Dict
from dataclasses import dataclass

from infra.llm.single import LLMSingleCall, LLMSingleCallConfig
from infra.pipeline.status import PhaseStatusTracker


@dataclass
class EntryForClassification:
    entry_id: str
    title: str
    position: int  # 1-indexed position in ToC
    total_entries: int
    scan_page_start: int


CLASSIFY_SYSTEM_PROMPT = """You are a book structure analyzer. Given a list of table of contents entries from a book, classify each entry into one of three categories:

- **front_matter**: Content that appears before the main text. Examples: preface, foreword, introduction, prologue, timeline, list of characters, maps, author's note (when at start).

- **body**: The main content of the book. Examples: chapters, parts, acts, sections with numbers or dates as titles.

- **back_matter**: Content that appears after the main text. Examples: epilogue, afterword, appendix, notes, endnotes, bibliography, references, glossary, index, acknowledgments, about the author, also by author.

Consider:
1. Position in the book (early entries more likely front matter, late entries more likely back matter)
2. Title keywords and conventions
3. Surrounding context (a "Notes" section after chapters is back matter)

Return a JSON object with entry_id -> classification mapping."""


def build_classify_prompt(entries: List[EntryForClassification]) -> str:
    lines = ["Classify each entry as front_matter, body, or back_matter:\n"]

    for e in entries:
        lines.append(f"{e.position}. \"{e.title}\" (page {e.scan_page_start}) [id: {e.entry_id}]")

    lines.append("\nReturn JSON: {\"classifications\": {\"entry_id\": \"category\", ...}}")
    return "\n".join(lines)


def classify_entries(
    tracker: PhaseStatusTracker,
    entries: List[EntryForClassification],
    model: str
) -> Dict[str, str]:
    """
    Classify all entries with a single LLM call.

    Returns:
        Dict mapping entry_id -> matter_type (front_matter, body, back_matter)
    """
    if not entries:
        return {}

    prompt = build_classify_prompt(entries)

    llm = LLMSingleCall(LLMSingleCallConfig(
        tracker=tracker,
        model=model,
        call_name="classify_matter",
        metric_key="matter_classification"
    ))

    json_schema = {
        "name": "entry_classifications",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "classifications": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "string",
                        "enum": ["front_matter", "body", "back_matter"]
                    }
                }
            },
            "required": ["classifications"],
            "additionalProperties": False
        }
    }

    result = llm.call(
        messages=[
            {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        response_format={"type": "json_schema", "json_schema": json_schema}
    )

    if not result.success or not result.parsed_json:
        # Fallback: return empty dict, caller should handle
        return {}

    return result.parsed_json.get("classifications", {})
