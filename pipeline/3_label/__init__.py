#!/usr/bin/env python3
"""
Vision-Based Page Labeling

Extracts page numbers and classifies content blocks using multimodal LLM.
Text correction is handled in Stage 2 (Correct).
"""

import json
import sys
import base64
import io
from pathlib import Path
from datetime import datetime
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from infra.config import Config
from infra.logger import create_logger
from infra.checkpoint import CheckpointManager
from infra.llm_client import LLMClient
from infra.pdf_utils import downsample_for_vision
from infra.progress import ProgressBar

# Import schemas
import importlib
ocr_schemas = importlib.import_module('pipeline.1_ocr.schemas')
OCRPageOutput = ocr_schemas.OCRPageOutput

label_schemas = importlib.import_module('pipeline.3_label.schemas')
LabelPageOutput = label_schemas.LabelPageOutput
BlockClassification = label_schemas.BlockClassification
ParagraphLabel = label_schemas.ParagraphLabel


class VisionLabeler:
    """
    Vision-based page number extraction and block classification.

    Uses multimodal LLM to:
    1. Extract printed page numbers from headers/footers
    2. Classify content blocks (body, footnote, header, etc.)

    Text correction is handled in Stage 2 (Correct).
    Supports checkpoint-based resume and parallel processing.
    """

    def __init__(self, storage_root=None, model=None, max_workers=30, enable_checkpoints=True, max_retries=3):
        """
        Initialize the VisionLabeler.

        Args:
            storage_root: Root directory for book storage (default: ~/Documents/book_scans)
            model: LLM model to use for labeling (default: from Config.VISION_MODEL env var)
            max_workers: Number of parallel workers (default: 30)
            enable_checkpoints: Enable checkpoint-based resume (default: True)
            max_retries: Maximum retry attempts for failed pages (default: 3, use 1 for no retries)
        """
        self.storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
        self.model = model or Config.VISION_MODEL
        self.max_workers = max_workers
        self.max_retries = max_retries
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
        Process all pages for page number extraction and block classification.

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

        # Initialize logger (file only, no console spam)
        logs_dir = book_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        self.logger = create_logger(book_title, "label", log_dir=logs_dir, console_output=False)

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Initialize checkpoint manager
        if self.enable_checkpoints:
            # Migrate old "labels" checkpoint to "label" (temporary migration code)
            checkpoint_dir = book_dir / "checkpoints"
            old_checkpoint = checkpoint_dir / "labels.json"
            new_checkpoint = checkpoint_dir / "label.json"
            if old_checkpoint.exists() and not new_checkpoint.exists():
                import shutil
                shutil.move(str(old_checkpoint), str(new_checkpoint))
                print(f"   Migrated checkpoint: labels.json → label.json")

            self.checkpoint = CheckpointManager(
                scan_id=book_title,
                stage="label",
                storage_root=self.storage_root,
                output_dir="labels"
            )
            if not resume:
                # Check if checkpoint exists with progress before resetting
                if self.checkpoint.checkpoint_file.exists():
                    status = self.checkpoint.get_status()
                    completed = len(status.get('completed_pages', []))
                    total = status.get('total_pages', 0)
                    cost = status.get('metadata', {}).get('total_cost_usd', 0.0)

                    if completed > 0:
                        print(f"\n⚠️  Checkpoint exists with progress:")
                        print(f"   Pages: {completed}/{total} complete ({completed/total*100:.1f}%)" if total > 0 else f"   Pages: {completed} complete")
                        print(f"   Cost: ${cost:.2f}")
                        print(f"   This will DELETE progress and start over.")

                        response = input("\n   Continue with reset? (type 'yes' to confirm): ").strip().lower()
                        if response != 'yes':
                            print("   Cancelled. Use --resume to continue from checkpoint.")
                            return

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
            labels_dir = book_dir / "labels"
            labels_dir.mkdir(exist_ok=True)

            # Get list of OCR outputs
            ocr_files = sorted(ocr_dir.glob("page_*.json"))
            total_pages = len(ocr_files)

            self.logger.start_stage(
                total_pages=total_pages,
                model=self.model,
                max_workers=self.max_workers
            )

            # Stage entry
            print(f"\n🏷️  Label Stage ({book_title})")
            print(f"   Pages:     {total_pages}")
            print(f"   Workers:   {self.max_workers}")
            print(f"   Model:     {self.model}")

            # Get source page images (extracted during 'ar library add')
            source_dir = book_dir / "source"
            if not source_dir.exists():
                self.logger.error("Source directory not found", source_dir=str(source_dir))
                raise FileNotFoundError(f"Source directory not found: {source_dir}")

            page_files = sorted(source_dir.glob("page_*.png"))
            if not page_files:
                self.logger.error("No page images found", source_dir=str(source_dir))
                raise FileNotFoundError(f"No page images found in {source_dir}. Run 'ar library add' to extract pages first.")

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
                page_file = source_dir / f"page_{page_num:04d}.png"

                if not ocr_file.exists() or not page_file.exists():
                    continue

                tasks.append({
                    'page_num': page_num,
                    'ocr_file': ocr_file,
                    'page_file': page_file,
                    'labels_dir': labels_dir,
                    'total_pages': total_pages  # For region classification context
                })

            if len(tasks) == 0:
                self.logger.info("All pages already labeled, skipping")
                print("✅ All pages already labeled")
                return

            # Process with single-pass retry logic
            # Progress bar tracks total pages (not iterations)
            print(f"\n   Labeling {len(tasks)} pages...")
            progress = ProgressBar(
                total=len(tasks),
                prefix="   ",
                width=40,
                unit="pages"
            )

            # Single-pass retry: Process → Accumulate failures → Retry failed batch
            retry_count = 0
            pending_tasks = tasks.copy()
            completed = 0

            while pending_tasks and retry_count < self.max_retries:
                # Track failures for this pass
                failed_tasks = []

                # Process current batch in parallel
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_task = {
                        executor.submit(self._process_single_page, task): task
                        for task in pending_tasks
                    }

                    for future in as_completed(future_to_task):
                        task = future_to_task[future]
                        try:
                            success, cost = future.result()
                            if success:
                                # Success: increment progress, update stats
                                with self.stats_lock:
                                    self.stats['pages_processed'] += 1
                                    self.stats['total_cost_usd'] += cost
                                completed += 1

                                # Update progress bar (only on success)
                                with self.stats_lock:
                                    total_cost = self.stats['total_cost_usd']

                                # Suffix: Just cost, with attempt indicator if retrying
                                suffix = f"${total_cost:.2f}"
                                if retry_count > 0:
                                    suffix += f" (attempt {retry_count + 1}/{self.max_retries})"

                                progress.update(completed, suffix=suffix)
                            else:
                                # Failure: accumulate for retry
                                failed_tasks.append(task)
                        except Exception as e:
                            # Exception: accumulate for retry
                            failed_tasks.append(task)
                            self.logger.error(f"Page processing exception", page=task['page_num'], error=str(e))

                # After pass completes, check for failures
                if failed_tasks:
                    retry_count += 1
                    if retry_count < self.max_retries:
                        # Retry failed batch after delay
                        import time
                        delay = min(30, 10 * retry_count)  # 10s, 20s, 30s
                        print(f"\n   ⚠️  {len(failed_tasks)} page(s) failed, retrying after {delay}s (attempt {retry_count + 1}/{self.max_retries})...")
                        time.sleep(delay)
                        pending_tasks = failed_tasks
                    else:
                        # Max retries reached
                        print(f"\n   ⚠️  {len(failed_tasks)} page(s) failed after {self.max_retries} attempts")
                        break
                else:
                    # All succeeded
                    break

            # Finish progress bar
            errors = len(pending_tasks) if retry_count >= self.max_retries else 0
            progress.finish(f"   ✓ {completed}/{len(tasks)} pages labeled")
            if errors > 0:
                failed_pages = sorted([t['page_num'] for t in pending_tasks])
                print(f"   ⚠️  {errors} pages failed: {failed_pages[:10]}" + (f" and {len(failed_pages)-10} more" if len(failed_pages) > 10 else ""))

            # Get final stats under lock
            with self.stats_lock:
                completed = self.stats['pages_processed']
                total_cost = self.stats['total_cost_usd']

            # Only mark stage complete if ALL pages succeeded
            if errors == 0:
                # Mark stage complete with cost in metadata
                if self.checkpoint:
                    self.checkpoint.mark_stage_complete(metadata={
                        "model": self.model,
                        "total_cost_usd": total_cost,
                        "pages_processed": completed
                    })

                # Update metadata
                metadata['labels_complete'] = True
                metadata['labels_completion_date'] = datetime.now().isoformat()
                metadata['labels_total_cost'] = total_cost

                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)

                # Log completion to file (not stdout)
                self.logger.info(
                    "Labeling complete",
                    pages_labeled=completed,
                    total_cost=total_cost,
                    avg_cost_per_page=total_cost / completed if completed > 0 else 0,
                    labels_dir=str(labels_dir)
                )

                # Print stage exit (success)
                print(f"\n✅ Label complete: {completed}/{total_pages} pages")
                print(f"   Total cost: ${total_cost:.2f}")
                print(f"   Avg per page: ${total_cost/completed:.3f}" if completed > 0 else "")
            else:
                # Stage incomplete - some pages failed
                failed_pages = sorted([t['page_num'] for t in pending_tasks])
                print(f"\n⚠️  Label incomplete: {completed}/{total_pages} pages succeeded")
                print(f"   Total cost: ${total_cost:.2f}")
                print(f"   Failed pages: {failed_pages}")
                print(f"\n   To retry failed pages:")
                print(f"   uv run python ar.py process label {book_title} --resume")

        except Exception as e:
            # Stage-level error handler
            self.logger.error(f"Labeling stage failed", error=str(e))
            if self.checkpoint:
                self.checkpoint.mark_stage_failed(error=str(e))
            print(f"\n❌ Labeling stage failed: {e}")
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

            # Load page image from source directory (600 DPI)
            page_image = Image.open(task['page_file'])

            # Downsample to 300 DPI for vision model (reduces token cost)
            page_image = downsample_for_vision(page_image)

            # Call vision model for page number extraction and classification
            label_data, cost = self._label_page_with_vision(ocr_page, page_image, task['total_pages'])

            # Validate output against schema
            try:
                validated = LabelPageOutput(**label_data)
                label_data = validated.model_dump()
            except Exception as validation_error:
                self.logger.error(
                    f"Schema validation failed",
                    page=task['page_num'],
                    error=str(validation_error)
                )
                raise ValueError(f"Label output failed schema validation: {validation_error}") from validation_error

            # Save label output
            output_file = task['labels_dir'] / f"page_{task['page_num']:04d}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(label_data, f, indent=2)

            # Mark complete in checkpoint with cost
            if self.checkpoint:
                self.checkpoint.mark_completed(task['page_num'], cost_usd=cost)

            return True, cost

        except Exception as e:
            if self.logger:
                self.logger.error(f"Page labeling failed", page=task['page_num'], error=str(e))
            return False, 0.0

    def _image_to_base64(self, pil_image):
        """Convert PIL Image to base64 string for vision API."""
        buffered = io.BytesIO()
        pil_image.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
        return base64.b64encode(img_bytes).decode('utf-8')

    def _label_page_with_vision(self, ocr_page, page_image, total_pages):
        """
        Extract page numbers, classify page region, and classify blocks using vision model.

        Args:
            ocr_page: OCRPageOutput object
            page_image: PIL Image of the page
            total_pages: Total pages in book (for region classification context)

        Returns:
            tuple: (label_data: dict, cost: float)
        """
        # Build OCR text representation for the prompt
        ocr_text = self._format_ocr_for_prompt(ocr_page)

        # Build the vision prompt with page context
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            ocr_page,
            ocr_text,
            current_page=ocr_page.page_number,
            total_pages=total_pages
        )

        # Generate simplified JSON Schema for structured outputs
        # OpenRouter's strict mode requires basic JSON Schema (no refs, no complex nesting)
        response_schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "page_labeling",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "printed_page_number": {"type": ["string", "null"]},
                        "numbering_style": {"type": ["string", "null"]},
                        "page_number_location": {"type": ["string", "null"]},
                        "page_number_confidence": {"type": "number"},
                        "page_region": {
                            "type": ["string", "null"],
                            "enum": ["front_matter", "body", "back_matter", "toc_area", "uncertain", None]
                        },
                        "page_region_confidence": {"type": ["number", "null"]},
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
                                                "confidence": {"type": "number"}
                                            },
                                            "required": ["par_num", "confidence"],
                                            "additionalProperties": False
                                        }
                                    }
                                },
                                "required": ["block_num", "classification", "classification_confidence", "paragraphs"],
                                "additionalProperties": False
                            }
                        }
                    },
                    "required": ["printed_page_number", "numbering_style", "page_number_location", "page_number_confidence", "page_region", "page_region_confidence", "blocks"],
                    "additionalProperties": False
                }
            }
        }

        # Call vision model with automatic JSON retry on parse failures
        def parse_label_json(response_text):
            """Parse and validate label JSON."""
            data = json.loads(response_text)  # Will raise JSONDecodeError if invalid
            return data

        label_data, usage, cost = self.llm_client.call_with_json_retry(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": '{"printed_page_number":'}  # Response prefilling for structure enforcement
            ],
            json_parser=parse_label_json,
            temperature=0.1,
            max_retries=2,  # Retry up to 2 times on JSON parse failures (3 total attempts)
            images=[page_image],
            timeout=180,
            response_format=response_schema
        )

        # Add metadata
        label_data['page_number'] = ocr_page.page_number
        label_data['model_used'] = self.model
        label_data['processing_cost'] = cost
        label_data['timestamp'] = datetime.now().isoformat()

        # Calculate summary stats
        avg_class_conf = sum(b.get('classification_confidence', 0) for b in label_data['blocks']) / len(label_data['blocks']) if label_data['blocks'] else 0
        avg_conf = sum(
            p.get('confidence', 1.0)
            for b in label_data['blocks']
            for p in b.get('paragraphs', [])
        ) / sum(len(b.get('paragraphs', [])) for b in label_data['blocks']) if label_data['blocks'] else 1.0

        label_data['total_blocks'] = len(label_data['blocks'])
        label_data['avg_classification_confidence'] = round(avg_class_conf, 3)
        label_data['avg_confidence'] = round(avg_conf, 3)

        return label_data, cost

    def _build_system_prompt(self):
        """Build the system prompt for vision labeling."""
        return """You are an expert page analysis assistant.

Extract printed page numbers from headers/footers and classify content blocks by type.
Do NOT correct OCR text - just analyze structure.

CRITICAL RULES (Check these FIRST):

1. INDENTATION = QUOTE
   - Indented both sides (0.25"-1") → QUOTE (even if content seems like body)
   - This is THE primary signal for QUOTE detection

2. EXPECTED DISTRIBUTION
   - BODY: 75-85% (majority)
   - QUOTE: 2-8% (regular but not frequent)
   - FOOTNOTE: 5-15% (common in academic books)
   - OTHER: <2% (RARE - check new types first)

3. BEFORE CHOOSING OTHER, CHECK:
   - Garbled text? → OCR_ARTIFACT
   - Map/geographic labels? → MAP_LABEL
   - Timeline/chart labels? → DIAGRAM_LABEL
   - Photo attribution? → PHOTO_CREDIT

4. PRINTED PAGE NUMBERS (from image headers/footers)
   ⚠️  CRITICAL: PDF page number ≠ printed page number
   - PDF page = our internal file number
   - Printed page = what's actually printed on the page image (may be totally different)

   Valid printed numbers: "23", "ix", "147" (standalone in corners/margins)
   Invalid: "Chapter 5", "page 1 of 300", running headers with numbers
   If no number visible on image → null

PAGE NUMBER EXTRACTION:
LOOK AT THE IMAGE (not the PDF page number) - check corners in order:
- top-right → top-center → bottom-center → bottom-corners
Roman (i, ii, iii) = front matter, Arabic (1, 2, 3) = body
Set confidence: 0.95-1.0 (clear), 0.85-0.94 (unusual position), 0.95 (no number found)

PAGE REGION CLASSIFICATION:
Use page position (current page X of Y total) to classify region:

- front_matter: First ~10% of book (typically roman numerals)
  * Title, copyright, dedication, preface, introduction
- toc_area: Table of Contents (look for ToC content + front matter position)
  * Multi-column layout, page numbers, hierarchical titles, dots/leaders
- body: Middle ~70-80% (typically arabic numerals starting at 1)
  * Main content chapters, regular BODY blocks dominate
- back_matter: Final ~10-20% (may be arabic or unnumbered)
  * INDEX, BIBLIOGRAPHY, ENDNOTES, APPENDIX blocks
- uncertain: Ambiguous position or mixed signals

Heuristics:
- First 10% + roman numerals → front_matter (conf 0.85-0.95)
- First 10% + ToC-like blocks → toc_area (conf 0.90-0.98)
- Middle 70% + arabic page 1+ → body (conf 0.90-0.98)
- Final 10-20% + INDEX/BIBLIOGRAPHY → back_matter (conf 0.85-0.95)
- Contradictory signals → uncertain (conf 0.50-0.70)

BLOCK TYPES:

Front/Back Matter: TITLE_PAGE, COPYRIGHT, DEDICATION, TABLE_OF_CONTENTS, PREFACE, INTRODUCTION
Content: CHAPTER_HEADING, SECTION_HEADING, BODY, QUOTE, EPIGRAPH
Reference: FOOTNOTE, ENDNOTES, BIBLIOGRAPHY, INDEX
Special: HEADER, FOOTER, PAGE_NUMBER, ILLUSTRATION_CAPTION, TABLE
New Types: OCR_ARTIFACT (garbled text), MAP_LABEL (geographic labels), DIAGRAM_LABEL (chart/timeline labels), PHOTO_CREDIT (image attribution)
Last Resort: OTHER (use <2% of the time)

CLASSIFICATION DECISION TREE:

1. INDENTATION (FIRST)
   - Both sides indented? → QUOTE (conf 0.90+)
   - Centered? → CHAPTER_HEADING, EPIGRAPH, DEDICATION
   - Hanging indent? → BIBLIOGRAPHY
   - Standard margins? → Continue

2. POSITION
   - Top 10%? → HEADER, CHAPTER_HEADING
   - Bottom 20%? → FOOTNOTE, FOOTER, PAGE_NUMBER
   - Middle? → BODY, SECTION_HEADING, QUOTE

3. FONT SIZE
   - 2x+ body → CHAPTER_HEADING
   - Larger/bold → SECTION_HEADING
   - <8pt → FOOTNOTE, PHOTO_CREDIT, FOOTER
   - Standard → BODY

4. CONTENT
   - Keywords ("Chapter", "Index") → Use specific type
   - Garbled → OCR_ARTIFACT
   - Geographic on map → MAP_LABEL
   - Chart labels → DIAGRAM_LABEL

CONFIDENCE:
0.95-1.0: Very clear signals
0.85-0.94: Most signals present
0.70-0.84: Some ambiguity
<0.70: Multiple types possible (consider OTHER)

EXAMPLES:

QUOTE (not BODY):
Indented 1" both sides, italicized text
"The policy was clear: no negotiations..."
→ QUOTE (conf 0.94) - Double indentation is primary signal

OCR_ARTIFACT (not OTHER):
Random characters: "l1I|l @@## tTtT"
→ OCR_ARTIFACT (conf 0.98) - Garbled OCR, not content

BODY with quotes (not QUOTE):
Standard margins: "The president said 'we shall prevail' in his speech."
→ BODY (conf 0.97) - Regular paragraph with embedded quote

OUTPUT FORMAT:
For each block: classification, classification_confidence (0-1.0), paragraphs with confidence
Focus on visual signals. Do NOT correct text."""

    def _build_user_prompt(self, ocr_page, ocr_text, current_page, total_pages):
        """Build the user prompt with OCR data and page context."""
        percent_through = (current_page / total_pages * 100) if total_pages > 0 else 0
        return f"""PDF page {ocr_page.page_number} of {total_pages} total PDF pages ({percent_through:.1f}% through document)

IMPORTANT: PDF page {ocr_page.page_number} is our internal file number. The PRINTED page number (what appears in headers/footers on the actual page image) may be completely different. You must LOOK AT THE IMAGE to extract the printed page number.

{ocr_text}

Analyze the page image:
1. Look at the image headers/footers to extract the PRINTED page number (may be different from PDF page {ocr_page.page_number})
2. Classify page region using PDF position ({percent_through:.1f}% through document)
3. Classify each block using visual signals (check indentation FIRST)

Follow the classification decision tree. Provide confidence scores based on signal clarity."""

    def _format_ocr_for_prompt(self, ocr_page):
        """Format OCR page data for the vision prompt."""
        lines = []
        page_dict = ocr_page.model_dump()
        for block in page_dict['blocks']:
            lines.append(f"\n--- Block {block['block_num']} ---")
            for para in block['paragraphs']:
                lines.append(f"  Paragraph {para['par_num']}: {para['text']}")
        return '\n'.join(lines)

    def clean_stage(self, scan_id: str, confirm: bool = False):
        """
        Clean/delete all label outputs and checkpoint for a book.

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

        labels_dir = book_dir / "labels"
        checkpoint_file = book_dir / "checkpoints" / "label.json"
        metadata_file = book_dir / "metadata.json"

        # Count what will be deleted
        label_files = list(labels_dir.glob("*.json")) if labels_dir.exists() else []

        print(f"\n🗑️  Clean Label stage for: {scan_id}")
        print(f"   Label outputs: {len(label_files)} files")
        print(f"   Checkpoint: {'exists' if checkpoint_file.exists() else 'none'}")

        if not confirm:
            response = input("\n   Proceed? (yes/no): ").strip().lower()
            if response != 'yes':
                print("   Cancelled.")
                return False

        # Delete label outputs
        if labels_dir.exists():
            import shutil
            shutil.rmtree(labels_dir)
            print(f"   ✓ Deleted {len(label_files)} label files")

        # Reset checkpoint
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            print(f"   ✓ Deleted checkpoint")

        # Update metadata
        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            metadata['labels_complete'] = False
            metadata.pop('labels_completion_date', None)
            metadata.pop('labels_total_cost', None)

            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            print(f"   ✓ Reset metadata")

        print(f"\n✅ Label stage cleaned for {scan_id}")
        return True
