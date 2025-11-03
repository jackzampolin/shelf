from infra.storage.book_storage import BookStorage


def get_merged_page_text(storage: BookStorage, page_num: int) -> str:
    from pipeline.ocr.storage import OCRStageStorage

    ocr_storage = OCRStageStorage(stage_name="ocr")
    ocr_page_dict = ocr_storage.load_selected_page(storage, page_num, include_line_word_data=False)

    if not ocr_page_dict:
        raise FileNotFoundError(f"Page {page_num} not found in OCR selection_map")

    from pipeline.ocr.schemas import OCRPageOutput
    ocr_page = OCRPageOutput(**ocr_page_dict)

    para_correct_stage = storage.stage("paragraph-correct")
    para_correct_page_dict = para_correct_stage.load_page(page_num)

    if not para_correct_page_dict:
        return ocr_page.get_all_text()

    from pipeline.paragraph_correct.vision.schemas import ParagraphCorrectPageOutput
    para_correct_page = ParagraphCorrectPageOutput(**para_correct_page_dict)

    correction_map = {}
    for block_correction in para_correct_page.blocks:
        for para_correction in block_correction.paragraphs:
            if para_correction.text:
                key = (block_correction.block_num, para_correction.par_num)
                correction_map[key] = para_correction.text

    merged_blocks = []
    for block in ocr_page.blocks:
        merged_paragraphs = []
        for para in block.paragraphs:
            key = (block.block_num, para.par_num)
            if key in correction_map:
                merged_paragraphs.append(correction_map[key])
            else:
                merged_paragraphs.append(para.text)

        merged_blocks.append("\n\n".join(merged_paragraphs))

    return "\n\n".join(merged_blocks)
