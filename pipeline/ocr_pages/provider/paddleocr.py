import time
import io
import base64
from PIL import Image
from typing import Dict, Any
import re

from infra.ocr import OCRProvider, OCRResult
from ..schemas.paddle import PaddleOcrPageOutput
from infra.deepinfra import DeepInfraClient

def detect_content_types(text: str) -> Dict[str, bool]:
    has_table = bool(re.search(r'\|.*\|', text))
    has_formula = bool(re.search(r'(\$.*\$|```)', text))

    chart_keywords = ['chart', 'graph', 'diagram', 'figure', 'illustration']
    has_chart = any(keyword in text.lower() for keyword in chart_keywords)

    return {
        "has_table": has_table,
        "has_formula": has_formula,
        "has_chart": has_chart,
    }

class PaddleOCRProvider(OCRProvider):
    def __init__(
        self,
        stage_storage,
        api_key: str = None,
        temperature: float = 0.1,
        top_p: float = 0.95,
        max_tokens: int = 8000,
        max_dimension: int = 2048,
    ):
        super().__init__(stage_storage)
        self.client = DeepInfraClient(api_key=api_key)
        self.model = "PaddlePaddle/PaddleOCR-VL-0.9B"

        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.max_dimension = max_dimension

    @property
    def name(self) -> str:
        return "paddle-ocr"

    @property
    def requests_per_second(self) -> float:
        return float('inf')

    @property
    def max_retries(self) -> int:
        return 3

    def process_image(self, image: Image.Image, page_num: int) -> OCRResult:
        start = time.time()

        try:
            if image.width > self.max_dimension or image.height > self.max_dimension:
                scale = self.max_dimension / max(image.width, image.height)
                new_width = int(image.width * scale)
                new_height = int(image.height * scale)
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            image_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "OCR:"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    ]
                }
            ]

            response = self.client.chat_completion(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
            )

            if not response.choices or len(response.choices) == 0:
                raise Exception("No response from PaddleOCR-VL")

            text = response.choices[0].message.content.strip()

            usage = {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            }

            cost = 0.0
            if response.usage and hasattr(response.usage, 'model_extra'):
                cost = response.usage.model_extra.get('estimated_cost', 0.0)

            content_types = detect_content_types(text)

            return OCRResult(
                success=True,
                text=text,
                metadata=content_types,
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
        output = PaddleOcrPageOutput(
            page_num=page_num,
            text=result.text,
            char_count=len(result.text),
            **result.metadata
        )

        self.stage_storage.save_page(page_num, output.model_dump(), schema=PaddleOcrPageOutput)

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
