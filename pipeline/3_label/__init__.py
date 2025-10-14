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
from infra.pdf_utils import downsample_for_vision

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

    def __init__(self, storage_root=None, model="google/gemini-2.5-flash-lite-preview-09-2025", max_workers=30, enable_checkpoints=True):
        """
        Initialize the VisionLabeler.

        Args:
            storage_root: Root directory for book storage (default: ~/Documents/book_scans)
            model: LLM model to use for labeling (default: google/gemini-2.5-flash-lite-preview-09-2025)
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

        # Initialize logger
        logs_dir = book_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        self.logger = create_logger(book_title, "label", log_dir=logs_dir)

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
                    'labels_dir': labels_dir
                })

            if len(tasks) == 0:
                self.logger.info("All pages already labeled, skipping")
                print("✅ All pages already labeled")
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
                            f"Labeling pages",
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
            metadata['labels_complete'] = True
            metadata['labels_completion_date'] = datetime.now().isoformat()
            metadata['labels_total_cost'] = total_cost

            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            self.logger.info(
                "Labeling complete",
                pages_labeled=completed,
                total_cost=total_cost,
                avg_cost_per_page=total_cost / completed if completed > 0 else 0,
                labels_dir=str(labels_dir)
            )

            print(f"\n✅ Labeling complete: {completed} pages")
            print(f"   Total cost: ${total_cost:.2f}")
            print(f"   Avg per page: ${total_cost/completed:.3f}" if completed > 0 else "")
            print(f"   Output: {labels_dir}")

            # Auto-retry failed pages (xAI cache workaround)
            # If there were failures and this wasn't already a resume, automatically retry
            if errors > 0 and not resume:
                retry_count = 0
                max_auto_retries = 2

                while errors > 0 and retry_count < max_auto_retries:
                    retry_count += 1

                    # Wait before retrying to allow xAI cache to expire
                    # Longer delays to avoid cache hits: 90s, 180s
                    delay = 90 * retry_count
                    print(f"\n⚠️  {errors} page(s) failed. Waiting {delay}s for xAI cache to clear...")
                    print(f"   Then auto-retrying (attempt {retry_count}/{max_auto_retries})")

                    import time
                    time.sleep(delay)

                    # Get remaining pages directly from checkpoint
                    if self.checkpoint:
                        remaining_pages = self.checkpoint.get_remaining_pages(
                            total_pages=total_pages,
                            resume=True
                        )

                        # Rebuild tasks for failed pages only
                        retry_tasks = []
                        for page_num in remaining_pages:
                            ocr_file = ocr_dir / f"page_{page_num:04d}.json"
                            if not ocr_file.exists():
                                continue

                            retry_tasks.append({
                                'page_num': page_num,
                                'ocr_file': ocr_file,
                                'pdf_files': pdf_files,
                                'labels_dir': labels_dir
                            })

                        if retry_tasks:
                            print(f"   Retrying {len(retry_tasks)} failed page(s)...")

                            # Process retry tasks in parallel
                            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                                future_to_task = {
                                    executor.submit(self._process_single_page, task): task
                                    for task in retry_tasks
                                }

                                for future in as_completed(future_to_task):
                                    task = future_to_task[future]
                                    try:
                                        success, cost = future.result()
                                        if success:
                                            with self.stats_lock:
                                                self.stats['pages_processed'] += 1
                                                self.stats['total_cost_usd'] += cost
                                        # Note: failures are already logged in _process_single_page
                                    except Exception as e:
                                        with self.progress_lock:
                                            self.logger.error(f"Page retry error", page=task['page_num'], error=str(e))

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
            label_data, cost = self._label_page_with_vision(ocr_page, page_image)

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

    def _label_page_with_vision(self, ocr_page, page_image):
        """
        Extract page numbers and classify blocks using vision model (no text correction).

        Args:
            ocr_page: OCRPageOutput object
            page_image: PIL Image of the page

        Returns:
            tuple: (label_data: dict, cost: float)
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
                "name": "page_labeling",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "printed_page_number": {"type": ["string", "null"]},
                        "numbering_style": {"type": ["string", "null"]},
                        "page_number_location": {"type": ["string", "null"]},
                        "page_number_confidence": {"type": "number"},
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
                    "required": ["printed_page_number", "numbering_style", "page_number_location", "page_number_confidence", "blocks"],
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
            response_format=response_schema  # ✓ Structured outputs enabled
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
        return """You are an expert page analysis assistant with vision capabilities.

<task>
Your task is to:
1. **Extract the printed page number** from headers/footers
2. **Classify content blocks** by type based on visual and textual signals

IMPORTANT: Do NOT correct any OCR text - just analyze structure and classify.
</task>

<page_number_extraction>
Look at the page image for printed page numbers:

Checklist:
1. Check top-right corner (most common)
2. Check top-center (chapter title pages)
3. Check bottom-center (alternate style)
4. Check bottom corners (less common)

Formats:
- Roman numerals (i, ii, iii, iv, v...) → typically front matter
- Arabic numerals (1, 2, 3...) → typically body content
- Unnumbered pages → title pages, blank pages, chapter starts

Output:
- `printed_page_number`: exact text (e.g., "ix", "45", or null if unnumbered)
- `numbering_style`: "roman", "arabic", or "none"
- `page_number_location`: "header", "footer", or "none"
- `page_number_confidence`: 0.9-1.0 if clearly visible, 0.7-0.8 if partially obscured, 1.0 if no number

Success Rate Goal: >92% (currently 87.7%)
</page_number_extraction>

<block_classification>

**Structural (Front/Back Matter):**
- TITLE_PAGE: Large centered text, minimal content, first page
- COPYRIGHT: Small text, "©" symbol, verso of title page, publishing info
- DEDICATION: Short centered text, often italicized, "To..." or "For..."
- TABLE_OF_CONTENTS: "Contents"/"Table of Contents" heading, dot leaders, page numbers
- PREFACE/FOREWORD: Heading with these words, author introduction before main content
- INTRODUCTION: "Introduction" heading, before Chapter 1

**Content Hierarchy:**
- CHAPTER_HEADING: Large centered/left-aligned, "Chapter N" or just number, substantial whitespace around
- SECTION_HEADING: Bold/larger than body, left-aligned, breaks text flow, section marker
- BODY: Standard paragraph text, consistent font size (10-12pt), majority of content
- QUOTE: Indented on both sides, often italicized, smaller margins, attributed text
- EPIGRAPH: Short quote at chapter start, often centered or right-aligned, sets chapter tone

**Reference Material:**
- FOOTNOTE: Small font (<8pt), bottom 20% of page, superscript numbers, references
- ENDNOTES: "Notes" heading, numbered list at end of chapter/book
- BIBLIOGRAPHY/REFERENCES: "Bibliography"/"References"/"Works Cited" heading, hanging indent
- INDEX: "Index" heading, multi-column layout, alphabetical entries, page numbers

**Back Matter:**
- APPENDIX: "Appendix" heading, supplementary tables/documents
- GLOSSARY: "Glossary" heading, definition list
- ACKNOWLEDGMENTS: "Acknowledgments"/"Acknowledgements" heading, thank-you text

**Page Metadata:**
- HEADER: Top of page, repeating text (chapter/book title), same across multiple pages
- FOOTER: Bottom of page, repeating text (often includes page number), same across pages
- PAGE_NUMBER: Standalone number (not embedded in header/footer text)

**Special Content:**
- ILLUSTRATION_CAPTION: Near image, "Figure N:" or "Plate:" or "Photo:" prefix, describes image
- TABLE: Grid structure, aligned columns, data in rows
- MAP_LABEL: Geographic labels on maps, place names, compass directions, scales
- DIAGRAM_LABEL: Labels on timelines, charts, diagrams, flowcharts, org charts
- PHOTO_CREDIT: Photo attribution, "Photo by...", "Courtesy of...", small text near images
- OCR_ARTIFACT: Garbled/nonsense text from OCR errors, random characters, unreadable fragments
- OTHER: Truly unclassifiable content (use VERY sparingly - <2% target)

</block_classification>

<quote_detection_guidance>
QUOTE is currently under-detected (0.86 confidence vs 0.97 for BODY). Pay special attention:

Visual Signals (strongest indicators):
1. **Indentation**: Indented from BOTH left and right margins (most reliable)
2. **Smaller margins**: Text block narrower than body paragraphs
3. **Font style**: Often italicized or different font
4. **Whitespace**: Extra space before and after the quote
5. **Attribution**: May have "—Author Name" or source citation after

Textual Signals:
- Opening/closing quotation marks
- Attribution lines
- Historical or literary content being referenced

Common Patterns:
- Block quotes in historical books
- Extended quotations from documents
- Testimony or interview excerpts
- Poetry or verse quoted within prose

IMPORTANT: Do NOT confuse QUOTE with:
- BODY text that happens to have quotes within it
- EPIGRAPH (short quote at chapter start)
- Regular paragraphs with quoted dialogue

Examples of QUOTE:
✅ Full paragraph indented on both sides discussing policy
✅ Extended testimony transcript with attribution
✅ Historical document excerpt with source citation
❌ Body paragraph containing a sentence in quotes
❌ Short centered quote at chapter opening (that's EPIGRAPH)
</quote_detection_guidance>

<other_usage_constraints>
OTHER is currently OVERUSED (3.9% of blocks, should be <2%).

ONLY use OTHER when content is:
1. Truly unclassifiable (doesn't fit ANY other category)
2. Ambiguous between multiple types with no clear winner
3. Unique special content not covered by other types

BEFORE choosing OTHER, ask:
- Is this a MAP_LABEL? (geographic text on maps)
- Is this a DIAGRAM_LABEL? (labels on charts/timelines)
- Is this a PHOTO_CREDIT? (image attribution)
- Is this an OCR_ARTIFACT? (garbled nonsense from OCR errors)
- Is this actually a HEADER/FOOTER? (repeating page elements)
- Is this actually a BODY paragraph? (standard text)

Common Mistakes (DO NOT mark as OTHER):
❌ Map labels → MAP_LABEL
❌ Photo credits → PHOTO_CREDIT
❌ Chart labels → DIAGRAM_LABEL
❌ Garbled OCR text → OCR_ARTIFACT
❌ Unusual formatting but still body text → BODY

Goal: Reduce OTHER from 3.9% to <2% by using specific types.
</other_usage_constraints>

<new_block_types>
Four new types added to reduce OTHER overuse:

OCR_ARTIFACT (addresses ~40% of current OTHER):
- Garbled, nonsense text from OCR failures
- Random character strings like "l1I|l" or "###@@"
- Unreadable fragments
- Clear OCR corruption, not real content

MAP_LABEL (addresses ~25% of current OTHER):
- Text on maps: place names, city labels
- Geographic annotations: "PACIFIC OCEAN", "FRANCE"
- Map legends, scales, compass labels
- Usually all-caps or distinctive geographic style

DIAGRAM_LABEL (addresses ~15% of current OTHER):
- Labels on timelines: dates, event names
- Chart annotations: axis labels, data points
- Flowchart/org chart text: boxes, connections
- Diagram callouts and annotations

PHOTO_CREDIT (addresses ~15% of current OTHER):
- Photo attribution: "Photo by John Smith"
- Image credits: "Courtesy of National Archives"
- Small text near photos
- Copyright notices for images
</new_block_types>

<confidence_guidance>
Confidence should reflect visual clarity of type signals:

HIGH CONFIDENCE (0.95-1.0):
- Very clear visual signals (size, position, whitespace, formatting)
- Type-specific keywords present ("Chapter", "Index", "Bibliography")
- No ambiguity about classification
- Example: Chapter heading with large font and whitespace

CONFIDENT (0.85-0.94):
- Most signals present
- Minor ambiguity but clear best choice
- Example: QUOTE with indentation but no italics

MODERATE (0.70-0.84):
- Some signals present
- Ambiguity between 2 types
- Example: SECTION_HEADING vs BODY (bold but not much larger)

LOW (<0.70):
- Unclear signals
- Multiple types possible
- Consider OTHER if truly cannot classify
- Example: Unusual formatting, no clear type match

Expected Distribution:
- BODY: 0.95-0.99 (very clear)
- CHAPTER_HEADING: 0.95-1.0 (obvious)
- QUOTE: 0.90-0.95 (work on improving from current 0.86)
- FOOTNOTE: 0.90-0.95 (small font is distinctive)
- OTHER: 0.60-0.80 (inherently ambiguous)
</confidence_guidance>

<classification_strategy>
Follow this decision tree:

1. **Position Check**:
   - Top 10%? → Likely HEADER, CHAPTER_HEADING, or page start element
   - Bottom 20%? → Likely FOOTNOTE, FOOTER, or PAGE_NUMBER
   - Middle? → Likely BODY, QUOTE, SECTION_HEADING

2. **Font Size Check**:
   - Much larger (2x+)? → CHAPTER_HEADING
   - Slightly larger/bold? → SECTION_HEADING
   - Much smaller (<8pt)? → FOOTNOTE, PHOTO_CREDIT, FOOTER
   - Standard size? → BODY, QUOTE

3. **Indentation Check**:
   - Indented both sides? → QUOTE (high priority check!)
   - Centered? → CHAPTER_HEADING, EPIGRAPH, DEDICATION
   - Hanging indent? → BIBLIOGRAPHY item

4. **Content Check**:
   - Keywords: "Chapter", "Index", "Bibliography", etc.
   - Garbled nonsense? → OCR_ARTIFACT
   - Geographic names on visual? → MAP_LABEL
   - Timeline/chart labels? → DIAGRAM_LABEL
   - Photo attribution? → PHOTO_CREDIT

5. **Whitespace Check**:
   - Substantial whitespace around? → CHAPTER_HEADING, SECTION_HEADING
   - Tight spacing? → FOOTNOTE, BODY

6. **Final Check**:
   - Does it fit a specific type? → Use that type
   - Truly unclassifiable? → OTHER (rarely)
</classification_strategy>

<examples>
Example 1: Clear QUOTE (Not BODY)
Visual: Text indented 1" from both margins, italicized
Content: "The policy was clear: no negotiations with..."
Output: {
  "classification": "QUOTE",
  "classification_confidence": 0.94
}
Reasoning: Double indentation is primary signal for QUOTE

Example 2: OCR_ARTIFACT (Not OTHER)
Visual: Small scattered text, random characters
Content: "l1I|l @@## tTtT"
Output: {
  "classification": "OCR_ARTIFACT",
  "classification_confidence": 0.98
}
Reasoning: Clearly garbled OCR, not real content

Example 3: BODY with quotes (Not QUOTE)
Visual: Standard margins, normal formatting
Content: "The president said 'we shall prevail' in his speech."
Output: {
  "classification": "BODY",
  "classification_confidence": 0.97
}
Reasoning: Regular paragraph with quoted text inside, not a block quote

Example 4: MAP_LABEL (Not OTHER)
Visual: Text on map image, all-caps
Content: "PACIFIC OCEAN" and "JAPAN"
Output: {
  "classification": "MAP_LABEL",
  "classification_confidence": 0.96
}
Reasoning: Geographic labels on map, clear map context
</examples>

<output_format>
For each block:
- `classification`: BlockType enum value (use specific types, avoid OTHER)
- `classification_confidence`: 0.0-1.0 (based on signal clarity)
- `paragraphs`: List of paragraph labels with confidence scores

Focus on structural classification using visual signals. Do NOT correct OCR text.
</output_format>"""

    def _build_user_prompt(self, ocr_page, ocr_text):
        """Build the user prompt with OCR data."""
        return f"""Page {ocr_page.page_number} OCR output to analyze:

{ocr_text}

Analyze the page image to:
1. **Extract page number** - Look in headers/footers (set to null if unnumbered)
2. **Classify each block** - Use visual signals (font, position, whitespace, alignment) + textual content

For each block, follow the classification strategy:
- Check position on page
- Compare font size/style to context
- Look for type-specific formatting
- Assign appropriate block type from the categories above
- Provide confidence score (0.9-1.0 for clear, 0.7-0.8 for minor ambiguity, etc.)

Remember: Analyze structure only. Do NOT correct OCR text."""

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
