"""
Request builder for body structure pass.

Builds on margin pass: image + margin output → body structure.
"""

from typing import Optional
import json

from infra.llm.models import LLMRequest
from infra.pipeline.storage.book_storage import BookStorage

from .prompts import build_body_user_prompt
from .schemas import BodyObservation


def prepare_body_request(
    item: int,
    storage: BookStorage,
    model: str,
    stage_name: str,
    **kwargs
) -> Optional[LLMRequest]:
    """
    Build LLMRequest for body structure pass.

    Args:
        item: Page number to process
        storage: BookStorage
        model: Model name
        stage_name: Name of the label-structure stage
        **kwargs: Unused (for compatibility)

    Returns:
        LLMRequest for body observation
    """
    page_num = item
    label_structure_stage = storage.stage(stage_name)

    # Load page image using SourceStorage API
    page_image = storage.source().load_page_image(
        page_num=page_num,
        downsample=True,
        max_payload_kb=300
    )

    # Load margin pass output
    margin_file = label_structure_stage.output_dir / "margin" / f"page_{page_num:04d}.json"
    if not margin_file.exists():
        raise FileNotFoundError(f"Margin pass output not found for page {page_num}")

    with open(margin_file, 'r') as f:
        margin_data = json.load(f)

    # Response schema
    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "body_observation",
            "strict": True,
            "schema": BodyObservation.model_json_schema()
        }
    }

    user_prompt = build_body_user_prompt(margin_data)

    return LLMRequest(
        id=f"body_{page_num:04d}",
        model=model,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        images=[page_image],
        response_format=response_schema,
        metadata={
            'page_num': page_num,
            'pass': 'body',
        }
    )
