#!/usr/bin/env python3
"""
Vision-Based OCR Correction with Block Classification

Corrects OCR errors and classifies content blocks using multimodal LLM.
"""

import json
import sys
import base64
import io
from pathlib import Path
from pdf2image import convert_from_path
from datetime import datetime
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from infra.logger import create_logger
from infra.checkpoint import CheckpointManager
from infra.llm_client import LLMClient

# Import schemas
import importlib
ocr_schemas = importlib.import_module('pipeline.1_ocr.schemas')
OCRPageOutput = ocr_schemas.OCRPageOutput

correction_schemas = importlib.import_module('pipeline.2_correction.schemas')
CorrectionPageOutput = correction_schemas.CorrectionPageOutput
BlockClassification = correction_schemas.BlockClassification
ParagraphCorrection = correction_schemas.ParagraphCorrection


class VisionCorrector:
    """
    Vision-based OCR correction and block classification.

    Uses multimodal LLM to:
    1. Correct OCR errors by comparing text against page images
    2. Classify content blocks (body, footnote, header, etc.)

    Supports checkpoint-based resume and parallel processing.
    """

    def __init__(self, storage_root=None, model="x-ai/grok-4-fast", max_workers=30, enable_checkpoints=True):
        """
        Initialize the VisionCorrector.

        Args:
            storage_root: Root directory for book storage (default: ~/Documents/book_scans)
            model: LLM model to use for correction (default: x-ai/grok-4-fast)
            max_workers: Number of parallel workers (default: 30)
            enable_checkpoints: Enable checkpoint-based resume (default: True)
        """
        self.storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
        self.model = model
        self.max_workers = max_workers
        self.progress_lock = threading.Lock()
        self.stats_lock = threading.Lock()  # Lock for thread-safe statistics updates
        self.stats = {
            "total_cost_usd": 0.0,
            "pages_processed": 0,
            "failed_pages": 0
        }
        self.logger = None  # Will be initialized per book
        self.checkpoint = None  # Will be initialized per book
        self.enable_checkpoints = enable_checkpoints
        self.llm_client = None  # Will be initialized per book

    def process_book(self, book_title, resume=False):
        """
        Process all pages for correction and classification.

        Args:
            book_title: Scan ID of the book to process
            resume: If True, resume from checkpoint (default: False)
        """
        book_dir = self.storage_root / book_title

        if not book_dir.exists():
            print(f"❌ Book directory not found: {book_dir}")
            return

        # Check for OCR outputs
        ocr_dir = book_dir / "ocr"
        if not ocr_dir.exists() or not list(ocr_dir.glob("page_*.json")):
            print(f"❌ No OCR outputs found. Run OCR stage first.")
            return

        # Load metadata
        metadata_file = book_dir / "metadata.json"
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)

        # Initialize logger
        logs_dir = book_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        self.logger = create_logger(book_title, "correction", log_dir=logs_dir)

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Initialize checkpoint manager
        if self.enable_checkpoints:
            self.checkpoint = CheckpointManager(
                scan_id=book_title,
                stage="correction",
                storage_root=self.storage_root,
                output_dir="corrected"
            )
            if not resume:
                self.checkpoint.reset()
                # Reset stats on fresh start
                with self.stats_lock:
                    self.stats = {
                        "total_cost_usd": 0.0,
                        "pages_processed": 0,
                        "failed_pages": 0
                    }
            else:
                # Load existing cost from checkpoint for resume runs
                checkpoint_state = self.checkpoint.get_status()
                existing_cost = checkpoint_state.get('metadata', {}).get('total_cost_usd', 0.0)
                with self.stats_lock:
                    self.stats['total_cost_usd'] = existing_cost

        self.logger.info(f"Processing book: {metadata.get('title', book_title)}", resume=resume, model=self.model)

        try:
            # Create output directory
            corrected_dir = book_dir / "corrected"
            corrected_dir.mkdir(exist_ok=True)

            # Get list of OCR outputs
            ocr_files = sorted(ocr_dir.glob("page_*.json"))
            total_pages = len(ocr_files)

            self.logger.start_stage(
                total_pages=total_pages,
                model=self.model,
                max_workers=self.max_workers
            )

            # Get source PDF paths
            source_dir = book_dir / "source"
            pdf_files = sorted(source_dir.glob("*.pdf"))
            if not pdf_files:
                self.logger.error("No source PDF found", source_dir=str(source_dir))
                raise FileNotFoundError(f"No PDF files found in {source_dir}")

            # Get pages to process (this sets checkpoint status to "in_progress")
            if self.checkpoint:
                pages_to_process = self.checkpoint.get_remaining_pages(
                    total_pages=total_pages,
                    resume=resume
                )
            else:
                pages_to_process = list(range(1, total_pages + 1))

            # Build tasks for remaining pages
            tasks = []
            for page_num in pages_to_process:
                ocr_file = ocr_dir / f"page_{page_num:04d}.json"
                if not ocr_file.exists():
                    continue

                tasks.append({
                    'page_num': page_num,
                    'ocr_file': ocr_file,
                    'pdf_files': pdf_files,
                    'corrected_dir': corrected_dir
                })

            if len(tasks) == 0:
                self.logger.info("All pages already corrected, skipping")
                print("✅ All pages already corrected")
                return

        # Process in parallel with thread-safe statistics
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {
                executor.submit(self._process_single_page, task): task
                for task in tasks
            }

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    success, cost = future.result()
                    with self.stats_lock:
                        if success:
                            self.stats['pages_processed'] += 1
                            self.stats['total_cost_usd'] += cost
                        else:
                            self.stats['failed_pages'] += 1
                except Exception as e:
                    with self.stats_lock:
                        self.stats['failed_pages'] += 1
                    with self.progress_lock:
                        self.logger.error(f"Page processing error", page=task['page_num'], error=str(e))

                # Progress update (read stats under lock)
                with self.stats_lock:
                    completed = self.stats['pages_processed']
                    errors = self.stats['failed_pages']
                    total_cost = self.stats['total_cost_usd']

                with self.progress_lock:
                    progress_count = completed + errors
                    self.logger.progress(
                        f"Correcting pages",
                        current=progress_count,
                        total=len(tasks),
                        completed=completed,
                        errors=errors,
                        cost=total_cost
                    )

        # Get final stats under lock
        with self.stats_lock:
            completed = self.stats['pages_processed']
            errors = self.stats['failed_pages']
            total_cost = self.stats['total_cost_usd']

        # Mark stage complete with cost in metadata
        if self.checkpoint:
            self.checkpoint.mark_stage_complete(metadata={
                "model": self.model,
                "total_cost_usd": total_cost,
                "pages_processed": completed
            })

        # Update metadata
        metadata['correction_complete'] = True
        metadata['correction_completion_date'] = datetime.now().isoformat()
        metadata['correction_total_cost'] = total_cost

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        self.logger.info(
            "Correction complete",
            pages_corrected=completed,
            total_cost=total_cost,
            avg_cost_per_page=total_cost / completed if completed > 0 else 0,
            corrected_dir=str(corrected_dir)
        )

        print(f"\n✅ Correction complete: {completed} pages")
        print(f"   Total cost: ${total_cost:.2f}")
        print(f"   Avg per page: ${total_cost/completed:.3f}" if completed > 0 else "")
        print(f"   Output: {corrected_dir}")

        # Auto-retry failed pages (xAI cache workaround)
        # If there were failures and this wasn't already a resume, automatically retry
        if errors > 0 and not resume:
            retry_count = 0
            max_auto_retries = 2

            while errors > 0 and retry_count < max_auto_retries:
                retry_count += 1

                # Wait before retrying to allow xAI cache to expire
                # Exponential backoff: 30s, 60s
                delay = 30 * retry_count
                print(f"\n⚠️  {errors} page(s) failed. Waiting {delay}s for xAI cache to clear...")
                print(f"   Then auto-retrying (attempt {retry_count}/{max_auto_retries})")

                import time
                time.sleep(delay)

                # Recursively call with resume=True to retry failed pages
                self.process_book(book_title, resume=True)

                # Check how many failures remain
                if self.checkpoint:
                    status = self.checkpoint.get_status()
                    total = status.get('total_pages', 0)
                    completed_pages = len(status.get('completed_pages', []))
                    errors = total - completed_pages

                if errors == 0:
                    print(f"\n🎉 All pages succeeded after {retry_count} auto-retry(ies)!")
                    break

            if errors > 0:
                print(f"\n⚠️  {errors} page(s) still failing after {max_auto_retries} auto-retries")
                print(f"   Run with --resume to try again, or these may be persistent xAI issues")

        except Exception as e:
            # Stage-level error handler
            self.logger.error(f"Correction stage failed", error=str(e))
            if self.checkpoint:
                self.checkpoint.mark_stage_failed(error=str(e))
            print(f"\n❌ Correction stage failed: {e}")
            raise
        finally:
            # Always clean up logger
            if self.logger:
                self.logger.close()

    def _process_single_page(self, task):
        """
        Process a single page (called by ThreadPoolExecutor).

        Returns:
            tuple: (success: bool, cost: float)
        """
        try:
            # Load OCR output
            with open(task['ocr_file'], 'r') as f:
                ocr_data = json.load(f)

            # Validate OCR input
            ocr_page = OCRPageOutput(**ocr_data)

            # Convert PDF page to image (handles multi-PDF books)
            page_image = self._get_page_image(task['pdf_files'], ocr_page.page_number)

            # Call vision model for correction and classification
            corrected_data, cost = self._correct_page_with_vision(ocr_page, page_image)

            # Validate output against schema
            try:
                validated = CorrectionPageOutput(**corrected_data)
                corrected_data = validated.model_dump()
            except Exception as validation_error:
                self.logger.error(
                    f"Schema validation failed",
                    page=task['page_num'],
                    error=str(validation_error)
                )
                raise ValueError(f"Correction output failed schema validation: {validation_error}") from validation_error

            # Save corrected output
            output_file = task['corrected_dir'] / f"page_{task['page_num']:04d}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(corrected_data, f, indent=2)

            # Mark complete in checkpoint with cost
            if self.checkpoint:
                self.checkpoint.mark_completed(task['page_num'], cost_usd=cost)

            return True, cost

        except Exception as e:
            if self.logger:
                self.logger.error(f"Page correction failed", page=task['page_num'], error=str(e))
            return False, 0.0

    def _pdf_page_to_image(self, pdf_path, page_number, dpi=150):
        """
        Convert a specific PDF page to PIL Image.

        Args:
            pdf_path: Path to PDF file
            page_number: Page number (1-indexed)
            dpi: Resolution for conversion (default 150 for reasonable file size)

        Returns:
            PIL.Image: Page image (resized if too large)
        """
        # pdf2image uses 1-indexed page numbers
        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            first_page=page_number,
            last_page=page_number
        )

        image = images[0]

        # Resize if image is too large (OpenAI has limits on image size)
        # Max dimension should be around 2000px for reasonable processing
        max_dimension = 2000
        width, height = image.size

        if width > max_dimension or height > max_dimension:
            # Calculate scaling factor
            scale = max_dimension / max(width, height)
            new_width = int(width * scale)
            new_height = int(height * scale)

            # Resize using high-quality resampling
            from PIL import Image as PILImage
            image = image.resize((new_width, new_height), PILImage.Resampling.LANCZOS)

        return image

    def _image_to_base64(self, pil_image):
        """Convert PIL Image to base64 string for vision API."""
        buffered = io.BytesIO()
        pil_image.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
        return base64.b64encode(img_bytes).decode('utf-8')

    def _correct_page_with_vision(self, ocr_page, page_image):
        """
        Correct OCR errors and classify blocks using vision model.

        Args:
            ocr_page: OCRPageOutput object
            page_image: PIL Image of the page

        Returns:
            tuple: (correction_data: dict, cost: float)
        """
        # Build OCR text representation for the prompt
        ocr_text = self._format_ocr_for_prompt(ocr_page)

        # Build the vision prompt
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(ocr_page, ocr_text)

        # Generate simplified JSON Schema for structured outputs
        # OpenRouter's strict mode requires basic JSON Schema (no refs, no complex nesting)
        response_schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "ocr_correction",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "blocks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "block_num": {"type": "integer"},
                                    "classification": {"type": "string"},
                                    "classification_confidence": {"type": "number"},
                                    "paragraphs": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "par_num": {"type": "integer"},
                                                "text": {"type": ["string", "null"]},
                                                "notes": {"type": ["string", "null"]},
                                                "confidence": {"type": "number"}
                                            },
                                            "required": ["par_num", "text", "notes", "confidence"],
                                            "additionalProperties": False
                                        }
                                    }
                                },
                                "required": ["block_num", "classification", "classification_confidence", "paragraphs"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["blocks"],
                    "additionalProperties": False
                }
            }
        }

        # Call vision model with automatic JSON retry on parse failures
        def parse_correction_json(response_text):
            """Parse and validate correction JSON."""
            data = json.loads(response_text)  # Will raise JSONDecodeError if invalid
            return data

        correction_data, usage, cost = self.llm_client.call_with_json_retry(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            json_parser=parse_correction_json,
            temperature=0.1,
            max_retries=2,  # Retry up to 2 times on JSON parse failures (3 total attempts)
            images=[page_image],
            timeout=180,
            response_format=response_schema  # ✓ Structured outputs enabled
        )

        # Add metadata
        correction_data['page_number'] = ocr_page.page_number
        correction_data['model_used'] = self.model
        correction_data['processing_cost'] = cost
        correction_data['timestamp'] = datetime.now().isoformat()

        # Calculate summary stats
        total_corrections = sum(
            1 for block in correction_data['blocks']
            for p in block.get('paragraphs', [])
            if p.get('text') is not None
        )

        avg_class_conf = sum(b.get('classification_confidence', 0) for b in correction_data['blocks']) / len(correction_data['blocks']) if correction_data['blocks'] else 0
        avg_conf = sum(
            p.get('confidence', 1.0)
            for b in correction_data['blocks']
            for p in b.get('paragraphs', [])
        ) / sum(len(b.get('paragraphs', [])) for b in correction_data['blocks']) if correction_data['blocks'] else 1.0

        correction_data['total_blocks'] = len(correction_data['blocks'])
        correction_data['total_corrections'] = total_corrections
        correction_data['avg_classification_confidence'] = round(avg_class_conf, 3)
        correction_data['avg_confidence'] = round(avg_conf, 3)

        return correction_data, cost

    def _build_system_prompt(self):
        """Build the system prompt for vision correction."""
        return """You are an expert OCR correction assistant with vision capabilities.

Your task is to:
1. **Classify content blocks** - Identify what type of content each block contains
2. **Correct OCR errors** - Fix any OCR mistakes by comparing the text to the actual page image

For each block, provide:
- A classification from the allowed types with confidence score (0.0-1.0)
- For each paragraph: ONLY if corrections needed, output the FULL corrected paragraph text

**Block Types:**
TITLE_PAGE, COPYRIGHT, DEDICATION, TABLE_OF_CONTENTS, PREFACE, FOREWORD, INTRODUCTION,
CHAPTER_HEADING, SECTION_HEADING, BODY, QUOTE, EPIGRAPH,
FOOTNOTE, ENDNOTES, BIBLIOGRAPHY, REFERENCES, INDEX,
APPENDIX, GLOSSARY, ACKNOWLEDGMENTS,
HEADER, FOOTER, PAGE_NUMBER,
ILLUSTRATION_CAPTION, TABLE, OTHER

**Correction Guidelines:**
- Use the page image to verify text accuracy - you can see formatting, layout, and actual characters
- ONLY include `text` field if you found actual errors (set to null otherwise)
- When you DO correct: output the COMPLETE corrected paragraph text (not deltas/patches)
- Add brief `notes` explaining what you fixed (e.g., "Fixed 3 OCR errors, removed hyphenation")
- Common OCR errors: character substitution (rn→m, cl→d, tbe→the), spacing issues, hyphenation
- Confidence scores: 0.0-1.0 (be honest about uncertainty)"""

    def _build_user_prompt(self, ocr_page, ocr_text):
        """Build the user prompt with OCR data."""
        return f"""Here is the OCR output for page {ocr_page.page_number}:

{ocr_text}

Please:
1. Classify each block by its content type (using the types listed above)
2. Compare the OCR text to the page image and identify any errors
3. For each paragraph with errors: output the FULL corrected paragraph text in `text` field (null if clean)
4. Add brief `notes` explaining changes (e.g., "Fixed 'tlie' → 'the', removed hyphen at line break")
5. Provide confidence scores for both classification and text quality

Focus on accuracy - only output corrected text if you're confident there's an error."""

    def _format_ocr_for_prompt(self, ocr_page):
        """Format OCR page data for the vision prompt."""
        lines = []
        # Convert to dict to access fields
        page_dict = ocr_page.model_dump()
        for block in page_dict['blocks']:
            lines.append(f"\n--- Block {block['block_num']} ---")
            for para in block['paragraphs']:
                lines.append(f"  Paragraph {para['par_num']}: {para['text']}")
        return '\n'.join(lines)

    def _get_page_image(self, pdf_files, page_number, dpi=150):
        """
        Get page image from multi-PDF book by calculating which PDF contains the page.

        Args:
            pdf_files: Sorted list of PDF file paths
            page_number: Global page number (1-indexed, continuous across PDFs)
            dpi: Resolution for conversion

        Returns:
            PIL.Image: Page image
        """
        from pdf2image.pdf2image import pdfinfo_from_path

        # Find which PDF contains this page
        page_offset = 0
        for pdf_path in pdf_files:
            info = pdfinfo_from_path(pdf_path)
            page_count = info['Pages']

            # Check if page is in this PDF
            if page_number <= page_offset + page_count:
                # Calculate local page number within this PDF
                local_page = page_number - page_offset
                return self._pdf_page_to_image(pdf_path, local_page, dpi=dpi)

            page_offset += page_count

        raise ValueError(f"Page {page_number} not found in any PDF (total pages: {page_offset})")

    def clean_stage(self, scan_id: str, confirm: bool = False):
        """
        Clean/delete all correction outputs and checkpoint for a book.

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

        corrected_dir = book_dir / "corrected"
        checkpoint_file = book_dir / "checkpoints" / "correction.json"
        metadata_file = book_dir / "metadata.json"

        # Count what will be deleted
        corrected_files = list(corrected_dir.glob("*.json")) if corrected_dir.exists() else []

        print(f"\n🗑️  Clean Correction stage for: {scan_id}")
        print(f"   Corrected outputs: {len(corrected_files)} files")
        print(f"   Checkpoint: {'exists' if checkpoint_file.exists() else 'none'}")

        if not confirm:
            response = input("\n   Proceed? (yes/no): ").strip().lower()
            if response != 'yes':
                print("   Cancelled.")
                return False

        # Delete corrected outputs
        if corrected_dir.exists():
            import shutil
            shutil.rmtree(corrected_dir)
            print(f"   ✓ Deleted {len(corrected_files)} corrected files")

        # Reset checkpoint
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            print(f"   ✓ Deleted checkpoint")

        # Update metadata
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            metadata['correction_complete'] = False
            metadata.pop('correction_completion_date', None)
            metadata.pop('correction_total_cost', None)

            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            print(f"   ✓ Reset metadata")

        print(f"\n✅ Correction stage cleaned for {scan_id}")
        return True
