#!/usr/bin/env python3
"""
Book OCR Processor
Extracts hierarchical text blocks (Tesseract) and image regions (OpenCV)

Uses BookStorage APIs for all file operations.
Supports checkpoint-based resume and parallel processing.

Reads source page images via storage.stage('source').source_page()
Writes OCR outputs via storage.stage('ocr').save_page()
Writes extracted images to storage.stage('ocr').images_dir
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
from infra.pipeline.logger import create_logger
from infra.storage.book_storage import BookStorage
from infra.pipeline.progress import ProgressBar

# Import schemas and reports using importlib (module name starts with number)
import importlib
schemas_module = importlib.import_module('pipeline.1_ocr.schemas')
OCRPageOutput = schemas_module.OCRPageOutput

report_module = importlib.import_module('pipeline.1_ocr.report')
OCRStageReport = report_module.OCRStageReport
save_report = report_module.save_report


def _process_page_worker(task: Dict[str, Any]) -> Tuple[bool, int, str, Dict[str, Any]]:
    """
    Standalone worker function for parallel OCR processing.

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

            # Save to images directory using storage API
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
        self.enable_checkpoints = enable_checkpoints

    def process_book(self, book_title, resume=False):
        """Process all pages for a given book from pre-extracted PNG images."""
        try:
            # Initialize storage
            storage = BookStorage(scan_id=book_title, storage_root=self.storage_root)

            # Validate inputs (checks book exists, source pages exist)
            try:
                source_stage = storage.stage('source')
                source_pages = source_stage.list_output_pages(extension='png')
                if not source_pages:
                    raise FileNotFoundError(
                        f"No source page images found in {source_stage.output_dir}. "
                        f"Run 'ar library add' to extract pages first."
                    )
            except FileNotFoundError as e:
                print(f"❌ {e}")
                return

            # Load metadata
            metadata = storage.load_metadata()

            # Initialize logger
            log_dir = storage.book_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.logger = create_logger(
                book_title,
                "ocr",
                log_dir=log_dir,
                console_output=False
            )

            # Ensure output directories exist
            ocr_stage = storage.stage('ocr')
            ocr_stage.ensure_directories()

            # Ensure images directory exists
            images_dir = storage.book_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)

            # Get checkpoint (if enabled)
            if self.enable_checkpoints:
                checkpoint = ocr_stage.checkpoint
                if not resume:
                    if not checkpoint.reset(confirm=True):
                        print("   Use --resume to continue from checkpoint.")
                        return

            self.logger.info(f"Processing book: {metadata['title']}", resume=resume)

            # Get pages to process
            if self.enable_checkpoints:
                pages_to_process = checkpoint.get_remaining_pages(resume=resume)
                total_pages = checkpoint._state['total_pages']
            else:
                # Non-checkpoint mode: get all source pages
                total_pages = len(storage.stage('source').list_output_pages(extension='png'))
                pages_to_process = list(range(1, total_pages + 1))

            # Log to file only (not stdout)
            self.logger.start_stage(
                total_pages=total_pages,
                mode="source-images",
                max_workers=self.max_workers
            )

            # Print stage entry
            print(f"\n📄 OCR Processing ({book_title})")
            print(f"   Pages:     {total_pages}")
            print(f"   Workers:   {self.max_workers}")

            # If all pages already done, skip
            if len(pages_to_process) == 0:
                self.logger.info(f"All {total_pages} pages already completed, skipping")
                print(f"\n✅ OCR complete: {total_pages}/{total_pages} pages")
                return

            print(f"\n   Processing {len(pages_to_process)} pages with Tesseract...")

            # Prepare tasks
            tasks = []
            for page_num in pages_to_process:
                tasks.append({
                    'storage_root': str(self.storage_root),
                    'scan_id': book_title,
                    'page_number': page_num
                })

            # Process pages in parallel using ProcessPoolExecutor (true parallelism for CPU-bound Tesseract)
            completed = 0
            errors = 0

            progress = ProgressBar(
                total=len(tasks),
                prefix="   ",
                width=40,
                unit="pages"
            )

            # Adjust workers based on task count to reduce spawn overhead
            # For small task counts, using fewer workers reduces risk of spawn failures
            effective_workers = min(self.max_workers, len(tasks), 8)
            if effective_workers < self.max_workers:
                print(f"   (Using {effective_workers} workers for {len(tasks)} tasks)")

            with ProcessPoolExecutor(max_workers=effective_workers) as executor:
                # Submit all tasks
                future_to_task = {
                    executor.submit(_process_page_worker, task): task
                    for task in tasks
                }

                # Process completions as they finish
                for future in as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        # Add timeout to prevent infinite hang (5 minutes per page)
                        success, page_number, error_msg, page_data = future.result(timeout=300)

                        if success:
                            # Save page data (atomic save + checkpoint update)
                            storage.stage('ocr').save_page(
                                page_num=page_number,
                                data=page_data,
                                cost_usd=0.0  # OCR has no LLM cost
                            )

                            completed += 1
                        else:
                            errors += 1
                            # Print error on new line (won't interfere with progress bar)
                            print(f"\n   ⚠️  Page {page_number} failed: {error_msg}")
                            with self.progress_lock:
                                self.logger.error(f"Page processing error", page=page_number, error=error_msg)

                    except TimeoutError:
                        errors += 1
                        page_num = task['page_number']
                        print(f"\n   ⚠️  Page {page_num} timed out after 300s")
                        with self.progress_lock:
                            self.logger.error(f"Page processing timeout", page=page_num)

                    except Exception as e:
                        errors += 1
                        print(f"\n   ⚠️  Page {task['page_number']} exception: {str(e)}")
                        with self.progress_lock:
                            self.logger.error(f"Page processing exception", page=task['page_number'], error=str(e))

                    # Update progress bar
                    current = completed + errors
                    suffix = f"{completed} ok" + (f", {errors} failed" if errors > 0 else "")
                    progress.update(current, suffix=suffix)

            # Finish progress bar
            progress.finish(f"   ✓ {completed}/{len(tasks)} pages processed")
            if errors > 0:
                print(f"   ⚠️  {errors} pages failed")

            # Generate stage report
            print("\n   Generating stage report...")
            report = OCRStageReport()

            # Collect stats from all OCR output files
            for page_num in range(1, total_pages + 1):
                ocr_file = storage.stage('ocr').output_page(page_num)
                if ocr_file.exists():
                    try:
                        with open(ocr_file, 'r') as f:
                            page_data = json.load(f)
                        report.add_page_data(page_data)
                    except Exception as e:
                        self.logger.error(f"Failed to read page for report", page=page_num, error=str(e))

            report.finalize()

            # Save report to file
            report_file = storage.book_dir / "reports" / "ocr_report.json"
            report_file.parent.mkdir(exist_ok=True)
            save_report(report, report_file)

            # Display report
            report.print_summary()

            # Mark stage complete if no errors
            if errors == 0:
                if self.enable_checkpoints:
                    checkpoint.mark_stage_complete(metadata={
                        "total_pages_processed": completed
                    })

                # Update metadata
                storage.update_metadata({
                    'ocr_complete': True,
                    'ocr_completion_date': datetime.now().isoformat(),
                    'total_pages_processed': completed
                })

            # Log completion to file
            self.logger.info(
                "OCR complete",
                total_pages_processed=completed,
                errors=errors,
                report_file=str(report_file)
            )

            # Print stage exit
            print(f"\n✅ OCR complete: {completed}/{total_pages} pages")
            print(f"   Report saved: {report_file}")

        except Exception as e:
            # Stage-level error handler
            if self.enable_checkpoints:
                storage.stage('ocr').checkpoint.mark_stage_failed(error=str(e))
            print(f"\n❌ OCR stage failed: {e}")
            raise
        finally:
            # Always clean up logger
            if self.logger:
                self.logger.close()

    def clean_stage(self, scan_id: str, confirm: bool = False) -> bool:
        """
        Clean/delete all OCR outputs, checkpoint, and extracted images.

        Uses inherited StageView.clean_stage() with custom images cleanup.

        NOTE: This deletes images/ (extracted images from OCR) but preserves
        source/ (source page images extracted during 'ar library add').

        Args:
            scan_id: Book scan ID
            confirm: If False, prompts for confirmation before deleting

        Returns:
            bool: True if cleaned, False if cancelled
        """
        storage = BookStorage(scan_id=scan_id, storage_root=self.storage_root)

        # Count images separately (OCR-specific)
        images_dir = storage.book_dir / "images"
        image_files = list(images_dir.glob("page_*_img_*.png")) if images_dir.exists() else []

        # Show what will be deleted
        print(f"\n🗑️  Clean OCR stage for: {scan_id}")
        print(f"   OCR outputs: {len(storage.stage('ocr').list_output_pages())} files")
        print(f"   Extracted images: {len(image_files)} files")
        print(f"   Checkpoint: {'exists' if storage.checkpoint_file('ocr').exists() else 'none'}")
        print(f"   NOTE: Source page images (source/page_XXXX.png) will NOT be deleted")

        if not confirm:
            response = input("\n   Proceed? (yes/no): ").strip().lower()
            if response != 'yes':
                print("   Cancelled.")
                return False

        # Call inherited clean_stage for OCR outputs and checkpoint
        storage.stage('ocr').clean_stage(confirm=True)  # Already confirmed above

        # Clean images directory (OCR-specific)
        if images_dir.exists():
            import shutil
            shutil.rmtree(images_dir)
            print(f"   ✓ Deleted images/ directory ({len(image_files)} extracted images)")

        # Update metadata
        storage.update_metadata({
            'ocr_complete': False,
            'ocr_completion_date': None,
            'total_pages_processed': None
        })
        print(f"   ✓ Reset metadata")

        print(f"\n✅ OCR stage cleaned for {scan_id}")
        return True