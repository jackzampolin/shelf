from infra.storage.book_storage import BookStorage


def get_merged_page_text(storage: BookStorage, page_num: int) -> str:
    ocr_stage = storage.stage("ocr")
    ocr_page = ocr_stage.load_page(page_num)

    para_correct_stage = storage.stage("paragraph_correct")
    para_correct_page = para_correct_stage.load_page(page_num)

    if not para_correct_page:
        return ocr_page.get_all_text()

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
