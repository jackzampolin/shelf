from infra.llm.models import LLMRequest
from infra.pipeline.storage.book_storage import BookStorage
from pipeline.ocr_pages.schemas import OlmOcrPageOutput, MistralOcrPageOutput
from ..schemas import PageRange
from .prompts import SYSTEM_PROMPT, build_user_prompt


def prepare_toc_request(
    item: int,
    storage: BookStorage,
) -> LLMRequest:
    page_num = item

    # Load from find phase (same stage as extract-toc)
    finder_result = storage.stage('extract-toc').load_file("finder_result.json")
    toc_range = PageRange(**finder_result["toc_page_range"])
    structure_notes_from_finder = finder_result.get("structure_notes") or {}
    global_structure_from_finder = finder_result.get("structure_summary")

    total_toc_pages = toc_range.end_page - toc_range.start_page + 1

    image = storage.source().load_page_image(
        page_num=page_num,
        downsample=True,
        max_payload_kb=800
    )

    ocr_stage = storage.stage('ocr-pages')
    olm_page = ocr_stage.load_page(page_num, schema=OlmOcrPageOutput, subdir="olm")
    mistral_page = ocr_stage.load_page(page_num, schema=MistralOcrPageOutput, subdir="mistral")

    mistral_text = mistral_page.get("markdown", "") if mistral_page else ""
    olm_text = olm_page.get("text", "") if olm_page else ""

    ocr_text = mistral_text if len(mistral_text) > len(olm_text) else olm_text

    page_structure_notes = structure_notes_from_finder.get(page_num, None)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(
            page_num=page_num,
            total_toc_pages=total_toc_pages,
            ocr_text=ocr_text,
            structure_notes=page_structure_notes,
            global_structure=global_structure_from_finder
        )}
    ]

    return LLMRequest(
        id=f"page_{page_num:04d}",
        messages=messages,
        images=[image],
        temperature=0.0,
        response_format={"type": "json_object"},
        timeout=300
    )
