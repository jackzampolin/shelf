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
    """Vision-based OCR correction and block classification."""

    def __init__(self, storage_root=None, model="openai/gpt-4o", max_workers=10, enable_checkpoints=True):
        self.storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
        self.model = model
        self.max_workers = max_workers
        self.progress_lock = threading.Lock()
        self.logger = None  # Will be initialized per book
        self.checkpoint = None  # Will be initialized per book
        self.enable_checkpoints = enable_checkpoints
        self.llm_client = None  # Will be initialized per book

    def process_book(self, book_title, resume=False):
        """Process all pages for correction and classification."""
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
        self.llm_client = LLMClient(logger=self.logger)

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

        self.logger.info(f"Processing book: {metadata.get('title', book_title)}", resume=resume, model=self.model)

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

        # Get source PDF path
        source_dir = book_dir / "source"
        pdf_files = sorted(source_dir.glob("*.pdf"))
        if not pdf_files:
            self.logger.error("No source PDF found", source_dir=str(source_dir))
            return

        # For simplicity, assume single PDF (can extend later for multi-PDF books)
        pdf_path = pdf_files[0]

        # Process pages in parallel
        tasks = []
        for ocr_file in ocr_files:
            page_num = int(ocr_file.stem.split('_')[1])

            # Skip if checkpoint says already done
            if self.checkpoint and self.checkpoint.validate_page_output(page_num):
                continue

            tasks.append({
                'page_num': page_num,
                'ocr_file': ocr_file,
                'pdf_path': pdf_path,
                'corrected_dir': corrected_dir
            })

        if len(tasks) == 0:
            self.logger.info("All pages already corrected, skipping")
            print("✅ All pages already corrected")
            return

        # Process in parallel
        completed = 0
        errors = 0
        total_cost = 0.0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {
                executor.submit(self._process_single_page, task): task
                for task in tasks
            }

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    success, cost = future.result()
                    if success:
                        completed += 1
                        total_cost += cost
                    else:
                        errors += 1
                except Exception as e:
                    errors += 1
                    with self.progress_lock:
                        self.logger.error(f"Page processing error", page=task['page_num'], error=str(e))

                # Progress update
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

        # Mark stage complete
        if self.checkpoint:
            self.checkpoint.mark_stage_complete(metadata={
                "total_pages_corrected": completed,
                "total_cost": total_cost
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

            # Convert PDF page to image
            page_image = self._pdf_page_to_image(task['pdf_path'], ocr_page.page_number)

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

            # Mark complete in checkpoint
            if self.checkpoint:
                self.checkpoint.mark_completed(task['page_num'])

            return True, cost

        except Exception as e:
            if self.logger:
                self.logger.error(f"Page correction failed", page=task['page_num'], error=str(e))
            return False, 0.0

    def _pdf_page_to_image(self, pdf_path, page_number, dpi=300):
        """
        Convert a specific PDF page to PIL Image.

        Args:
            pdf_path: Path to PDF file
            page_number: Page number (1-indexed)
            dpi: Resolution for conversion

        Returns:
            PIL.Image: Page image
        """
        # pdf2image uses 1-indexed page numbers
        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            first_page=page_number,
            last_page=page_number
        )
        return images[0]

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

        # Generate JSON Schema from Pydantic model for structured outputs
        # We need to create a schema for just the blocks array since that's what the LLM returns
        from pipeline.2_correction.schemas import BlockClassification

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
                            "items": BlockClassification.model_json_schema()
                        }
                    },
                    "required": ["blocks"],
                    "additionalProperties": False
                }
            }
        }

        # Call vision model with structured output
        response, usage, cost = self.llm_client.call(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            images=[page_image],
            temperature=0.1,
            timeout=180,
            response_format=response_schema
        )

        # Response is guaranteed to be valid JSON with structured outputs
        correction_data = json.loads(response)

        # Add metadata
        correction_data['page_number'] = ocr_page.page_number
        correction_data['model_used'] = self.model
        correction_data['processing_cost'] = cost
        correction_data['timestamp'] = datetime.now().isoformat()

        # Calculate summary stats
        total_corrections = sum(
            len(block.get('paragraphs', []))
            for block in correction_data['blocks']
            if any(p.get('corrected_text') for p in block.get('paragraphs', []))
        )

        avg_class_conf = sum(b.get('classification_confidence', 0) for b in correction_data['blocks']) / len(correction_data['blocks']) if correction_data['blocks'] else 0
        avg_corr_conf = sum(
            p.get('correction_confidence', 1.0)
            for b in correction_data['blocks']
            for p in b.get('paragraphs', [])
        ) / sum(len(b.get('paragraphs', [])) for b in correction_data['blocks']) if correction_data['blocks'] else 1.0

        correction_data['total_blocks'] = len(correction_data['blocks'])
        correction_data['total_corrections'] = total_corrections
        correction_data['avg_classification_confidence'] = round(avg_class_conf, 3)
        correction_data['avg_correction_confidence'] = round(avg_corr_conf, 3)

        return correction_data, cost

    def _build_system_prompt(self):
        """Build the system prompt for vision correction."""
        return """You are an expert OCR correction assistant with vision capabilities.

Your task is to:
1. **Classify content blocks** - Identify what type of content each block contains
2. **Correct OCR errors** - Fix any OCR mistakes by comparing the text to the actual page image

For each block, provide:
- A classification from the allowed types with confidence score (0.0-1.0)
- Corrections for each paragraph (ONLY if errors are found)

**Block Types:**
TITLE_PAGE, COPYRIGHT, DEDICATION, TABLE_OF_CONTENTS, PREFACE, FOREWORD, INTRODUCTION,
CHAPTER_HEADING, SECTION_HEADING, BODY, QUOTE, EPIGRAPH,
FOOTNOTE, ENDNOTES, BIBLIOGRAPHY, REFERENCES, INDEX,
APPENDIX, GLOSSARY, ACKNOWLEDGMENTS,
HEADER, FOOTER, PAGE_NUMBER,
ILLUSTRATION_CAPTION, TABLE, OTHER

**Correction Guidelines:**
- Use the page image to verify text accuracy - you can see formatting, layout, and actual characters
- ONLY include `corrected_text` if you found actual errors (set to null otherwise)
- Common OCR errors: character substitution (rn→m, cl→d, tbe→the), spacing issues, hyphenation
- Confidence scores: 0.0-1.0 (be honest about uncertainty)"""

    def _build_user_prompt(self, ocr_page, ocr_text):
        """Build the user prompt with OCR data."""
        return f"""Here is the OCR output for page {ocr_page.page_number}:

{ocr_text}

Please:
1. Classify each block by its content type (using the types listed above)
2. Compare the OCR text to the page image and identify any errors
3. For each paragraph, provide corrected_text ONLY if you find errors (otherwise set to null)
4. Provide confidence scores for both classification and corrections

Focus on accuracy - only mark text as corrected if you're confident there's an error."""

    def _format_ocr_for_prompt(self, ocr_page):
        """Format OCR page data for the vision prompt."""
        lines = []
        for block in ocr_page.blocks:
            lines.append(f"\n--- Block {block['block_num']} ---")
            for para in block['paragraphs']:
                lines.append(f"  Paragraph {para['par_num']}: {para['text']}")
        return '\n'.join(lines)

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
