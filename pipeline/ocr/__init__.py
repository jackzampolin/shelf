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
from infra.pipeline.progress import ProgressBar

# Import from local modules
from pipeline.ocr.schemas import OCRPageOutput
from pipeline.ocr.report import generate_ocr_report, save_report


class OCRStage(BaseStage):
    """
    OCR Stage - First pipeline stage.

    Reads: source/*.png (page images from tools/add.py)
    Writes: ocr/page_NNNN.json (hierarchical text blocks)
    Also creates: images/ (extracted image regions)
    """

    name = "ocr"
    dependencies = []  # First stage, no dependencies

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
        progress = ProgressBar(
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
                    success, returned_page_num, error_msg, page_data = future.result()

                    if success:
                        # Save page output using storage API
                        storage.stage(self.name).save_page(
                            page_num=returned_page_num,
                            data=page_data,
                            schema=OCRPageOutput
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
        """Generate OCR quality report."""
        logger.info("Generating OCR quality report...")

        # Generate report from OCR outputs
        ocr_stage = storage.stage('ocr')
        report = generate_ocr_report(ocr_stage.output_dir)

        # Save report
        report_file = ocr_stage.output_dir / "ocr_report.json"
        save_report(report, report_file)

        logger.info(f"OCR report saved to {report_file}")


def _process_page_worker(task: Dict[str, Any]) -> Tuple[bool, int, str, Dict[str, Any]]:
    """
    Standalone worker function for parallel OCR processing.

    Runs in separate process via ProcessPoolExecutor.

    Args:
        task: Dict with storage_root, scan_id, page_number

    Returns:
        (success, page_number, error_msg, page_data)
    """
    try:
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

        # Parse TSV into hierarchical blocks
        blocks_data = _parse_tesseract_hierarchy(tsv_output)

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

        return (True, page_number, None, page_data)

    except Exception as e:
        return (False, task['page_number'], str(e), None)


def _parse_tesseract_hierarchy(tsv_string):
    """
    Parse Tesseract TSV into hierarchical blocks->paragraphs structure.

    Standalone version for use in worker processes.
    """
    reader = csv.DictReader(io.StringIO(tsv_string), delimiter='\t', quoting=csv.QUOTE_NONE)
    blocks = {}

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

    return blocks_list


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
