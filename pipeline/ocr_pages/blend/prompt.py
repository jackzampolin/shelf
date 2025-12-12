"""
Blend prompts for diff-based OCR correction.

Approach:
1. Mistral output is authoritative (has native markdown structure)
2. LLM outputs corrections only (not full page rewrite)
3. Corrections are applied to Mistral output programmatically

Benefits:
- ~50% reduction in output tokens
- No spurious formatting (can't add what you're not rewriting)
- Mistral's markdown structure preserved
"""

BLEND_SYSTEM_PROMPT = """You are an OCR correction assistant. Compare the IMAGE (ground truth) against MISTRAL and PADDLE OCR outputs to identify text errors in MISTRAL.

CORRECT: Misread characters (rn→m, cl→d), missing/extra words, OCR spelling errors, punctuation errors.
DO NOT CORRECT: Markdown formatting, structure, running headers, page numbers, intentional author spelling.

Return corrections as {original, replacement, reason} pairs. Empty array if no corrections needed."""


BLEND_USER_PROMPT = """<mistral_ocr>
{mistral_text}
</mistral_ocr>

<paddle_ocr>
{paddle_text}
</paddle_ocr>"""


CORRECTIONS_JSON_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "ocr_corrections",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "corrections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "original": {
                                "type": "string",
                                "description": "Exact text to find in Mistral output"
                            },
                            "replacement": {
                                "type": "string",
                                "description": "Corrected text"
                            },
                            "reason": {
                                "type": "string",
                                "description": "Brief explanation"
                            }
                        },
                        "required": ["original", "replacement", "reason"],
                        "additionalProperties": False
                    },
                    "description": "List of corrections to apply"
                },
                "confidence": {
                    "type": "number",
                    "description": "Overall confidence (0.0-1.0)"
                }
            },
            "required": ["corrections", "confidence"],
            "additionalProperties": False
        }
    }
}
