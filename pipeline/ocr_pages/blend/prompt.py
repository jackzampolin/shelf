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

BLEND_SYSTEM_PROMPT = """You are an OCR correction assistant.

You will receive:
- An IMAGE of the page (ground truth)
- MISTRAL output (authoritative markdown - preserve its structure)
- PADDLE output (comparison text, may include headers/page numbers)

Your task: Identify ONLY text corrections needed in the MISTRAL output.

RULES:
1. DO NOT suggest markdown formatting changes (no #, ##, **, etc.)
2. DO NOT change structure - only fix OCR errors (wrong characters, missing words)
3. Running headers (page numbers, chapter titles at top) are NOT errors
4. Compare against IMAGE to verify corrections are needed
5. Only output corrections you are confident about

WHAT TO CORRECT:
- Misread characters (e.g., "rn" misread as "m", "cl" as "d")
- Missing or extra words
- Spelling errors from OCR
- Punctuation errors

WHAT NOT TO CORRECT:
- Formatting or structure (headings, bold, italics)
- Running headers or page numbers
- Paragraph breaks
- Intentional author spelling/punctuation

Output JSON with:
- "corrections": array of {original, replacement, reason}
- "confidence": 0.0-1.0 overall confidence

If no corrections are needed, return empty corrections array."""


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
