from typing import Optional, Dict, Any, List
import re
from PIL import Image

from infra.storage.book_storage import BookStorage
from infra.llm.batch_client import LLMRequest
from infra.utils.pdf import downsample_for_vision
from infra.config import Config

from ..storage import OCRStageStorage
from ..providers import OCRProvider
from ..tools.agreement import _load_provider_outputs
from ..constants import SUPPORTED_PSM_MODES
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
    provider_outputs = _load_provider_outputs(
        storage, ocr_storage, providers, page_num
    )

    if len(provider_outputs) < len(providers):
        raise ValueError(f"Page {page_num}: Missing provider outputs (expected {len(providers)}, got {len(provider_outputs)})")

    source_file = storage.stage("source").output_page(page_num, extension="png")
    if not source_file.exists():
        raise FileNotFoundError(f"Page {page_num}: Source file not found: {source_file}")

    pil_image = Image.open(source_file)
    downsampled = downsample_for_vision(pil_image)

    psm_outputs = {}
    for provider in providers:
        match = re.search(r'psm(\d+)', provider.config.name)
        if not match:
            raise ValueError(
                f"Page {page_num}: Provider name '{provider.config.name}' doesn't contain PSM mode. "
                f"Expected format: 'tesseract-psm<N>' where N is a digit"
            )

        psm_mode = int(match.group(1))

        if psm_mode not in SUPPORTED_PSM_MODES:
            raise ValueError(
                f"Page {page_num}: Unexpected PSM mode {psm_mode} from provider '{provider.config.name}'. "
                f"Supported PSM modes: {SUPPORTED_PSM_MODES}"
            )

        if provider.config.name not in provider_outputs:
            raise ValueError(
                f"Page {page_num}: Provider output not found for '{provider.config.name}'. "
                f"Available providers: {list(provider_outputs.keys())}"
            )

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
