"""
Mistral OCR provider implementation using Mistral AI API.

Uses Mistral's native OCR API:
- Returns markdown with preserved structure
- Detects images with bounding boxes
- Provides page dimensions and DPI
- Fixed cost: $0.002 per page
- Rate limit: 6 requests/second
"""

import time
import base64
import os
from pathlib import Path
from PIL import Image
from typing import Dict, Any
from mistralai import Mistral

from infra.ocr import OCRProvider, OCRResult
from ..schemas.mistral import MistralOcrPageOutput, ImageBBox, PageDimensions


# Mistral OCR pricing and rate limits (as of 2025-11)
# TODO: Update if pricing changes - check https://mistral.ai/pricing
# Base OCR: $1/1000 pages = $0.001
# Annotations (bboxes): $3/1000 pages = $0.003
# Total: $0.004 per page (we use annotations for image detection)
MISTRAL_OCR_COST_PER_PAGE = 0.004  # $0.004 per page


def encode_image(image_path: Path) -> str:
    """Encode image file to base64."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


class MistralOCRProvider(OCRProvider):
    """Mistral OCR provider using Mistral AI API."""

    def __init__(self, stage_storage, api_key: str = None, include_images: bool = False):
        super().__init__(stage_storage)
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise ValueError("MISTRAL_API_KEY environment variable not set")

        self.client = Mistral(api_key=self.api_key)
        self.model = "mistral-ocr-latest"
        self.include_images = include_images

    @property
    def name(self) -> str:
        return "mistral-ocr"

    @property
    def requests_per_second(self) -> float:
        return 6.0  # Mistral OCR rate limit

    @property
    def max_retries(self) -> int:
        return 3

    def process_image(self, image: Image.Image, page_num: int) -> OCRResult:
        """Process image with Mistral OCR."""
        start = time.time()

        try:
            # Save image to temporary buffer for base64 encoding
            # (Mistral API expects base64-encoded image)
            from io import BytesIO
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            # Call Mistral OCR API
            ocr_response = self.client.ocr.process(
                model=self.model,
                document={
                    "type": "image_url",
                    "image_url": f"data:image/png;base64,{image_base64}"
                },
                include_image_base64=self.include_images
            )

            # Check response has pages
            if not ocr_response.pages or len(ocr_response.pages) == 0:
                raise Exception("No pages in OCR response")

            # Get first page (single image = single page)
            page_data = ocr_response.pages[0]

            # Extract images with bboxes
            images = []
            if hasattr(page_data, 'images') and page_data.images:
                for img in page_data.images:
                    images.append(ImageBBox(
                        top_left_x=img.top_left_x,
                        top_left_y=img.top_left_y,
                        bottom_right_x=img.bottom_right_x,
                        bottom_right_y=img.bottom_right_y,
                        image_base64=img.image_base64 if self.include_images else None
                    ))

            # Extract dimensions
            dimensions = PageDimensions(
                width=page_data.dimensions.width,
                height=page_data.dimensions.height,
                dpi=page_data.dimensions.dpi if hasattr(page_data.dimensions, 'dpi') else None
            )

            return OCRResult(
                success=True,
                text=page_data.markdown,
                metadata={
                    "dimensions": dimensions.model_dump(),
                    "images": [img.model_dump() for img in images],
                    "model_used": ocr_response.model,
                },
                cost_usd=MISTRAL_OCR_COST_PER_PAGE,
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
        # Reconstruct structured objects from metadata
        dimensions = PageDimensions(**result.metadata["dimensions"])
        images = [ImageBBox(**img) for img in result.metadata["images"]]

        # Build output with provider metadata
        output = MistralOcrPageOutput(
            page_num=page_num,
            markdown=result.text,
            char_count=len(result.text),
            dimensions=dimensions,
            images=images,
            model_used=result.metadata["model_used"],
            processing_cost=result.cost_usd
        )

        # Save to disk
        self.stage_storage.save_page(page_num, output.model_dump(), schema=MistralOcrPageOutput)

        # Record metrics
        self.stage_storage.metrics_manager.record(
            key=f"page_{page_num:04d}",
            cost_usd=result.cost_usd,
            time_seconds=result.execution_time_seconds,
            custom_metrics={
                "page": page_num,
                "char_count": len(result.text),
                "images_detected": len(images),
                "model": result.metadata["model_used"],
            }
        )
