"""
OlmOCR provider implementation using DeepInfra API.

Uses the olmocr toolkit's best practices:
- 1288px image resize on longest dimension
- v4 YAML prompt for structured metadata
- Returns markdown with front matter (language, rotation, table/diagram detection)
"""

import time
import io
import base64
from PIL import Image
from typing import Dict, Any
from olmocr.prompts import build_no_anchoring_v4_yaml_prompt

from infra.ocr import OCRProvider, OCRResult
from infra.deepinfra import DeepInfraClient
from ..schemas.olm import OlmOcrPageOutput

def parse_olmocr_response(text: str) -> Dict[str, Any]:
    """Parse OlmOCR v4 YAML front matter and extract metadata + clean text."""
    result = {
        "text": text,
        "primary_language": None,
        "is_rotation_valid": True,
        "rotation_correction": 0,
        "is_table": False,
        "is_diagram": False,
    }

    if not text.strip().startswith("---"):
        return result

    parts = text.split("---", 2)
    if len(parts) < 3:
        return result

    front_matter = parts[1].strip()
    content = parts[2].strip()

    for line in front_matter.split("\n"):
        line = line.strip()
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        if key == "primary_language":
            result["primary_language"] = value if value != "null" else None
        elif key == "is_rotation_valid":
            result["is_rotation_valid"] = value.lower() in ("true", "1")
        elif key == "rotation_correction":
            result["rotation_correction"] = int(value)
        elif key == "is_table":
            result["is_table"] = value.lower() in ("true", "1")
        elif key == "is_diagram":
            result["is_diagram"] = value.lower() in ("true", "1")

    result["text"] = content
    return result


class OlmOCRProvider(OCRProvider):
    """OlmOCR provider using DeepInfra API."""

    def __init__(self, stage_storage, api_key: str = None):
        super().__init__(stage_storage)
        self.client = DeepInfraClient(api_key=api_key)
        self.model = "allenai/olmOCR-2-7B-1025"
        self.target_longest_dim = 1288  # olmocr spec

    @property
    def name(self) -> str:
        return "olm-ocr"

    @property
    def requests_per_second(self) -> float:
        return float('inf')  # DeepInfra handles throttling

    @property
    def max_retries(self) -> int:
        return 3

    def process_image(self, image: Image.Image, page_num: int) -> OCRResult:
        """Process image with OlmOCR and extract structured metadata."""
        start = time.time()

        try:
            # Resize to 1288px on longest dimension
            if image.width > self.target_longest_dim or image.height > self.target_longest_dim:
                scale = self.target_longest_dim / max(image.width, image.height)
                new_width = int(image.width * scale)
                new_height = int(image.height * scale)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Convert to base64
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            # Build request with olmocr v4 prompt
            prompt = build_no_anchoring_v4_yaml_prompt()
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    ]
                }
            ]

            # Call DeepInfra API
            response = self.client.chat_completion(
                model=self.model,
                messages=messages,
                max_tokens=8000,
                temperature=0.1,
            )

            if not response.choices or len(response.choices) == 0:
                raise Exception("No response from OlmOCR")

            text = response.choices[0].message.content

            # Extract usage and cost
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }

            cost = 0.0
            if response.usage and hasattr(response.usage, 'model_extra'):
                cost = response.usage.model_extra.get('estimated_cost', 0.0)

            # Parse YAML front matter
            parsed = parse_olmocr_response(text)

            return OCRResult(
                success=True,
                text=parsed["text"],
                metadata={
                    "primary_language": parsed["primary_language"],
                    "is_rotation_valid": parsed["is_rotation_valid"],
                    "rotation_correction": parsed["rotation_correction"],
                    "is_table": parsed["is_table"],
                    "is_diagram": parsed["is_diagram"],
                },
                cost_usd=cost,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                execution_time_seconds=time.time() - start,
            )

        except Exception as e:
            return OCRResult(
                success=False,
                text="",
                metadata={},
                cost_usd=0.0,
                error_message=str(e),
                execution_time_seconds=time.time() - start,
            )

    def handle_result(self, page_num: int, result: OCRResult, output_dir=None):
        """Save OCR result to disk and record metrics."""
        # Build output with provider metadata
        output = OlmOcrPageOutput(
            page_num=page_num,
            text=result.text,
            char_count=len(result.text),
            **result.metadata  # OlmOCR-specific fields
        )

        # Save to disk
        self.stage_storage.save_page(page_num, output.model_dump(), schema=OlmOcrPageOutput)

        # Record metrics
        self.stage_storage.metrics_manager.record(
            key=f"page_{page_num:04d}",
            cost_usd=result.cost_usd,
            time_seconds=result.execution_time_seconds,
            custom_metrics={
                "page": page_num,
                "char_count": len(result.text),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            }
        )
