import io
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from PIL import Image

from infra.config import Config

if TYPE_CHECKING:
    from infra.pipeline.storage.book_storage import BookStorage


class SourceStorage:
    def __init__(self, storage: 'BookStorage'):
        self.storage = storage
        self.source_dir = storage.book_dir / "source"

    def load_page_image(
        self,
        page_num: int,
        downsample: bool = False,
        max_payload_kb: Optional[int] = None
    ) -> Image.Image:
        """
        Load a source page image, optionally downsampled for vision models.

        Args:
            page_num: Page number (1-indexed)
            downsample: If True, downsample for vision model consumption
            max_payload_kb: Maximum base64 payload size in KB (default: 800)
                          Only used if downsample=True

        Returns:
            PIL Image object

        Raises:
            FileNotFoundError: If page image doesn't exist
        """
        filename = f"page_{page_num:04d}.png"
        image_path = self.source_dir / filename

        if not image_path.exists():
            raise FileNotFoundError(f"Source image not found: {image_path}")

        image = Image.open(image_path)

        if downsample:
            if max_payload_kb is None:
                max_payload_kb = 800
            image = self._downsample_for_vision(image, max_payload_kb)

        return image

    def _downsample_for_vision(
        self,
        image: Image.Image,
        max_payload_kb: int = 800
    ) -> Image.Image:
        """
        Downsample high-resolution OCR images to vision-appropriate resolution.

        Two-stage approach:
        1. DPI-based: 600 DPI → 300 DPI (50% linear reduction)
        2. Payload validation: Further reduce if needed to fit max_payload_kb

        Args:
            image: PIL Image (typically 600 DPI from source/ directory)
            max_payload_kb: Maximum base64-encoded size in KB

        Returns:
            Downsampled PIL Image
        """
        ratio = Config.pdf_extraction_dpi_vision / Config.pdf_extraction_dpi_ocr

        if ratio < 1.0:
            width, height = image.size
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=75)
        jpeg_size_kb = buffer.tell() / 1024

        estimated_payload_kb = jpeg_size_kb * 1.33

        if estimated_payload_kb <= max_payload_kb:
            return image

        reduction_needed = max_payload_kb / estimated_payload_kb
        scale_factor = reduction_needed ** 0.5

        width, height = image.size
        new_width = int(width * scale_factor)
        new_height = int(height * scale_factor)

        return image.resize((new_width, new_height), Image.Resampling.LANCZOS)
