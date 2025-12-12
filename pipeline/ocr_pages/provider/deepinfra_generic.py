"""
Generic DeepInfra OCR provider.

Supports any vision-capable model on DeepInfra with configurable:
- Model identifier
- Prompt template
- Image processing settings
- Rate limiting

This allows adding new OCR models via config without code changes:

    ocr_providers:
      qwen-vl:
        type: deepinfra
        model: Qwen/Qwen2-VL-72B-Instruct
        rate_limit: 5.0

Usage:
    provider = DeepInfraGenericProvider(
        stage_storage,
        model="Qwen/Qwen2-VL-72B-Instruct",
    )
"""

import time
import io
import base64
from PIL import Image
from typing import Optional
from pydantic import BaseModel

from infra.ocr import OCRProvider, OCRResult
from infra.deepinfra import DeepInfraClient


DEFAULT_OCR_PROMPT = "Extract all text from this image. Preserve the structure and formatting as much as possible. Output only the extracted text."


class GenericOcrPageOutput(BaseModel):
    """Generic output schema for DeepInfra-based OCR."""
    page_num: int
    text: str
    char_count: int
    model_used: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class DeepInfraGenericProvider(OCRProvider):
    """Generic OCR provider for any DeepInfra-hosted vision model.

    This provider works with any vision-capable model on DeepInfra,
    allowing new models to be added via config without code changes.
    """

    def __init__(
        self,
        stage_storage,
        model: str,
        api_key: str = None,
        prompt: str = None,
        temperature: float = 0.1,
        top_p: float = 0.95,
        max_tokens: int = 8000,
        max_dimension: int = 2048,
        rate_limit: float = None,
    ):
        """Initialize DeepInfra provider.

        Args:
            stage_storage: StageStorage instance
            model: DeepInfra model identifier (e.g., "Qwen/Qwen2-VL-72B-Instruct")
            api_key: Optional API key (defaults to DEEPINFRA_API_KEY env var)
            prompt: Optional custom prompt (defaults to generic OCR prompt)
            temperature: Sampling temperature
            top_p: Top-p sampling
            max_tokens: Maximum tokens in response
            max_dimension: Maximum image dimension (larger images are resized)
            rate_limit: Optional rate limit (requests per second)
        """
        super().__init__(stage_storage)
        self.client = DeepInfraClient(api_key=api_key)
        self.model = model
        self.prompt = prompt or DEFAULT_OCR_PROMPT
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.max_dimension = max_dimension
        self._rate_limit = rate_limit

    @property
    def name(self) -> str:
        # Extract model name from full path (e.g., "Qwen2-VL" from "Qwen/Qwen2-VL-72B")
        model_name = self.model.split("/")[-1]
        # Truncate at first version indicator
        for suffix in ["-72B", "-7B", "-2B", "-1B", "-0.9B", "-Instruct"]:
            if suffix in model_name:
                model_name = model_name.split(suffix)[0]
                break
        return f"deepinfra-{model_name.lower()}"

    @property
    def requests_per_second(self) -> float:
        return self._rate_limit if self._rate_limit else float('inf')

    @property
    def max_retries(self) -> int:
        return 3

    def process_image(self, image: Image.Image, page_num: int) -> OCRResult:
        """Process image with DeepInfra vision model."""
        start = time.time()

        try:
            # Resize if needed
            if image.width > self.max_dimension or image.height > self.max_dimension:
                scale = self.max_dimension / max(image.width, image.height)
                new_width = int(image.width * scale)
                new_height = int(image.height * scale)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Convert to base64
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            # Build request
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    ]
                }
            ]

            # Call DeepInfra API
            response = self.client.chat_completion(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
            )

            if not response.choices or len(response.choices) == 0:
                raise Exception(f"No response from {self.model}")

            text = response.choices[0].message.content.strip()

            # Extract usage and cost
            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }

            cost = 0.0
            if response.usage and hasattr(response.usage, 'model_extra'):
                cost = response.usage.model_extra.get('estimated_cost', 0.0)

            return OCRResult(
                success=True,
                text=text,
                metadata={
                    "model_used": self.model,
                    "prompt_tokens": usage["prompt_tokens"],
                    "completion_tokens": usage["completion_tokens"],
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

    def handle_result(self, page_num: int, result: OCRResult, subdir: str = None, metrics_prefix: str = ""):
        """Save OCR result to disk and record metrics."""
        output = GenericOcrPageOutput(
            page_num=page_num,
            text=result.text,
            char_count=len(result.text),
            model_used=result.metadata.get("model_used", self.model),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
        )

        # Save to disk
        self.stage_storage.save_page(
            page_num,
            output.model_dump(),
            schema=GenericOcrPageOutput,
            subdir=subdir
        )

        # Record metrics
        self.stage_storage.metrics_manager.record(
            key=f"{metrics_prefix}page_{page_num:04d}",
            cost_usd=result.cost_usd,
            time_seconds=result.execution_time_seconds,
            custom_metrics={
                "page": page_num,
                "char_count": len(result.text),
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "model": self.model,
            }
        )
