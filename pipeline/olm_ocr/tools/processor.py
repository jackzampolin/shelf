from typing import Dict, Any, List
from PIL import Image
import re

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.deepinfra import DeepInfraOCRBatchProcessor, OCRRequest, OCRResult

from ..schemas import OlmOcrPageOutput


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


def process_batch(
    storage: BookStorage,
    logger: PipelineLogger,
    remaining_pages: List[int],
    max_workers: int
) -> Dict[str, Any]:

    requests = []
    source_storage = storage.stage("source")

    for page_num in remaining_pages:
        page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

        if not page_file.exists():
            logger.error(f"  Page {page_num}: Source image not found: {page_file}")
            continue

        image = Image.open(page_file)
        # Use olmocr toolkit's default v4 YAML prompt (set in OlmOCRProvider)
        # This returns structured markdown with metadata front matter

        requests.append(OCRRequest(
            id=f"page_{page_num:04d}",
            image=image,
            prompt=None,  # Use default olmocr prompt
            metadata={"page_num": page_num}
        ))

    stage_storage = storage.stage("olm-ocr")
    pages_processed = 0

    def handle_result(result: OCRResult):
        nonlocal pages_processed

        if result.success:
            page_num = result.request.metadata["page_num"]

            # Parse OlmOCR v4 YAML front matter
            parsed = parse_olmocr_response(result.text)

            page_data = {
                "page_num": page_num,
                "text": parsed["text"],
                "char_count": len(parsed["text"]),
                "primary_language": parsed["primary_language"],
                "is_rotation_valid": parsed["is_rotation_valid"],
                "rotation_correction": parsed["rotation_correction"],
                "is_table": parsed["is_table"],
                "is_diagram": parsed["is_diagram"],
            }

            stage_storage.save_page(
                page_num,
                page_data,
                schema=OlmOcrPageOutput
            )

            stage_storage.metrics_manager.record(
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

            pages_processed += 1
        else:
            page_num = result.request.metadata["page_num"]
            logger.error(f"  Page {page_num}: OCR failed: {result.error_message}")

    processor = DeepInfraOCRBatchProcessor(
        logger=logger,
        max_workers=max_workers,
        verbose=True,
        batch_name="OCR Pages (OlmOCR)"
    )

    batch_stats = processor.process_batch(
        requests=requests,
        on_result=handle_result
    )

    logger.info(
        "OCR-Pages complete",
        pages_processed=pages_processed,
        cost=f"${batch_stats['total_cost_usd']:.4f}"
    )

    return {
        "status": "success",
        "pages_processed": pages_processed,
        "cost_usd": batch_stats["total_cost_usd"]
    }
