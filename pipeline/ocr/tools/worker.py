from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from ..providers import TesseractProvider, OCRProviderConfig, OCRResult

def process_ocr_task(task: Dict[str, Any]) -> Tuple[int, str, Optional[OCRResult], Optional[str]]:
    import sys
    import traceback

    try:
        page_num = task["page_num"]
        source_file = Path(task["source_file"])
        provider_config = OCRProviderConfig(**task["provider_config"])
        provider_kwargs = task.get("provider_kwargs", {})

        provider_class = task["provider_class"]
        if provider_class == "TesseractProvider":
            provider = TesseractProvider(provider_config, **provider_kwargs)
        else:
            raise ValueError(f"Unknown provider class: {provider_class}")

        result = provider.process_page(source_file)

        result.metadata["page_number"] = page_num

        return (page_num, provider_config.name, result, None)

    except Exception as e:
        print(f"Worker error on page {task.get('page_num', '?')}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

        return (
            task.get("page_num", -1),
            task.get("provider_config", {}).get("name", "unknown"),
            None,
            str(e),
        )
