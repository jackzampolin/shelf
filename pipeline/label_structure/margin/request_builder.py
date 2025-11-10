from typing import Optional

from infra.llm.models import LLMRequest
from infra.pipeline.storage.book_storage import BookStorage

from .prompts import MARGIN_SYSTEM_PROMPT, build_margin_user_prompt
from .schemas import MarginObservation


def prepare_margin_request(
    item: int,
    storage: BookStorage,
    model: str,
    **kwargs
) -> Optional[LLMRequest]:
    page_num = item

    # Load page image using SourceStorage API
    page_image = storage.source().load_page_image(
        page_num=page_num,
        downsample=True,
        max_payload_kb=300
    )

    # Response schema
    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "margin_observation",
            "strict": True,
            "schema": MarginObservation.model_json_schema()
        }
    }

    user_prompt = build_margin_user_prompt()

    return LLMRequest(
        id=f"margin_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": MARGIN_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=[page_image],
        response_format=response_schema,
        metadata={
            'page_num': page_num,
            'pass': 'margin',
        }
    )
