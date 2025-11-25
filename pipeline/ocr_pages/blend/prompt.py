BLEND_SYSTEM_PROMPT = """Your task is to produce the best possible markdown transcription of a book page by combining three OCR outputs.

You will receive:
- An IMAGE of the page (this is ground truth - use it to verify accuracy)
- Three OCR transcriptions of that same page (each with different strengths)

The IMAGE is your source of truth. When OCR outputs conflict, look at the image to determine correct text and markdown structure.

OCR source characteristics:
- **Mistral**: The only output that contains native markdown structure. May trim page numbers or have text errors or miss markdown structure.
- **OlmOCR**: High accuracy text but plain text only, no formatting. generally excludes headers and page numbers.
- **PaddleOCR**: Reliable page numbers and headers. Plain text only. Rare failure modes of repeated text.

Markdown patterns to use:
- Headings: #, ##, ###, ####
- Footnotes: ${ }^{1}$, ${ }^{2}$, etc. (LaTeX superscript)
- Images: ![img-N.jpeg](img-N.jpeg)
- Tables: | col | col | with :--: alignment
- Bold: **text**
- Lists: - item

Quality checks:
- If one output differs substantially from the other two, verify against the IMAGE
- Ensure all text from the OCR outputs is included unless clearly erroneous
- Maintain original spelling and punctuation from the OCR outputs
- Keep logical paragraph breaks

Return JSON with a "markdown" field containing the synthesized markdown. No explanations in the markdown itself.
"""


BLEND_USER_PROMPT = """<mistral_ocr>
{mistral_text}
</mistral_ocr>

<olmocr>
{olm_text}
</olmocr>

<paddle_ocr>
{paddle_text}
</paddle_ocr>"""
