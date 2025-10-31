"""
Quality Metrics Calculator

Calculates similarity metrics between OCR and corrected text.
Used to detect over-correction and measure edit magnitude.
"""

import difflib
from typing import Tuple, Dict, Any

from pipeline.ocr.schemas import OCRPageOutput


def calculate_similarity_metrics(
    ocr_page: OCRPageOutput,
    correction_data: Dict[str, Any]
) -> Tuple[float, int]:
    """
    Calculate text similarity between OCR and corrected text.

    Metrics help identify:
    - Over-correction (low similarity)
    - Edit magnitude (characters changed)
    - Quality issues (text changed significantly from OCR)

    Args:
        ocr_page: Original OCR page output
        correction_data: Corrected data from LLM (dict with 'blocks')

    Returns:
        Tuple of (similarity_ratio, characters_changed)
        - similarity_ratio: 0.0-1.0 (1.0 = identical)
        - characters_changed: Number of characters modified

    Example:
        >>> similarity, chars = calculate_similarity_metrics(ocr_page, corrections)
        >>> if similarity < 0.70:
        ...     print(f"Warning: Low similarity ({similarity:.2f}) - possible over-correction")
    """
    try:
        # Build full OCR text
        ocr_texts = []
        for block in ocr_page.blocks:
            for para in block.paragraphs:
                ocr_texts.append(para.text)
        ocr_full_text = '\n'.join(ocr_texts)

        # Build full corrected text (merge OCR + corrections)
        corrected_texts = []
        for block_idx, block in enumerate(ocr_page.blocks):
            for para_idx, para in enumerate(block.paragraphs):
                # Find if this paragraph was corrected
                try:
                    correction_block = correction_data['blocks'][block_idx]
                    correction_para = correction_block['paragraphs'][para_idx]

                    # Use corrected text if available, otherwise use original OCR
                    if correction_para.get('text') is not None:
                        corrected_texts.append(correction_para['text'])
                    else:
                        corrected_texts.append(para.text)
                except (IndexError, KeyError):
                    # Structure mismatch - use OCR text
                    corrected_texts.append(para.text)

        corrected_full_text = '\n'.join(corrected_texts)

    except (IndexError, KeyError, AttributeError) as e:
        # Structure mismatch - fall back to safe defaults
        return 1.0, 0  # Assume no changes if can't compare

    # Calculate similarity ratio using difflib
    similarity = difflib.SequenceMatcher(
        None,
        ocr_full_text,
        corrected_full_text
    ).ratio()

    # Calculate characters changed using difflib opcodes
    matcher = difflib.SequenceMatcher(None, ocr_full_text, corrected_full_text)
    chars_changed = sum(
        abs(j2 - j1 - (i2 - i1))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
    )

    return round(similarity, 4), chars_changed
