"""
Detection: Direct ToC Entry Extraction

Vision model extracts complete ToC entries (title + page number + hierarchy) in a single pass.
Loads OCR text directly from ocr-pages stage (no intermediate storage needed).
"""

import json
import time
from typing import Dict, Tuple
from pathlib import Path
from PIL import Image

from infra.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.llm.models import LLMRequest, LLMResult
from infra.utils.pdf import downsample_for_vision
from infra.config import Config

from ..schemas import PageRange, ToCEntry
from .prompts import SYSTEM_PROMPT, build_user_prompt


def extract_toc_entries(
    storage: BookStorage,
    toc_range: PageRange,
    structure_notes_from_finder: Dict[int, str],
    logger: PipelineLogger,
    global_structure_from_finder: dict = None,
    model: str = None
) -> Tuple[Dict[str, any], Dict[str, any]]:
    model = model or Config.vision_model_primary
    stage_storage_obj = storage.stage('extract-toc')

    start_time = time.time()
    total_toc_pages = toc_range.end_page - toc_range.start_page + 1

    logger.info(f"Extracting ToC entries from {total_toc_pages} pages (parallel)")

    requests = []
    source_storage = storage.stage("source")

    # Load OCR text directly from ocr-pages stage
    from pipeline.ocr_pages.schemas import OcrPagesPageOutput
    ocr_pages_storage = storage.stage('ocr-pages')

    for page_num in range(toc_range.start_page, toc_range.end_page + 1):
        # Load OCR data from ocr-pages stage
        page_data = ocr_pages_storage.load_page(page_num, schema=OcrPagesPageOutput)

        if not page_data:
            logger.error(f"  Page {page_num}: OCR data not found in ocr-pages stage")
            continue

        ocr_text = page_data.get("text", "")

        page_file = source_storage.output_dir / f"page_{page_num:04d}.png"

        if not page_file.exists():
            logger.error(f"  Page {page_num}: Source image not found: {page_file}")
            continue

        image = Image.open(page_file)
        image = downsample_for_vision(image)

        page_structure_notes = structure_notes_from_finder.get(page_num, None)

        user_prompt = build_user_prompt(
            page_num=page_num,
            total_toc_pages=total_toc_pages,
            ocr_text=ocr_text,
            structure_notes=page_structure_notes,
            global_structure=global_structure_from_finder
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]

        requests.append(LLMRequest(
            id=f"page_{page_num:04d}",
            model=model,
            messages=messages,
            images=[image],
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=300,
            metadata={"page_num": page_num}
        ))

    # Process batch with LLMBatchProcessor
    page_results = []

    def handle_result(result: LLMResult):
        """Handle completed ToC entry extraction result."""
        if result.success:
            page_num = result.request.metadata["page_num"]

            try:
                response_data = json.loads(result.response)

                # Validate entries against ToCEntry schema
                entries_raw = response_data.get("entries", [])
                entries_validated = []

                for entry in entries_raw:
                    try:
                        validated_entry = ToCEntry(**entry)
                        entries_validated.append(validated_entry.model_dump())
                    except Exception as e:
                        logger.error(f"  Page {page_num}: Invalid entry {entry}: {e}")

                page_results.append({
                    "page_num": page_num,
                    "entries": entries_validated,
                    "page_metadata": response_data.get("page_metadata", {}),
                    "confidence": response_data.get("confidence", 0.0),
                    "notes": response_data.get("notes", "")
                })

                # Metrics automatically recorded by LLMBatchProcessor

            except Exception as e:
                logger.error(f"  Page {page_num}: Failed to parse ToC entry extraction: {e}")
        else:
            page_num = result.request.metadata["page_num"]
            logger.error(f"  Page {page_num}: Failed to extract ToC entries: {result.error_message}")

    processor = LLMBatchProcessor(
        storage=storage,
        stage_name='extract-toc',
        logger=logger,
        config=LLMBatchConfig(
            model=model,
            max_workers=4,
            max_retries=3,
            batch_name="ToC entry extraction"
        )
    )

    batch_stats = processor.process_batch(
        requests=requests,
        on_result=handle_result
    )

    elapsed_time = time.time() - start_time

    # Sort page_results by page_num
    page_results.sort(key=lambda p: p["page_num"])

    results_data = {
        "pages": page_results,
        "toc_range": toc_range.model_dump(),
    }

    # Save entries.json
    stage_storage_obj.save_file("entries.json", results_data)
    logger.info(f"Saved entries.json ({len(page_results)} pages)")

    # Metrics automatically recorded by LLMBatchProcessor
