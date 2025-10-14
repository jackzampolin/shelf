#!/usr/bin/env python3
"""
Book OCR Processor
Extracts hierarchical text blocks (Tesseract) and image regions (OpenCV)

Reads source page images from {scan_id}/source/page_XXXX.png
Writes extracted images to {scan_id}/images/page_XXXX_img_XXX.png
"""

import json
import csv
import io
import sys
from pathlib import Path
import pytesseract
from datetime import datetime
from PIL import Image
import cv2
import numpy as np
from concurrent.futures import ProcessPoolExecutor, as_completed
import threading
import multiprocessing
from typing import Tuple, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from infra.logger import create_logger
from infra.checkpoint import CheckpointManager

# Import schemas for validation
import importlib
schemas_module = importlib.import_module('pipeline.1_ocr.schemas')
OCRPageOutput = schemas_module.OCRPageOutput


def _process_page_worker(task: Dict[str, Any]) -> Tuple[bool, int, str, Dict[str, Any]]:
    """
    Standalone worker function for parallel OCR processing.

    Args:
        task: Dict with page_file, page_number, ocr_dir, images_dir

    Returns:
        (success, page_number, error_msg, page_data)
    """
    try:
        # Load image
        pil_image = Image.open(task['page_file'])
        page_number = task['page_number']
        images_dir = task['images_dir']

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
            img_filename = f"page_{page_number:04d}_img_{img_id:03d}.png"
            img_path = images_dir / img_filename
            cropped.save(img_path)

            images.append({
                'image_id': img_id,
                'bbox': list(img_box),
                'image_file': img_filename
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
                blocks[block_num] = {
                    'block_num': block_num,
                    'paragraphs': {}
                }

            block = blocks[block_num]

            # Initialize paragraph
            if par_num not in block['paragraphs']:
                block['paragraphs'][par_num] = {
                    'par_num': par_num,
                    'words': [],
                    'confidences': [],
                    'min_x': left,
                    'min_y': top,
                    'max_x': left + width,
                    'max_y': top + height
                }

            para = block['paragraphs'][par_num]
            para['words'].append(text)
            para['confidences'].append(conf)
            para['min_x'] = min(para['min_x'], left)
            para['min_y'] = min(para['min_y'], top)
            para['max_x'] = max(para['max_x'], left + width)
            para['max_y'] = max(para['max_y'], top + height)

        except (ValueError, KeyError):
            continue

    # Convert to list format
    blocks_list = []
    for block_num, block in blocks.items():
        paragraphs_list = []

        for par_num, para in block['paragraphs'].items():
            if not para['words']:
                continue

            para_bbox = [
                para['min_x'],
                para['min_y'],
                para['max_x'] - para['min_x'],
                para['max_y'] - para['min_y']
            ]
            para_text = ' '.join(para['words'])
            para_conf = sum(para['confidences']) / len(para['confidences']) / 100.0

            paragraphs_list.append({
                'par_num': par_num,
                'bbox': para_bbox,
                'text': para_text,
                'avg_confidence': round(para_conf, 3)
            })

        if not paragraphs_list:
            continue

        # Calculate block bbox
        all_bboxes = [p['bbox'] for p in paragraphs_list]
        xs = [bbox[0] for bbox in all_bboxes]
        ys = [bbox[1] for bbox in all_bboxes]
        x2s = [bbox[0] + bbox[2] for bbox in all_bboxes]
        y2s = [bbox[1] + bbox[3] for bbox in all_bboxes]

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
        # Look for darker regions (likely images) in areas without text
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
                # Most images are roughly rectangular, not extremely narrow
                if 0.2 < aspect_ratio < 5.0:
                    image_boxes.append((x, y, w, h))

        return image_boxes


class BookOCRProcessor:
    """OCR processor with hierarchical text extraction and image detection."""

    def __init__(self, storage_root=None, max_workers: Optional[int] = None, enable_checkpoints=True):
        self.storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
        # Default to all CPU cores if not specified
        self.max_workers = max_workers if max_workers is not None else multiprocessing.cpu_count()
        self.progress_lock = threading.Lock()
        self.logger = None  # Will be initialized per book
        self.checkpoint = None  # Will be initialized per book
        self.enable_checkpoints = enable_checkpoints

    def process_book(self, book_title, resume=False):
        """Process all pages for a given book from pre-extracted PNG images."""
        book_dir = self.storage_root / book_title

        if not book_dir.exists():
            print(f"❌ Book directory not found: {book_dir}")
            return

        # Load metadata
        metadata_file = book_dir / "metadata.json"
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Initialize logger for this book
        logs_dir = book_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        self.logger = create_logger(book_title, "ocr", log_dir=logs_dir)

        # Initialize checkpoint manager
        if self.enable_checkpoints:
            self.checkpoint = CheckpointManager(
                scan_id=book_title,
                stage="ocr",
                storage_root=self.storage_root,
                output_dir="ocr"
            )
            if not resume:
                self.checkpoint.reset()

        self.logger.info(f"Processing book: {metadata['title']}", resume=resume)

        # Create output directories
        ocr_dir = book_dir / "ocr"
        ocr_dir.mkdir(exist_ok=True)

        needs_review_dir = ocr_dir / "needs_review"
        needs_review_dir.mkdir(exist_ok=True)

        images_dir = book_dir / "images"
        images_dir.mkdir(exist_ok=True)

        # Get all page images from source/ directory (extracted during 'ar library add')
        source_dir = book_dir / "source"
        if not source_dir.exists():
            self.logger.error(f"Source directory not found", source_dir=str(source_dir))
            print(f"❌ Source directory not found: {source_dir}")
            print(f"   Run 'ar library add' to extract pages first.")
            return

        # Find all source page images (page_XXXX.png)
        page_files = sorted(source_dir.glob("page_*.png"))

        if not page_files:
            self.logger.error(f"No page images found in {source_dir}")
            print(f"❌ No page images found in {source_dir}")
            return

        total_pages = len(page_files)

        self.logger.start_stage(
            total_pages=total_pages,
            mode="source-images",
            max_workers=self.max_workers
        )

        print(f"📄 Processing {total_pages} pages with Tesseract OCR...")

        # Prepare tasks (filter already-completed pages if using checkpoints)
        tasks = []
        for page_file in page_files:
            # Extract page number from filename: page_0001.png -> 1
            page_num = int(page_file.stem.split('_')[1])

            # Skip if checkpoint says page is already done
            if self.checkpoint and self.checkpoint.validate_page_output(page_num):
                continue

            tasks.append({
                'page_file': page_file,
                'page_number': page_num,
                'ocr_dir': ocr_dir,
                'needs_review_dir': needs_review_dir,
                'images_dir': images_dir
            })

        # If all pages already done, skip
        if len(tasks) == 0:
            self.logger.info(f"All {total_pages} pages already completed, skipping")
            print(f"✅ All {total_pages} pages already processed")
            return

        # Process pages in parallel using ProcessPoolExecutor (true parallelism for CPU-bound Tesseract)
        completed = 0
        errors = 0
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(_process_page_worker, task): task
                for task in tasks
            }

            # Process completions as they finish
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    success, page_number, error_msg, page_data = future.result()

                    if success:
                        # Save page data
                        json_file = ocr_dir / f"page_{page_number:04d}.json"
                        with open(json_file, 'w', encoding='utf-8') as f:
                            json.dump(page_data, f, indent=2)

                        # Mark complete in checkpoint
                        if self.checkpoint:
                            self.checkpoint.mark_completed(page_number)

                        completed += 1
                    else:
                        errors += 1
                        with self.progress_lock:
                            self.logger.error(f"Page processing error", page=page_number, error=error_msg)

                except Exception as e:
                    errors += 1
                    with self.progress_lock:
                        self.logger.error(f"Page processing exception", page=task['page_number'], error=str(e))

                # Progress update
                with self.progress_lock:
                    progress_count = completed + errors
                    self.logger.progress(
                        f"Processing pages",
                        current=progress_count,
                        total=len(tasks),
                        page=task['page_number'],
                        completed=completed,
                        errors=errors
                    )

        # Mark stage complete in checkpoint
        if self.checkpoint:
            self.checkpoint.mark_stage_complete(metadata={
                "total_pages_processed": completed
            })

        # Update metadata
        metadata['ocr_complete'] = True
        metadata['ocr_completion_date'] = datetime.now().isoformat()
        metadata['total_pages_processed'] = completed

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        self.logger.info(
            "OCR complete",
            total_pages_processed=completed,
            errors=errors,
            ocr_dir=str(ocr_dir)
        )

        print(f"\n✅ OCR complete: {completed}/{total_pages} pages processed")
        if errors > 0:
            print(f"   ⚠️  {errors} pages failed")
        print(f"   Output: {ocr_dir}")

    def clean_stage(self, scan_id: str, confirm: bool = False):
        """
        Clean/delete all OCR outputs and checkpoint for a book.

        NOTE: This deletes images/ (extracted images from OCR) but preserves
        source/ (source page images extracted during 'ar library add').

        Useful for testing and re-running OCR stage from scratch.

        Args:
            scan_id: Book scan ID
            confirm: If False, prompts for confirmation before deleting

        Returns:
            bool: True if cleaned, False if cancelled
        """
        book_dir = self.storage_root / scan_id

        if not book_dir.exists():
            print(f"❌ Book directory not found: {book_dir}")
            return False

        ocr_dir = book_dir / "ocr"
        images_dir = book_dir / "images"
        checkpoint_file = book_dir / "checkpoints" / "ocr.json"
        metadata_file = book_dir / "metadata.json"

        # Count what will be deleted
        ocr_files = list(ocr_dir.glob("*.json")) if ocr_dir.exists() else []
        image_files = list(images_dir.glob("page_*_img_*.png")) if images_dir.exists() else []

        print(f"\n🗑️  Clean OCR stage for: {scan_id}")
        print(f"   OCR outputs: {len(ocr_files)} files")
        print(f"   Extracted images: {len(image_files)} files")
        print(f"   Checkpoint: {'exists' if checkpoint_file.exists() else 'none'}")
        print(f"   NOTE: Source page images (source/page_XXXX.png) will NOT be deleted")

        if not confirm:
            response = input("\n   Proceed? (yes/no): ").strip().lower()
            if response != 'yes':
                print("   Cancelled.")
                return False

        # Delete OCR outputs
        if ocr_dir.exists():
            import shutil
            shutil.rmtree(ocr_dir)
            print(f"   ✓ Deleted {len(ocr_files)} OCR files")

        # Delete extracted images directory (entire images/ directory)
        if images_dir.exists():
            import shutil
            shutil.rmtree(images_dir)
            print(f"   ✓ Deleted images/ directory ({len(image_files)} extracted images)")

        # Reset checkpoint
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            print(f"   ✓ Deleted checkpoint")

        # Update metadata
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            metadata['ocr_complete'] = False
            metadata.pop('ocr_completion_date', None)
            metadata.pop('total_pages_processed', None)

            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            print(f"   ✓ Reset metadata")

        print(f"\n✅ OCR stage cleaned for {scan_id}")
        return True