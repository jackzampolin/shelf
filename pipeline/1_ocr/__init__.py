#!/usr/bin/env python3
"""
Book OCR Processor - Enhanced with Layout Analysis
Extracts structured text with images, captions, headers, and footers
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


class BlockClassifier:
    """Classifies text blocks by type based on position and content."""

    @staticmethod
    def classify(bbox, text, page_width, page_height):
        """
        Classify a text block as header, footer, caption, or body.

        Args:
            bbox: (x, y, width, height) bounding box
            text: The text content
            page_width, page_height: Page dimensions

        Returns:
            str: Block type ('header', 'footer', 'caption', 'body')
        """
        x, y, w, h = bbox

        # Header: top 8% of page
        if y < page_height * 0.08:
            return "header"

        # Footer: bottom 5% of page
        if y + h > page_height * 0.95:
            return "footer"

        # Caption heuristics:
        # - ALL CAPS (common for photo credits)
        # - Contains certain keywords
        # - Very short text
        text_upper = text.strip()
        if text_upper.isupper() and len(text_upper) > 5:
            caption_keywords = ['LIBRARY', 'MUSEUM', 'ARCHIVES', 'COLLECTION', 'GETTY', 'PHOTO']
            if any(kw in text_upper for kw in caption_keywords):
                return "caption"

        # Default: body text
        return "body"


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


class LayoutAnalyzer:
    """Analyzes page layout and associates captions with images."""

    @staticmethod
    def associate_captions(caption_blocks, image_blocks, proximity=100):
        """
        Associate caption blocks with nearby image blocks.

        Args:
            caption_blocks: List of caption block dicts with 'bbox'
            image_blocks: List of image block dicts with 'bbox'
            proximity: Maximum distance in pixels to associate

        Returns:
            Dict mapping caption IDs to image IDs
        """
        associations = {}

        for caption in caption_blocks:
            cx, cy, cw, ch = caption['bbox']
            caption_center_y = cy + ch / 2

            closest_image = None
            closest_dist = float('inf')

            for image in image_blocks:
                ix, iy, iw, ih = image['bbox']

                # Check if caption is above or below image
                if cy + ch < iy:  # Caption above image
                    dist = iy - (cy + ch)
                elif cy > iy + ih:  # Caption below image
                    dist = cy - (iy + ih)
                else:  # Overlapping vertically (side by side - unlikely for captions)
                    continue

                if dist < proximity and dist < closest_dist:
                    closest_dist = dist
                    closest_image = image

            if closest_image:
                associations[caption['id']] = closest_image['id']

        return associations


class BookOCRProcessor:
    """Enhanced OCR processor with layout analysis."""

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

            self.logger.start_stage(
                pdfs=len(pdf_files),
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
                    page_end=None  # Will be determined during processing
                )

                total_pages += pages_processed
                page_offset += pages_processed

        # Mark stage complete in checkpoint (saves pending pages + sets status)
        if self.checkpoint:
            self.checkpoint.mark_stage_complete(metadata={
                "total_pages_processed": total_pages,
                "ocr_mode": "structured"
            })

        # Update metadata
        metadata['ocr_complete'] = True
        metadata['ocr_completion_date'] = datetime.now().isoformat()
        metadata['total_pages_processed'] = total_pages
        metadata['ocr_mode'] = 'structured'

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

    def process_batch(self, pdf_path, batch_num, ocr_dir, images_dir, page_start, page_end):
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

            # Save structured JSON
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
        Process a single page with full layout analysis.

        Returns:
            dict: Structured page data with regions
        """
        width, height = pil_image.size

        # Step 1: Get TSV output from Tesseract
        tsv_output = pytesseract.image_to_data(pil_image, lang='eng', output_type=pytesseract.Output.STRING)

        # Step 2: Parse TSV into text blocks
        text_blocks = self._parse_tsv(tsv_output, width, height)

        # Step 3: Detect image regions
        text_boxes = [b['bbox'] for b in text_blocks]
        image_boxes = ImageDetector.detect_images(pil_image, text_boxes)

        # Step 4: Create region list
        regions = []
        next_id = 1

        # Add text blocks
        for block in text_blocks:
            regions.append({
                'id': next_id,
                'type': block['type'],
                'bbox': block['bbox'],
                'text': block['text'],
                'confidence': block['confidence'],
                'reading_order': next_id
            })
            next_id += 1

        # Add image blocks
        for img_box in image_boxes:
            # Crop and save image
            x, y, w, h = img_box
            cropped = pil_image.crop((x, y, x + w, y + h))
            img_filename = f"page_{page_number:04d}_img_{next_id:03d}.png"
            img_path = images_dir / img_filename
            cropped.save(img_path)

            regions.append({
                'id': next_id,
                'type': 'image',
                'bbox': list(img_box),
                'image_file': img_filename,
                'reading_order': next_id
            })
            next_id += 1

        # Step 5: Associate captions with images
        caption_blocks = [r for r in regions if r['type'] == 'caption']
        image_blocks = [r for r in regions if r['type'] == 'image']
        associations = LayoutAnalyzer.associate_captions(caption_blocks, image_blocks)

        # Add associations to caption blocks
        for region in regions:
            if region['type'] == 'caption' and region['id'] in associations:
                region['associated_image'] = associations[region['id']]

        # Step 6: Sort by reading order (top to bottom, left to right)
        regions.sort(key=lambda r: (r['bbox'][1], r['bbox'][0]))
        for i, region in enumerate(regions, 1):
            region['reading_order'] = i

        return {
            'page_number': page_number,
            'page_dimensions': {'width': width, 'height': height},
            'ocr_timestamp': datetime.now().isoformat(),
            'ocr_mode': 'structured',
            'regions': regions
        }

    def _parse_tsv(self, tsv_string, page_width, page_height):
        """
        Parse Tesseract TSV output into text blocks.

        Returns:
            List of dicts with 'bbox', 'text', 'confidence', 'type'
        """
        # IMPORTANT: Use QUOTE_NONE because Tesseract TSV contains unescaped quotes
        # which cause csv.DictReader to incorrectly parse multi-line quoted fields
        reader = csv.DictReader(io.StringIO(tsv_string), delimiter='\t', quoting=csv.QUOTE_NONE)

        # Group by paragraph
        paragraphs = {}
        for row in reader:
            try:
                level = int(row['level'])
                if level != 5:  # We want word level (5)
                    continue

                par_num = int(row['par_num'])
                conf = float(row['conf'])  # Fixed: conf is a float, not int
                text = row['text'].strip()

                if conf < 0 or not text:
                    continue

                left = int(row['left'])
                top = int(row['top'])
                width = int(row['width'])
                height = int(row['height'])

                if par_num not in paragraphs:
                    paragraphs[par_num] = {
                        'words': [],
                        'min_x': left,
                        'min_y': top,
                        'max_x': left + width,
                        'max_y': top + height,
                        'confidences': []
                    }

                para = paragraphs[par_num]
                para['words'].append(text)
                para['confidences'].append(conf)
                para['min_x'] = min(para['min_x'], left)
                para['min_y'] = min(para['min_y'], top)
                para['max_x'] = max(para['max_x'], left + width)
                para['max_y'] = max(para['max_y'], top + height)

            except (ValueError, KeyError):
                continue

        # Convert paragraphs to blocks
        blocks = []
        for par_num, para in paragraphs.items():
            text = ' '.join(para['words'])
            bbox = [
                para['min_x'],
                para['min_y'],
                para['max_x'] - para['min_x'],
                para['max_y'] - para['min_y']
            ]
            confidence = sum(para['confidences']) / len(para['confidences']) / 100.0

            block_type = BlockClassifier.classify(bbox, text, page_width, page_height)

            blocks.append({
                'bbox': bbox,
                'text': text,
                'confidence': round(confidence, 3),
                'type': block_type
            })

        return blocks

    def list_books(self):
        """List all books available for OCR processing."""
        books = []
        for book_dir in self.storage_root.iterdir():
            if book_dir.is_dir():
                metadata_file = book_dir / "metadata.json"
                if metadata_file.exists():
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                        books.append(metadata)

        print("\n📚 Books available for OCR:")
        for book in books:
            ocr_status = "✅ Complete" if book.get('ocr_complete') else "⏳ Pending"
            ocr_mode = book.get('ocr_mode', 'plain')
            print(f"{ocr_status} {book['title']} (mode: {ocr_mode})")
            print(f"         {len(book['batches'])} batches, ~{book['total_pages']} pages")
            if book.get('ocr_complete'):
                print(f"         Processed: {book.get('total_pages_processed', 0)} pages")
            print()

        return books


def interactive_mode():
    """Simple CLI for OCR processing."""
    processor = BookOCRProcessor()

    print("🔍 Book OCR Processor (Enhanced)")
    print("-" * 40)

    while True:
        print("\nCommands:")
        print("  1. List books")
        print("  2. Process a book")
        print("  3. Exit")

        choice = input("\nChoice: ").strip()

        if choice == "1":
            processor.list_books()

        elif choice == "2":
            books = processor.list_books()
            book_title = input("\nEnter book safe title (e.g., 'The-Accidental-President'): ").strip()

            if book_title:
                processor.process_book(book_title)
            else:
                print("❌ No book title provided")

        elif choice == "3":
            break

        else:
            print("Invalid choice")

    print("\n👋 Done!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Command-line mode
        processor = BookOCRProcessor()
        processor.process_book(sys.argv[1])
    else:
        # Interactive mode
        interactive_mode()