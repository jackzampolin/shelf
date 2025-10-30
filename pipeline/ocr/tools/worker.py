"""
Standalone worker function for parallel OCR processing.

Must be top-level function (not class method) for ProcessPoolExecutor pickling.
"""

from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from ..providers import TesseractProvider, OCRProviderConfig, OCRResult


def process_ocr_task(task: Dict[str, Any]) -> Tuple[int, str, Optional[OCRResult], Optional[str]]:
    """
    Standalone worker for parallel OCR processing.

    Args:
        task: Dict with:
            - page_num: int
            - source_file: Path to source PNG
            - provider_config: Dict with provider configuration
            - provider_class: str (class name)
            - provider_kwargs: Dict (constructor kwargs)

    Returns:
        (page_num, provider_name, OCRResult or None, error_msg or None)
    """
    import sys
    import traceback

    try:
        page_num = task["page_num"]
        source_file = Path(task["source_file"])
        provider_config = OCRProviderConfig(**task["provider_config"])
        provider_kwargs = task.get("provider_kwargs", {})

        # Reconstruct provider (only Tesseract for now)
        provider_class = task["provider_class"]
        if provider_class == "TesseractProvider":
            provider = TesseractProvider(provider_config, **provider_kwargs)
        else:
            raise ValueError(f"Unknown provider class: {provider_class}")

        # Run OCR
        result = provider.process_page(source_file)

        # Add page number to metadata
        result.metadata["page_number"] = page_num

        return (page_num, provider_config.name, result, None)

    except Exception as e:
        # Print to stderr for debugging worker crashes
        print(f"Worker error on page {task.get('page_num', '?')}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

        return (
            task.get("page_num", -1),
            task.get("provider_config", {}).get("name", "unknown"),
            None,
            str(e),
        )
