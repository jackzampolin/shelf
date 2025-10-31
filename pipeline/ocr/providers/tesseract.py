import time
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from PIL import Image
import pytesseract

from .base import OCRProvider, OCRResult, OCRProviderConfig


class TesseractProvider(OCRProvider):
    def __init__(
        self,
        config: OCRProviderConfig,
        psm_mode: int = 3,
        use_opencl: bool = False,
    ):
        super().__init__(config)
        self.psm_mode = psm_mode
        self.use_opencl = use_opencl

    @property
    def provider_name(self) -> str:
        suffix = " (OpenCL)" if self.use_opencl else ""
        return f"Tesseract PSM{self.psm_mode}{suffix}"

    @property
    def supports_gpu(self) -> bool:
        return self.use_opencl

    def process_page(self, image_path: Path) -> OCRResult:
        from .parsers import (
            parse_tesseract_hierarchy,
            parse_hocr_typography,
            merge_typography_into_blocks,
        )
        from .image_detection import (
            validate_image_candidates,
            ImageDetector,
        )

        start_time = time.time()

        original_env = {}
        if self.use_opencl:
            original_env = self._enable_opencl()

        try:
            pil_image = Image.open(image_path)
            width, height = pil_image.size

            tsv_output = pytesseract.image_to_data(
                pil_image,
                lang="eng",
                config=f"--psm {self.psm_mode}",
                output_type=pytesseract.Output.STRING,
            )

            hocr_output = pytesseract.image_to_pdf_or_hocr(
                pil_image,
                lang="eng",
                config=f"--psm {self.psm_mode}",
                extension="hocr",
            )

            blocks_data, confidence_stats = parse_tesseract_hierarchy(tsv_output)

            typography_data = parse_hocr_typography(hocr_output)

            blocks_data = merge_typography_into_blocks(blocks_data, typography_data)

            text_boxes = []
            for block in blocks_data:
                for para in block["paragraphs"]:
                    text_boxes.append(para["bbox"])

            image_candidates = ImageDetector.detect_images(pil_image, text_boxes)

            confirmed_images, recovered_text_blocks = validate_image_candidates(
                pil_image, image_candidates, self.psm_mode
            )

            if recovered_text_blocks:
                for recovered_block in recovered_text_blocks:
                    new_block_num = (
                        max((b["block_num"] for b in blocks_data), default=0) + 1
                    )
                    blocks_data.append(
                        {
                            "block_num": new_block_num,
                            "bbox": recovered_block["bbox"],
                            "paragraphs": [
                                {
                                    "par_num": 0,
                                    "text": recovered_block["text"],
                                    "bbox": recovered_block["bbox"],
                                    "avg_confidence": recovered_block["confidence"],
                                    "source": "recovered_from_image",
                                    "lines": [],
                                }
                            ],
                        }
                    )

            full_text = "\n\n".join(
                para["text"]
                for block in blocks_data
                for para in block["paragraphs"]
                if para["text"].strip()
            )

            processing_time = time.time() - start_time
            tesseract_version = pytesseract.get_tesseract_version()

            metadata = {
                "page_number": None, 
                "page_dimensions": {"width": width, "height": height},
                "ocr_timestamp": datetime.now().isoformat(),
                "processing_time_seconds": processing_time,
                "psm_mode": self.psm_mode,
                "tesseract_version": str(tesseract_version),
                "confidence_mean": confidence_stats["mean_confidence"],
                "blocks_detected": len(blocks_data),
                "recovered_text_blocks_count": len(recovered_text_blocks),
                "confirmed_image_boxes": confirmed_images,
            }

            return OCRResult(
                text=full_text,
                confidence=confidence_stats["mean_confidence"],
                metadata=metadata,
                blocks=blocks_data,
            )

        finally:
            if self.use_opencl:
                self._restore_env(original_env)

    def _enable_opencl(self) -> Dict[str, Optional[str]]:
        original = {}

        opencl_vars = {
            "TESSERACT_OPENCL_DEVICE": "0",
            "OMP_THREAD_LIMIT": "1",
        }

        for key, value in opencl_vars.items():
            original[key] = os.environ.get(key)
            os.environ[key] = value

        return original

    def _restore_env(self, original: Dict[str, Optional[str]]):
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
