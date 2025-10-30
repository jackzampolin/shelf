"""
Tesseract OCR provider implementation.

Supports:
- Standard PSM modes (3, 4, 6, etc.)
- Optional OpenCL GPU acceleration
"""

import time
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from PIL import Image
import pytesseract

from .base import OCRProvider, OCRResult, OCRProviderConfig


class TesseractProvider(OCRProvider):
    """
    Tesseract OCR provider with configurable PSM mode.

    Extracts:
    - Full page text
    - Hierarchical blocks/paragraphs/lines
    - Typography metadata (fonts, sizes, styles)
    - Image regions with OCR validation
    - Confidence scores
    """

    def __init__(
        self,
        config: OCRProviderConfig,
        psm_mode: int = 3,
        use_opencl: bool = False,
    ):
        """
        Args:
            config: Provider configuration
            psm_mode: Page segmentation mode (default 3 = auto)
            use_opencl: Enable OpenCL GPU acceleration (experimental)
        """
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
        """
        Run Tesseract OCR on a page image.

        Args:
            image_path: Path to page PNG file

        Returns:
            OCRResult with text, confidence, blocks, and metadata

        Raises:
            Exception: If OCR processing fails
        """
        # Import parsers here to avoid circular imports
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

        # Set OpenCL environment if enabled
        original_env = {}
        if self.use_opencl:
            original_env = self._enable_opencl()

        try:
            # Load image
            pil_image = Image.open(image_path)
            width, height = pil_image.size

            # Run Tesseract OCR with specified PSM mode
            # 1. Extract TSV for hierarchical structure
            tsv_output = pytesseract.image_to_data(
                pil_image,
                lang="eng",
                config=f"--psm {self.psm_mode}",
                output_type=pytesseract.Output.STRING,
            )

            # 2. Extract hOCR for typography metadata
            hocr_output = pytesseract.image_to_pdf_or_hocr(
                pil_image,
                lang="eng",
                config=f"--psm {self.psm_mode}",
                extension="hocr",
            )

            # Parse TSV into hierarchical blocks
            blocks_data, confidence_stats = parse_tesseract_hierarchy(tsv_output)

            # Parse hOCR for typography metadata
            typography_data = parse_hocr_typography(hocr_output)

            # Merge typography into blocks
            blocks_data = merge_typography_into_blocks(blocks_data, typography_data)

            # Detect image regions
            text_boxes = []
            for block in blocks_data:
                for para in block["paragraphs"]:
                    text_boxes.append(para["bbox"])

            image_candidates = ImageDetector.detect_images(pil_image, text_boxes)

            # Validate image candidates (filter out decorative text)
            confirmed_images, recovered_text_blocks = validate_image_candidates(
                pil_image, image_candidates, self.psm_mode
            )

            # Store confirmed image boxes for caller to save
            # Don't build images_metadata here - caller will do it after saving images

            # Add recovered text blocks back to blocks_data
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

            # Extract full text
            full_text = "\n\n".join(
                para["text"]
                for block in blocks_data
                for para in block["paragraphs"]
                if para["text"].strip()
            )

            # Build metadata
            processing_time = time.time() - start_time
            tesseract_version = pytesseract.get_tesseract_version()

            metadata = {
                "page_number": None,  # Caller will set this
                "page_dimensions": {"width": width, "height": height},
                "ocr_timestamp": datetime.now().isoformat(),
                "processing_time_seconds": processing_time,
                "psm_mode": self.psm_mode,
                "tesseract_version": str(tesseract_version),
                "confidence_mean": confidence_stats["mean_confidence"],
                "blocks_detected": len(blocks_data),
                "recovered_text_blocks_count": len(recovered_text_blocks),
                "confirmed_image_boxes": confirmed_images,  # For caller to save
            }

            return OCRResult(
                text=full_text,
                confidence=confidence_stats["mean_confidence"],
                metadata=metadata,
                blocks=blocks_data,
            )

        finally:
            # Restore environment if we changed it
            if self.use_opencl:
                self._restore_env(original_env)

    def _enable_opencl(self) -> Dict[str, Optional[str]]:
        """
        Enable OpenCL for Tesseract.

        Returns:
            Original environment values to restore later
        """
        original = {}

        # Tesseract OpenCL environment variables
        opencl_vars = {
            "TESSERACT_OPENCL_DEVICE": "0",  # Use first GPU
            "OMP_THREAD_LIMIT": "1",  # Disable OpenMP (conflicts with OpenCL)
        }

        for key, value in opencl_vars.items():
            original[key] = os.environ.get(key)
            os.environ[key] = value

        return original

    def _restore_env(self, original: Dict[str, Optional[str]]):
        """Restore original environment variables"""
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
