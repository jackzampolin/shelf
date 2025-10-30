"""
Base OCR provider abstraction for pluggable OCR backends.

Allows easy experimentation with different OCR engines:
- Tesseract PSM modes (3, 4, 6, etc.)
- Tesseract with OpenCL
- Future: Cloud OCR services, custom models
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List

from pydantic import BaseModel, Field, ConfigDict


class OCRResult(BaseModel):
    """Standardized OCR result from any provider"""

    model_config = ConfigDict(validate_assignment=True)

    text: str = Field(..., description="Full extracted text")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence score (0.0-1.0)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Provider-specific metrics (word count, processing time, etc.)")
    blocks: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="""Text blocks with bounding boxes and metadata.

        Each block should have at minimum:
        - text: str
        - confidence: float
        - bbox: Optional[Dict] with x, y, width, height
        """
    )


class OCRProviderConfig(BaseModel):
    """Configuration for an OCR provider"""

    name: str = Field(..., description="Unique identifier (e.g., 'tesseract-psm3', 'tesseract-opencl-psm4')")
    enabled: bool = Field(True, description="Whether this provider should be used")
    cost_per_page: float = Field(0.0, ge=0.0, description="Cost in USD per page (for tracking, typically 0 for local OCR)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Provider-specific configuration")


class OCRProvider(ABC):
    """
    Abstract base class for OCR providers.

    Subclasses implement process_page() to run OCR on a single page image.
    """

    def __init__(self, config: OCRProviderConfig):
        self.config = config

    @abstractmethod
    def process_page(self, image_path: Path) -> OCRResult:
        """
        Process a single page image and return OCR results.

        Args:
            image_path: Path to page PNG file

        Returns:
            OCRResult with text, confidence, blocks, metadata

        Raises:
            Exception: If OCR processing fails
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name (e.g., 'Tesseract PSM3')"""
        pass

    @property
    def supports_gpu(self) -> bool:
        """Whether this provider can use GPU acceleration"""
        return False

    @property
    def is_local(self) -> bool:
        """Whether this provider runs locally (vs cloud API)"""
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.config.name}>"
