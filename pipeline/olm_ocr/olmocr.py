"""
OlmOCR provider implementation using DeepInfra API.

Uses the olmocr toolkit's best practices:
- 1288px image resize on longest dimension
- v4 YAML prompt for structured metadata
- Returns markdown with front matter (language, rotation, table/diagram detection)
"""

import time
from PIL import Image
from typing import Dict, Any

from infra.ocr import OCRProvider, OCRResult
from infra.deepinfra.ocr import OlmOCRProvider as DeepInfraOlmOCR


def parse_olmocr_response(text: str) -> Dict[str, Any]:
    """
    Parse OlmOCR v4 YAML front matter and extract metadata + clean text.

    Args:
        text: Raw response from OlmOCR with YAML front matter

    Returns:
        Dict with parsed metadata and clean text
    """
    # Default values
    result = {
        "text": text,
        "primary_language": None,
        "is_rotation_valid": True,
        "rotation_correction": 0,
        "is_table": False,
        "is_diagram": False,
    }

    # Check if response has YAML front matter
    if not text.strip().startswith("---"):
        return result

    # Split front matter from content
    parts = text.split("---", 2)
    if len(parts) < 3:
        return result

    front_matter = parts[1].strip()
    content = parts[2].strip()

    # Parse front matter fields
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
    """
    OlmOCR provider using DeepInfra API.

    Features:
    - Images resized to 1288px on longest dimension (olmocr spec)
    - Uses build_no_anchoring_v4_yaml_prompt() for optimal results
    - Returns structured markdown with YAML front matter
    - Extracts metadata: language, rotation, table/diagram detection
    """

    def __init__(self, api_key: str = None):
        """
        Initialize OlmOCR provider.

        Args:
            api_key: DeepInfra API key (optional, reads from DEEPINFRA_API_KEY env var)
        """
        self.client = DeepInfraOlmOCR(api_key=api_key)

    @property
    def name(self) -> str:
        return "olm-ocr"

    @property
    def requests_per_second(self) -> float:
        # DeepInfra handles throttling server-side
        return float('inf')

    @property
    def max_retries(self) -> int:
        # Fail fast for OCR - no retries
        return 0

    def process_image(self, image: Image.Image, page_num: int) -> OCRResult:
        """
        Process image with OlmOCR and extract structured metadata.

        Args:
            image: PIL Image to process
            page_num: Page number for logging

        Returns:
            OCRResult with text and parsed YAML front matter metadata
        """
        start = time.time()

        try:
            # Call DeepInfra OlmOCR API
            text, usage, cost = self.client.extract_text(image)

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
