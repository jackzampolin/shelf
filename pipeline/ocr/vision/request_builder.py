from typing import Optional, Dict, Any, List
from PIL import Image

from infra.storage.book_storage import BookStorage
from infra.llm.batch_client import LLMRequest
from infra.utils.pdf import downsample_for_vision
from infra.config import Config

from ..storage import OCRStageStorage
from ..providers import OCRProvider
from ..tools.agreement import _load_provider_outputs
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import VisionSelectionResponse


def prepare_vision_request(
    page_num: int,
    storage: BookStorage,
    model: str,
    total_pages: int,
    ocr_storage: OCRStageStorage,
    providers: List[OCRProvider],
) -> Optional[LLMRequest]:
    try:
        provider_outputs = _load_provider_outputs(
            storage, ocr_storage, providers, page_num
        )

        if len(provider_outputs) < len(providers):
            return None

        source_file = storage.stage("source").output_page(page_num, extension="png")
        if not source_file.exists():
            return None

        pil_image = Image.open(source_file)
        downsampled = downsample_for_vision(pil_image)

        psm_outputs = {}
        for provider in providers:
            psm_mode = int(provider.config.name.split("psm")[1])
            psm_outputs[psm_mode] = provider_outputs[provider.config.name]["data"]

        user_prompt = build_user_prompt(
            page_num=page_num,
            total_pages=total_pages,
            psm_outputs=psm_outputs,
        )

        request = LLMRequest(
            id=f"page_{page_num:04d}_vision",
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            images=[downsampled],
            temperature=0.0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "vision_selection",
                    "schema": VisionSelectionResponse.model_json_schema()
                }
            },
            metadata={
                "page_num": page_num,
                "provider_outputs": provider_outputs,
            },
        )

        return request

    except Exception as e:
        # Log error details, return None to skip this page
        return None
