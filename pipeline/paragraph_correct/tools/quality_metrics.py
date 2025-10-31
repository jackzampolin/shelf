import difflib
from typing import Tuple, Dict, Any

from pipeline.ocr.schemas import OCRPageOutput


def calculate_similarity_metrics(
    ocr_page: OCRPageOutput,
    correction_data: Dict[str, Any]
) -> Tuple[float, int]:
    try:
        ocr_texts = []
        for block in ocr_page.blocks:
            for para in block.paragraphs:
                ocr_texts.append(para.text)
        ocr_full_text = '\n'.join(ocr_texts)

        corrected_texts = []
        for block_idx, block in enumerate(ocr_page.blocks):
            for para_idx, para in enumerate(block.paragraphs):
                try:
                    correction_block = correction_data['blocks'][block_idx]
                    correction_para = correction_block['paragraphs'][para_idx]

                    if correction_para.get('text') is not None:
                        corrected_texts.append(correction_para['text'])
                    else:
                        corrected_texts.append(para.text)
                except (IndexError, KeyError):
                    corrected_texts.append(para.text)

        corrected_full_text = '\n'.join(corrected_texts)

    except (IndexError, KeyError, AttributeError) as e:
        return 1.0, 0

    similarity = difflib.SequenceMatcher(
        None,
        ocr_full_text,
        corrected_full_text
    ).ratio()

    matcher = difflib.SequenceMatcher(None, ocr_full_text, corrected_full_text)
    chars_changed = sum(
        abs(j2 - j1 - (i2 - i1))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
    )

    return round(similarity, 4), chars_changed
