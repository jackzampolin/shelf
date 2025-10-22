"""
OCR Stage - Extracts text and images from page images.

Uses Tesseract for hierarchical text extraction and OpenCV for image detection.
Processes pages in parallel using ProcessPoolExecutor (CPU-bound).
"""

import json
import csv
import io
from pathlib import Path
from datetime import datetime
from PIL import Image
import cv2
import numpy as np
import pytesseract
from concurrent.futures import ProcessPoolExecutor, as_completed
import threading
import multiprocessing
from typing import Dict, Any, Tuple

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

# Import from local modules
from pipeline.ocr.schemas import OCRPageOutput, OCRPageMetrics, OCRPageReport


class OCRStage(BaseStage):
    """
    OCR Stage - First pipeline stage.

    Reads: source/*.png (page images from tools/add.py)
    Writes: ocr/page_NNNN.json (hierarchical text blocks)
    Also creates: images/ (extracted image regions)
    """

    name = "ocr"
    dependencies = []  # First stage, no dependencies

    # Schema definitions
    input_schema = None  # No input (reads raw images)
    output_schema = OCRPageOutput
    checkpoint_schema = OCRPageMetrics
    report_schema = OCRPageReport  # Quality-focused report

    def __init__(self, max_workers: int = None):
        """
        Initialize OCR stage.

        Args:
            max_workers: Number of parallel workers (default: all CPU cores)
        """
        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.progress_lock = threading.Lock()

    def before(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger):
        """Validate source images exist."""
        source_stage = storage.stage('source')
        source_pages = source_stage.list_output_pages(extension='png')

        if not source_pages:
            raise FileNotFoundError(
                f"No source page images found in {source_stage.output_dir}. "
                f"Run 'ar add <pdf>' to extract pages first."
            )

        logger.info(f"Found {len(source_pages)} source pages to OCR")

        # Ensure images directory exists
        images_dir = storage.book_dir / "images"
        
        images_dir.mkdir(exist_ok=True)

    def run(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger) -> Dict[str, Any]:
        """Process pages in parallel with Tesseract OCR."""
        # Get total pages from metadata
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        logger.start_stage(total_pages=total_pages, max_workers=self.max_workers)
        logger.info("OCR Stage - Tesseract text extraction + OpenCV image detection")

        # Get pages to process
        pages = checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)

        if not pages:
            logger.info("No pages to process (all complete)")
            return checkpoint.get_status().get('metadata', {})

        logger.info(f"Processing {len(pages)} pages with {self.max_workers} workers")

        # Build tasks for parallel processing
        tasks = []
        for page_num in pages:
            tasks.append({
                'storage_root': str(storage.storage_root),
                'scan_id': storage.scan_id,
                'page_number': page_num
            })

        # Track stats
        completed = 0
        failed = 0

        # Progress bar
        progress = RichProgressBar(
            total=len(pages),
            prefix="   ",
            width=40,
            unit="pages"
        )

        # Process in parallel using all CPU cores
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_page = {
                executor.submit(_process_page_worker, task): task['page_number']
                for task in tasks
            }

            for future in as_completed(future_to_page):
                page_num = future_to_page[future]

                try:
                    success, returned_page_num, error_msg, page_data, metrics = future.result()

                    if success:
                        # Validate metrics against schema
                        from pipeline.ocr.schemas import OCRPageMetrics
                        validated_metrics = OCRPageMetrics(**metrics)

                        # Save page output using storage API (with metrics)
                        storage.stage(self.name).save_page(
                            page_num=returned_page_num,
                            data=page_data,
                            schema=OCRPageOutput,
                            metrics=validated_metrics.model_dump()
                        )
                        completed += 1
                    else:
                        logger.error(f"Page {page_num} failed", error=error_msg)
                        failed += 1

                except Exception as e:
                    logger.error(f"Page {page_num} exception", error=str(e))
                    failed += 1

                # Update progress
                with self.progress_lock:
                    current = completed + failed
                    suffix = f"{completed} ok" + (f", {failed} failed" if failed > 0 else "")
                    progress.update(current, suffix=suffix)

        # Finish progress
        progress.finish(f"   ✓ Processed {completed}/{len(pages)} pages")

        if failed > 0:
            logger.warning(f"{failed} pages failed")

        # Return stats
        return {
            'pages_processed': completed,
            'pages_failed': failed,
            'total_cost_usd': 0.0  # No LLM cost for OCR
        }

    def after(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger, stats: Dict[str, Any]):
        """Generate OCR quality report and extract book metadata."""
        # Generate quality report from checkpoint metrics (parent implementation)
        super().after(storage, checkpoint, logger, stats)

        # Extract book metadata from first 15 pages (stage-specific)
        logger.info("Extracting book metadata from OCR text...")
        metadata_extracted = self._extract_metadata(storage, logger)

        if metadata_extracted:
            logger.info("Metadata extraction complete")
        else:
            logger.warning("Metadata extraction failed or low confidence")

    def _extract_metadata(self, storage: BookStorage, logger: PipelineLogger, num_pages: int = 15) -> bool:
        """
        Extract book metadata from first N pages of OCR output.

        Args:
            storage: BookStorage instance
            logger: Logger instance
            num_pages: Number of pages to analyze (default: 15)

        Returns:
            True if metadata extracted and updated, False otherwise
        """
        from infra.llm.client import LLMClient
        from infra.config import Config

        ocr_stage = storage.stage('ocr')
        ocr_files = sorted(ocr_stage.output_dir.glob("page_*.json"))

        if not ocr_files:
            logger.warning("No OCR files found for metadata extraction")
            return False

        # Collect text from first N pages
        pages_text = []
        for i, ocr_file in enumerate(ocr_files[:num_pages], 1):
            try:
                with open(ocr_file, 'r') as f:
                    ocr_data = json.load(f)

                # Extract all text from blocks/paragraphs
                page_text = []
                for block in ocr_data.get('blocks', []):
                    for para in block.get('paragraphs', []):
                        text = para.get('text', '').strip()
                        if text:
                            page_text.append(text)

                if page_text:
                    pages_text.append(f"--- Page {i} ---\n" + "\n".join(page_text))

            except Exception as e:
                logger.warning(f"Failed to read OCR page {i}", error=str(e))
                continue

        if not pages_text:
            logger.error("No text extracted from OCR files")
            return False

        combined_text = "\n\n".join(pages_text)
        logger.info(f"Extracted {len(combined_text)} characters from {len(pages_text)} pages")

        # Build prompt for metadata extraction
        prompt = f"""<task>
Analyze the text from the FIRST PAGES of this scanned book and extract bibliographic metadata.

These pages typically contain:
- Title page (large title text)
- Copyright page (publisher, year, ISBN)
- Table of contents
- Dedication or foreword

Extract the following information:
- title: Complete book title including subtitle
- author: Author name(s) - format as "First Last" or "First Last and First Last"
- year: Publication year (integer)
- publisher: Publisher name
- type: Book genre/type (biography, history, memoir, political_analysis, military_history, etc.)
- isbn: ISBN if visible (can be null)

Return ONLY information you can clearly identify from the text. Do not guess.
Set confidence to 0.9+ if information is on a clear title/copyright page.
Set confidence to 0.5-0.8 if inferred from content.
Set confidence below 0.5 if uncertain.
</task>

<text>
{combined_text[:15000]}
</text>

<output_format>
Return JSON only. No explanations.
</output_format>"""

        # Define JSON schema for structured output
        response_schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "book_metadata",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": ["string", "null"]},
                        "author": {"type": ["string", "null"]},
                        "year": {"type": ["integer", "null"]},
                        "publisher": {"type": ["string", "null"]},
                        "type": {"type": ["string", "null"]},
                        "isbn": {"type": ["string", "null"]},
                        "confidence": {"type": "number"}
                    },
                    "required": ["title", "author", "year", "publisher", "type", "isbn", "confidence"],
                    "additionalProperties": False
                }
            }
        }

        try:
            # Use batch client for consistent logging and telemetry
            from infra.llm.batch_client import LLMBatchClient, LLMRequest

            # Use stage-specific log directory
            stage_log_dir = storage.stage('ocr').output_dir / "logs"
            batch_client = LLMBatchClient(
                max_workers=1,
                # rate_limit uses Config.rate_limit_requests_per_minute by default
                max_retries=3,
                verbose=True,  # Enable detailed progress
                log_dir=stage_log_dir,
                log_timestamp=logger.log_file.stem.split('_', 1)[1] if hasattr(logger, 'log_file') else None
            )

            # Create single request for metadata extraction
            request = LLMRequest(
                id="metadata_extraction",
                model=Config.VISION_MODEL,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                response_format=response_schema,
                metadata={}
            )

            logger.info(
                "Calling LLM for metadata extraction",
                model=Config.VISION_MODEL,
                num_pages=len(pages_text),
                text_length=len(combined_text)
            )

            # Process batch with single request (gets full telemetry)
            results = batch_client.process_batch([request])

            if not results or len(results) == 0:
                logger.error("No result returned from metadata extraction")
                return False

            result = results[0]

            if not result.success:
                logger.error("Metadata extraction failed", error=result.error_message)
                return False

            # Parse JSON response
            metadata = json.loads(result.response)
            confidence = metadata.get('confidence', 0)

            # Log detailed extraction results with full telemetry
            logger.info(
                "Metadata extracted successfully",
                confidence=confidence,
                title=metadata.get('title', 'Unknown'),
                author=metadata.get('author', 'Unknown'),
                year=metadata.get('year', 'Unknown'),
                publisher=metadata.get('publisher', 'Unknown'),
                book_type=metadata.get('type', 'Unknown'),
                cost_usd=result.cost_usd,
                input_tokens=result.usage.get('prompt_tokens', 0),
                output_tokens=result.usage.get('completion_tokens', 0),
                reasoning_tokens=result.usage.get('reasoning_tokens', 0),
                total_tokens=result.usage.get('total_tokens', 0),
                ttft_seconds=result.ttft_seconds,
                tokens_per_second=result.tokens_per_second,
                execution_time=result.execution_time_seconds
            )

            # Only update if confidence >= 0.5
            if confidence < 0.5:
                logger.warning(f"Low confidence ({confidence:.2f}) - metadata not updated")
                return False

            # Update metadata.json
            current_metadata = storage.load_metadata()

            # Update fields (preserve existing non-None values if extraction is None)
            for field in ['title', 'author', 'year', 'publisher', 'type', 'isbn']:
                extracted_value = metadata.get(field)
                if extracted_value is not None:
                    current_metadata[field] = extracted_value

            current_metadata['metadata_extraction_confidence'] = confidence

            # Save updated metadata
            storage.save_metadata(current_metadata)

            logger.info("Metadata saved to metadata.json")
            return True

        except Exception as e:
            logger.error("Metadata extraction failed", error=str(e))
            import traceback
            logger.error("Traceback", error=traceback.format_exc())
            return False


def _process_page_worker(task: Dict[str, Any]) -> Tuple[bool, int, str, Dict[str, Any], Dict[str, Any]]:
    """
    Standalone worker function for parallel OCR processing.

    Runs in separate process via ProcessPoolExecutor.

    Args:
        task: Dict with storage_root, scan_id, page_number

    Returns:
        (success, page_number, error_msg, page_data, metrics)
    """
    import time

    try:
        start_time = time.time()

        # Reconstruct storage in worker process
        storage = BookStorage(
            scan_id=task['scan_id'],
            storage_root=Path(task['storage_root'])
        )

        page_number = task['page_number']

        # Load image from source
        page_file = storage.stage('source').output_page(page_number, extension='png')
        pil_image = Image.open(page_file)
        images_dir = storage.book_dir / "images"

        # Extract dimensions
        width, height = pil_image.size

        # Run Tesseract OCR
        tsv_output = pytesseract.image_to_data(pil_image, lang='eng', output_type=pytesseract.Output.STRING)

        # Parse TSV into hierarchical blocks (returns blocks_data and confidence stats)
        blocks_data, confidence_stats = _parse_tesseract_hierarchy(tsv_output)

        # Detect image regions
        text_boxes = []
        for block in blocks_data:
            for para in block['paragraphs']:
                text_boxes.append(para['bbox'])

        image_boxes = ImageDetector.detect_images(pil_image, text_boxes)

        # Create image regions
        images = []
        for img_id, img_box in enumerate(image_boxes, 1):
            x, y, w, h = img_box
            cropped = pil_image.crop((x, y, x + w, y + h))

            # Save to images directory
            img_path = images_dir / f"page_{page_number:04d}_img_{img_id:03d}.png"
            cropped.save(img_path)

            images.append({
                'image_id': img_id,
                'bbox': list(img_box),
                'image_file': img_path.name
            })

        # Build page data
        page_data = {
            'page_number': page_number,
            'page_dimensions': {'width': width, 'height': height},
            'ocr_timestamp': datetime.now().isoformat(),
            'blocks': blocks_data,
            'images': images
        }

        # Validate against schema
        validated_page = OCRPageOutput(**page_data)
        page_data = validated_page.model_dump()

        # Build metrics
        processing_time = time.time() - start_time
        tesseract_version = pytesseract.get_tesseract_version()

        metrics = {
            'page_num': page_number,
            'processing_time_seconds': processing_time,
            'cost_usd': 0.0,  # No cost for Tesseract
            'tesseract_version': str(tesseract_version),
            'confidence_mean': confidence_stats['mean_confidence'],
            'blocks_detected': len(blocks_data)
        }

        return (True, page_number, None, page_data, metrics)

    except Exception as e:
        return (False, task['page_number'], str(e), None, None)


def _parse_tesseract_hierarchy(tsv_string):
    """
    Parse Tesseract TSV into hierarchical blocks->paragraphs structure.

    Standalone version for use in worker processes.

    Returns:
        (blocks_list, confidence_stats) where confidence_stats contains
        'mean_confidence' and other aggregate metrics
    """
    reader = csv.DictReader(io.StringIO(tsv_string), delimiter='\t', quoting=csv.QUOTE_NONE)
    blocks = {}
    all_confidences = []  # Track all word-level confidences for stats

    for row in reader:
        try:
            level = int(row['level'])
            if level != 5:  # Word level
                continue

            block_num = int(row['block_num'])
            par_num = int(row['par_num'])
            conf = float(row['conf'])
            text = row['text'].strip()

            if conf < 0 or not text:
                continue

            left = int(row['left'])
            top = int(row['top'])
            width = int(row['width'])
            height = int(row['height'])

            # Initialize block
            if block_num not in blocks:
                blocks[block_num] = {}

            # Initialize paragraph
            para_key = par_num
            if para_key not in blocks[block_num]:
                blocks[block_num][para_key] = {
                    'words': [],
                    'confs': [],
                    'xs': [],
                    'ys': [],
                    'x2s': [],
                    'y2s': []
                }

            # Add word data
            para = blocks[block_num][para_key]
            para['words'].append(text)
            para['confs'].append(conf)
            para['xs'].append(left)
            para['ys'].append(top)
            para['x2s'].append(left + width)
            para['y2s'].append(top + height)

            # Track for page-level stats
            all_confidences.append(conf)

        except (ValueError, KeyError):
            continue

    # Convert to list format
    blocks_list = []
    for block_num in sorted(blocks.keys()):
        paragraphs_list = []

        for par_num in sorted(blocks[block_num].keys()):
            para = blocks[block_num][par_num]

            if not para['words']:
                continue

            # Combine words into text
            text = ' '.join(para['words'])

            # Calculate average confidence
            avg_conf = sum(para['confs']) / len(para['confs'])

            # Calculate paragraph bounding box
            para_bbox = [
                min(para['xs']),
                min(para['ys']),
                max(para['x2s']) - min(para['xs']),
                max(para['y2s']) - min(para['ys'])
            ]

            paragraphs_list.append({
                'par_num': par_num,
                'text': text,
                'bbox': para_bbox,
                'avg_confidence': round(avg_conf / 100, 3)
            })

        # Calculate block bounding box from all paragraphs
        if paragraphs_list:
            xs = [p['bbox'][0] for p in paragraphs_list]
            ys = [p['bbox'][1] for p in paragraphs_list]
            x2s = [p['bbox'][0] + p['bbox'][2] for p in paragraphs_list]
            y2s = [p['bbox'][1] + p['bbox'][3] for p in paragraphs_list]

            block_bbox = [
                min(xs),
                min(ys),
                max(x2s) - min(xs),
                max(y2s) - min(ys)
            ]

            blocks_list.append({
                'block_num': block_num,
                'bbox': block_bbox,
                'paragraphs': paragraphs_list
            })

    # Calculate confidence statistics
    if all_confidences:
        mean_conf = sum(all_confidences) / len(all_confidences)
        # Tesseract confidence is 0-100, normalize to 0-1
        confidence_stats = {
            'mean_confidence': round(mean_conf / 100, 3)
        }
    else:
        confidence_stats = {
            'mean_confidence': 0.0
        }

    return blocks_list, confidence_stats


class ImageDetector:
    """Detects image regions on a page using OpenCV."""

    @staticmethod
    def detect_images(pil_image, text_boxes, min_area=10000):
        """
        Detect image regions by finding large areas without text.

        Args:
            pil_image: PIL Image object
            text_boxes: List of (x, y, w, h) text bounding boxes
            min_area: Minimum area in pixels for an image region

        Returns:
            List of (x, y, w, h) image bounding boxes
        """
        # Convert PIL to OpenCV format
        img_array = np.array(pil_image)
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array

        # Create mask of text regions
        height, width = gray.shape
        text_mask = np.zeros((height, width), dtype=np.uint8)

        for x, y, w, h in text_boxes:
            # Expand text boxes slightly to avoid detecting gaps between lines
            padding = 10
            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(width, x + w + padding)
            y2 = min(height, y + h + padding)
            cv2.rectangle(text_mask, (x1, y1), (x2, y2), 255, -1)

        # Find contours in non-text regions
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        non_text = cv2.bitwise_and(cv2.bitwise_not(binary), cv2.bitwise_not(text_mask))

        contours, _ = cv2.findContours(non_text, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        image_boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = w * h

            # Filter by size and aspect ratio
            if area > min_area:
                aspect_ratio = w / h if h > 0 else 0
                if 0.2 < aspect_ratio < 5.0:
                    image_boxes.append((x, y, w, h))

        return image_boxes
