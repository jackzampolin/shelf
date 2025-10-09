#!/usr/bin/env python3
"""
Book OCR Processor
Extracts hierarchical text blocks (Tesseract) and image regions (OpenCV)
"""

import json
import csv
import io
import sys
from pathlib import Path
from pdf2image import convert_from_path
import pytesseract
from datetime import datetime
from PIL import Image
import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from infra.logger import create_logger
from infra.checkpoint import CheckpointManager

# Import schemas for validation
import importlib
schemas_module = importlib.import_module('pipeline.1_ocr.schemas')
OCRPageOutput = schemas_module.OCRPageOutput


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

    def __init__(self, storage_root=None, max_workers=8, enable_checkpoints=True):
        self.storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
        self.max_workers = max_workers
        self.progress_lock = threading.Lock()
        self.logger = None  # Will be initialized per book
        self.checkpoint = None  # Will be initialized per book
        self.enable_checkpoints = enable_checkpoints

    def process_book(self, book_title, resume=False):
        """Process all batches for a given book."""
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

        needs_review_dir = book_dir / "ocr" / "needs_review"
        needs_review_dir.mkdir(exist_ok=True)

        images_dir = book_dir / "images"
        images_dir.mkdir(exist_ok=True)

        # Check if using old batch structure or new simple structure
        if 'batches' in metadata and metadata['batches']:
            # Old batch-based structure
            self.logger.start_stage(
                total_batches=len(metadata['batches']),
                estimated_pages=metadata.get('total_pages', 'unknown'),
                mode="batch-based",
                max_workers=self.max_workers
            )

            total_pages = 0
            for batch_info in metadata['batches']:
                batch_num = batch_info['batch_number']
                pdf_path = book_dir / "source" / "batches" / f"batch_{batch_num:03d}" / batch_info['filename']

                if not pdf_path.exists():
                    self.logger.warning(f"Batch {batch_num} PDF not found", batch=batch_num, pdf_path=str(pdf_path))
                    continue

                pages_processed = self.process_batch(
                    pdf_path,
                    batch_num,
                    ocr_dir,
                    images_dir,
                    batch_info['page_start'],
                    batch_info['page_end']
                )
                total_pages += pages_processed

                # Update batch status
                batch_info['ocr_status'] = 'complete'
                batch_info['ocr_timestamp'] = datetime.now().isoformat()

        else:
            # New simple structure - PDFs directly in source/
            source_dir = book_dir / "source"
            pdf_files = sorted(source_dir.glob("*.pdf"))

            if not pdf_files:
                self.logger.error(f"No PDFs found in source directory", source_dir=str(source_dir))
                return

            # Count total pages across all PDFs upfront
            self.logger.info(f"Counting pages in {len(pdf_files)} PDFs...")
            pdf_page_counts = []
            total_book_pages = 0
            for pdf_path in pdf_files:
                try:
                    # Quick page count without loading images
                    from pdf2image.pdf2image import pdfinfo_from_path
                    info = pdfinfo_from_path(pdf_path)
                    page_count = info['Pages']
                    pdf_page_counts.append(page_count)
                    total_book_pages += page_count
                except Exception as e:
                    self.logger.warning(f"Could not count pages in {pdf_path.name}", error=str(e))
                    pdf_page_counts.append(0)

            self.logger.start_stage(
                pdfs=len(pdf_files),
                total_pages=total_book_pages,
                mode="simple",
                max_workers=self.max_workers
            )

            total_pages = 0
            page_offset = 0  # Track page numbering across PDFs

            for batch_num, pdf_path in enumerate(pdf_files, 1):
                self.logger.info(f"Processing PDF: {pdf_path.name}", batch=batch_num, pdf=pdf_path.name)

                # Process PDF
                pages_processed = self.process_batch(
                    pdf_path,
                    batch_num,
                    ocr_dir,
                    images_dir,
                    page_start=page_offset + 1,
                    page_end=None,  # Will be determined during processing
                    total_book_pages=total_book_pages  # For overall progress
                )

                total_pages += pages_processed
                page_offset += pages_processed

        # Mark stage complete in checkpoint (saves pending pages + sets status)
        if self.checkpoint:
            self.checkpoint.mark_stage_complete(metadata={
                "total_pages_processed": total_pages
            })

        # Update metadata
        metadata['ocr_complete'] = True
        metadata['ocr_completion_date'] = datetime.now().isoformat()
        metadata['total_pages_processed'] = total_pages

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        self.logger.info(
            "OCR complete",
            total_pages_processed=total_pages,
            ocr_dir=str(ocr_dir),
            images_dir=str(images_dir)
        )

        # Also print for compatibility
        print(f"\n✅ OCR complete: {total_pages} pages processed")
        print(f"   Output: {ocr_dir}")
        print(f"   Images: {images_dir}")

    def process_batch(self, pdf_path, batch_num, ocr_dir, images_dir, page_start, page_end, total_book_pages=None):
        """Process a single PDF batch with layout analysis."""
        self.logger.info(f"Starting batch {batch_num}: {pdf_path.name}", batch=batch_num, pdf=pdf_path.name)

        # Write directly to ocr/ directory (flat structure)
        batch_ocr_dir = ocr_dir

        # Convert PDF to images
        try:
            images = convert_from_path(pdf_path, dpi=300)
        except Exception as e:
            self.logger.error(f"Error converting PDF", batch=batch_num, error=str(e))
            print(f"❌ Error converting PDF: {e}")

            # Mark stage as failed if this is a fatal error
            if self.checkpoint:
                self.checkpoint.mark_stage_failed(error=f"PDF conversion failed: {str(e)}")

            # Raise to propagate error (don't silently continue)
            raise RuntimeError(f"PDF conversion failed for {pdf_path}: {e}") from e

        num_pages = len(images)
        self.logger.info(
            f"Processing {num_pages} pages with layout analysis",
            batch=batch_num,
            num_pages=num_pages,
            max_workers=self.max_workers
        )

        # Prepare page tasks (filter already-completed pages if using checkpoints)
        tasks = []
        for i, image in enumerate(images, start=1):
            book_page = page_start + i - 1

            # Skip if checkpoint says page is already done
            if self.checkpoint and self.checkpoint.validate_page_output(book_page):
                continue

            tasks.append({
                'image': image,
                'page_number': book_page,
                'index': i,
                'total': num_pages,
                'batch_ocr_dir': batch_ocr_dir,
                'needs_review_dir': batch_ocr_dir / "needs_review",
                'images_dir': images_dir
            })

        # If all pages already done, skip batch
        if len(tasks) == 0:
            self.logger.info(f"Batch {batch_num} already completed, skipping", batch=batch_num)
            return num_pages

        # Process pages in parallel
        completed = 0
        errors = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_task = {
                executor.submit(self._process_single_page, task): task
                for task in tasks
            }

            # Process completions as they finish
            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    success = future.result()
                    if success:
                        completed += 1
                    else:
                        errors += 1
                except Exception as e:
                    errors += 1
                    with self.progress_lock:
                        self.logger.error(f"Page processing error", page=task['page_number'], error=str(e))

                # Progress update
                with self.progress_lock:
                    progress_count = completed + errors
                    # If we know total book pages, show overall progress
                    if total_book_pages:
                        current_page = task['page_number']
                        self.logger.progress(
                            f"Processing book",
                            current=current_page,
                            total=total_book_pages,
                            page=current_page,
                            completed=completed + (page_start - 1),
                            errors=errors
                        )
                    else:
                        # Fallback to batch progress
                        self.logger.progress(
                            f"Batch {batch_num} progress",
                            current=progress_count,
                            total=num_pages,
                            batch=batch_num,
                            completed=completed,
                            errors=errors
                        )

        self.logger.info(f"Batch {batch_num} complete", batch=batch_num, completed=completed, total=num_pages)
        print(f"   ✅ Batch {batch_num} complete: {completed}/{num_pages} pages\n")
        return completed

    def _process_single_page(self, task):
        """
        Process a single page (called by ThreadPoolExecutor).

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            page_data = self.process_page(
                task['image'],
                task['page_number'],
                task['images_dir']
            )

            # Validate against schema before saving
            try:
                validated_page = OCRPageOutput(**page_data)
                # Convert back to dict for JSON serialization
                page_data = validated_page.model_dump()
            except Exception as validation_error:
                # Save invalid output to needs_review for debugging
                needs_review_file = task['needs_review_dir'] / f"page_{task['page_number']:04d}.json"
                with open(needs_review_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'page_number': task['page_number'],
                        'validation_error': str(validation_error),
                        'raw_output': page_data
                    }, f, indent=2)

                if self.logger:
                    self.logger.error(
                        f"Schema validation failed - saved to needs_review/",
                        page=task['page_number'],
                        error=str(validation_error),
                        needs_review_file=str(needs_review_file)
                    )
                raise ValueError(f"OCR output failed schema validation: {validation_error}") from validation_error

            # Save validated JSON
            json_file = task['batch_ocr_dir'] / f"page_{task['page_number']:04d}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(page_data, f, indent=2)

            # Mark page as completed in checkpoint
            if self.checkpoint:
                self.checkpoint.mark_completed(task['page_number'])

            return True

        except Exception as e:
            if self.logger:
                self.logger.error(f"Page processing failed", page=task['page_number'], error=str(e))
            return False

    def process_page(self, pil_image, page_number, images_dir):
        """
        Process a single page - extract hierarchical text blocks and images.

        Returns:
            dict: Structured page data matching OCRPageOutput schema
        """
        width, height = pil_image.size

        # Step 1: Get TSV output from Tesseract
        tsv_output = pytesseract.image_to_data(pil_image, lang='eng', output_type=pytesseract.Output.STRING)

        # Step 2: Parse TSV into hierarchical blocks
        blocks_data = self._parse_tesseract_hierarchy(tsv_output)

        # Step 3: Detect image regions
        # Collect all paragraph bboxes for image detection
        text_boxes = []
        for block in blocks_data:
            for para in block['paragraphs']:
                text_boxes.append(para['bbox'])

        image_boxes = ImageDetector.detect_images(pil_image, text_boxes)

        # Step 4: Create image regions
        images = []
        for img_id, img_box in enumerate(image_boxes, 1):
            # Crop and save image
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

        return {
            'page_number': page_number,
            'page_dimensions': {'width': width, 'height': height},
            'ocr_timestamp': datetime.now().isoformat(),
            'blocks': blocks_data,
            'images': images
        }

    def _parse_tesseract_hierarchy(self, tsv_string):
        """
        Parse Tesseract TSV into hierarchical blocks->paragraphs structure.

        This preserves Tesseract's spatial layout analysis:
        - Blocks: isolated regions (headers/footers) or continuous regions (body)
        - Paragraphs: grouped text within blocks

        Returns:
            List of block dicts with nested paragraphs
        """
        # IMPORTANT: Use QUOTE_NONE because Tesseract TSV contains unescaped quotes
        reader = csv.DictReader(io.StringIO(tsv_string), delimiter='\t', quoting=csv.QUOTE_NONE)

        # Group by block_num -> par_num (preserving Tesseract hierarchy)
        blocks = {}

        for row in reader:
            try:
                level = int(row['level'])
                if level != 5:  # We want word level (5)
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

                # Initialize paragraph within block
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

        # Convert to list format and calculate final bboxes
        blocks_list = []

        for block_num, block in blocks.items():
            paragraphs_list = []

            for par_num, para in block['paragraphs'].items():
                if not para['words']:
                    continue

                # Calculate paragraph bbox and text
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

            # Calculate block bbox from all paragraphs
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

    def clean_stage(self, scan_id: str, confirm: bool = False):
        """
        Clean/delete all OCR outputs and checkpoint for a book.

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
        image_files = list(images_dir.glob("page_*.png")) if images_dir.exists() else []

        print(f"\n🗑️  Clean OCR stage for: {scan_id}")
        print(f"   OCR outputs: {len(ocr_files)} files")
        print(f"   Images: {len(image_files)} files")
        print(f"   Checkpoint: {'exists' if checkpoint_file.exists() else 'none'}")

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

        # Delete images
        if images_dir.exists():
            import shutil
            shutil.rmtree(images_dir)
            print(f"   ✓ Deleted {len(image_files)} image files")

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