import json
from typing import Optional

from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_client import LLMBatchClient, LLMRequest, LLMResult
from infra.config import Config

from ..storage import OCRStageStorage
from ..status import OCRStageStatus


def extract_metadata(
    storage: BookStorage,
    checkpoint: CheckpointManager,
    logger: PipelineLogger,
    ocr_storage: OCRStageStorage,
    num_pages: int = 15,
) -> bool:
    logger.info(f"Extracting book metadata from first {num_pages} pages...")

    selection_map = ocr_storage.load_selection_map(storage)

    pages_text = []
    for page_num in range(1, min(num_pages + 1, len(selection_map) + 1)):
        if page_num not in selection_map:
            continue

        try:
            selection = selection_map[page_num]
            provider_name = selection["provider"]

            provider_dir = ocr_storage.get_provider_dir(storage, provider_name)
            ocr_file = provider_dir / f"page_{page_num:04d}.json"

            if not ocr_file.exists():
                logger.warning(f"Page {page_num} OCR file missing: {ocr_file}")
                continue

            with open(ocr_file, 'r') as f:
                ocr_data = json.load(f)

            page_text = []
            for block in ocr_data.get('blocks', []):
                for para in block.get('paragraphs', []):
                    text = para.get('text', '').strip()
                    if text:
                        page_text.append(text)

            if page_text:
                pages_text.append(f"--- Page {page_num} ---\n" + "\n".join(page_text))

        except Exception as e:
            logger.warning(f"Failed to read OCR page {page_num}", error=str(e))
            continue

    if not pages_text:
        logger.error("No text extracted from OCR files for metadata extraction")
        return False

    combined_text = "\n\n".join(pages_text)

    prompt = f"""You are analyzing the first pages of a scanned book to extract bibliographic metadata.

<context>
The text below comes from the first {num_pages} pages of a book. These typically include:
- Title page (with full title, subtitle, author)
- Copyright page (with publisher, year, ISBN)
- Table of contents
- Dedication/epigraph pages
- Preface/introduction

Your job is to extract accurate metadata fields from this content.
</context>

<instructions>
1. Extract ONLY information that is clearly present in the text
2. Return null for any field you cannot confidently identify
3. Provide a confidence score:
   - 0.9-1.0: Clear title page + copyright page with all info
   - 0.7-0.9: Most info present, some inference needed
   - 0.5-0.7: Partial info, significant inference
   - <0.5: Very uncertain (too little info)
4. For 'type', use one of: biography, history, memoir, fiction, science, philosophy, reference, other
</instructions>

<text>
{combined_text[:15000]}  # Limit to ~15k chars to avoid token limits
</text>

Extract the following metadata fields:
- title: Full book title including subtitle
- author: Author name(s)
- year: Publication year (integer)
- publisher: Publisher name
- type: Book genre/type
- isbn: ISBN number (can be ISBN-10 or ISBN-13)
- confidence: Your confidence in this extraction (0.0-1.0)"""

    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "book_metadata",
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "author": {"type": ["string", "null"]},
                    "year": {"type": ["integer", "null"]},
                    "publisher": {"type": ["string", "null"]},
                    "type": {"type": ["string", "null"]},
                    "isbn": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                },
                "required": ["title", "author", "year", "publisher", "type", "isbn", "confidence"],
                "additionalProperties": False
            }
        }
    }

    request = LLMRequest(
        id="extract_metadata",
        model=Config.vision_model_primary,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=500,
        response_format=response_format
    )

    # Execute with batch client (single request)
    log_dir = storage.book_dir / ocr_storage.stage_name / "metadata_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    batch_client = LLMBatchClient(
        max_workers=1,
        max_retries=3,
        verbose=False,
        log_dir=log_dir
    )

    try:
        results = batch_client.process_batch(
            [request],
            on_event=None,  # No progress events for single request
            on_result=None
        )

        result = results[0]

        if not result.success:
            logger.error(f"Metadata extraction failed: {result.error_message}")
            return False

        metadata = result.parsed_json
        confidence = metadata.get("confidence", 0.0)

        logger.info(f"Metadata extracted with confidence {confidence:.2f}")

        if confidence < 0.5:
            logger.warning("Metadata confidence too low, not updating")
            return False

        current_metadata = storage.load_metadata()

        for field in ['title', 'author', 'year', 'publisher', 'type', 'isbn']:
            extracted_value = metadata.get(field)
            if extracted_value is not None:
                current_metadata[field] = extracted_value

        current_metadata['metadata_extraction_confidence'] = confidence

        storage.save_metadata(current_metadata)

        logger.info(f"✓ Metadata updated: {current_metadata.get('title')} by {current_metadata.get('author')}")
        return True

    except Exception as e:
        logger.error(f"Metadata extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False
