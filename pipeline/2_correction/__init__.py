#!/usr/bin/env python3
"""
Vision-Based OCR Correction (Text Only)

Corrects OCR errors using multimodal LLM.
Block classification and page number extraction are handled in Stage 3 (Label).

Reads source page images from {scan_id}/source/page_XXXX.png
Writes corrected output to {scan_id}/corrected/page_XXXX.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from PIL import Image
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from infra.config import Config
from infra.logger import create_logger
from infra.checkpoint import CheckpointManager
from infra.llm_batch_client import LLMBatchClient
from infra.llm_models import LLMRequest, LLMResult, EventData, LLMEvent
from infra.pdf_utils import downsample_for_vision
from infra.progress import ProgressBar

# Import schemas
import importlib
ocr_schemas = importlib.import_module('pipeline.1_ocr.schemas')
OCRPageOutput = ocr_schemas.OCRPageOutput

correction_schemas = importlib.import_module('pipeline.2_correction.schemas')
CorrectionPageOutput = correction_schemas.CorrectionPageOutput
BlockCorrection = correction_schemas.BlockCorrection
ParagraphCorrection = correction_schemas.ParagraphCorrection


class VisionCorrector:
    """
    Vision-based OCR correction (text only).

    Uses multimodal LLM to correct OCR errors by comparing text against page images.
    Block classification and page number extraction are handled in Stage 3 (Label).

    Supports checkpoint-based resume and parallel processing.
    """

    def __init__(self, storage_root=None, model=None, max_workers=30, enable_checkpoints=True, max_retries=3):
        """
        Initialize the VisionCorrector.

        Args:
            storage_root: Root directory for book storage (default: ~/Documents/book_scans)
            model: LLM model to use for correction (default: from Config.VISION_MODEL env var)
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
        self.batch_client = None  # Will be initialized per book
        self.verbose = False  # Can be set for detailed progress

    def process_book(self, book_title, resume=False):
        """
        Process all pages for OCR text correction only.

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
        self.logger = create_logger(book_title, "correction", log_dir=logs_dir, console_output=False)

        # Initialize batch LLM client
        self.batch_client = LLMBatchClient(
            max_workers=self.max_workers,
            rate_limit=150,  # OpenRouter default
            max_retries=self.max_retries,
            retry_jitter=(1.0, 3.0),
            json_retry_budget=2,
            verbose=self.verbose,
            progress_interval=0.5  # Update progress every 0.5s
        )

        # Initialize checkpoint manager
        if self.enable_checkpoints:
            self.checkpoint = CheckpointManager(
                scan_id=book_title,
                stage="correction",
                storage_root=self.storage_root,
                output_dir="corrected"
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

            # Stage entry
            print(f"\n🔧 Correction Stage ({book_title})")
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

            # Pre-load OCR data and prepare requests (parallelized)
            print(f"\n   Loading {len(pages_to_process)} pages...")
            load_progress = ProgressBar(
                total=len(pages_to_process),
                prefix="   ",
                width=40,
                unit="pages"
            )
            load_progress.update(0, suffix="loading...")

            requests = []
            page_data_map = {}  # Store loaded data for saving later
            completed_loads = 0
            load_lock = threading.Lock()

            # Build JSON schema once (shared across all requests)
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
                                        "block_num": {"type": "integer", "minimum": 1},
                                        "paragraphs": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "par_num": {"type": "integer", "minimum": 1},
                                                    "text": {"type": ["string", "null"]},
                                                    "notes": {"type": ["string", "null"]},
                                                    "confidence": {"type": "number"}
                                                },
                                                "required": ["par_num", "text", "notes", "confidence"],
                                                "additionalProperties": False
                                            }
                                        }
                                    },
                                    "required": ["block_num", "paragraphs"],
                                    "additionalProperties": False
                                }
                            }
                        },
                        "required": ["blocks"],
                        "additionalProperties": False
                    }
                }
            }

            # Build system prompt once (same for all pages)
            system_prompt = self._build_system_prompt()

            def load_page(page_num):
                """Load and prepare a single page (called in parallel)."""
                ocr_file = ocr_dir / f"page_{page_num:04d}.json"
                page_file = source_dir / f"page_{page_num:04d}.png"

                if not ocr_file.exists() or not page_file.exists():
                    return None

                try:
                    # Load OCR data
                    with open(ocr_file, 'r') as f:
                        ocr_data = json.load(f)
                    ocr_page = OCRPageOutput(**ocr_data)

                    # Load and downsample image (CPU-intensive, releases GIL in PIL)
                    page_image = Image.open(page_file)
                    page_image = downsample_for_vision(page_image)

                    # Build page-specific prompt with book context
                    ocr_text = self._format_ocr_for_prompt(ocr_page)
                    user_prompt = self._build_user_prompt(
                        ocr_page,
                        ocr_text,
                        page_num=page_num,
                        total_pages=total_pages,
                        book_metadata=metadata
                    )

                    # Create LLM request (multimodal)
                    # The page_image is passed via images= parameter and gets sent
                    # to the LLM alongside the text prompt for vision-based correction
                    request = LLMRequest(
                        id=f"page_{page_num:04d}",
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                            {"role": "assistant", "content": '{"blocks": ['}  # Response prefilling
                        ],
                        temperature=0.1,
                        timeout=180,
                        images=[page_image],
                        response_format=response_schema,
                        metadata={
                            'page_num': page_num,
                            'corrected_dir': str(corrected_dir),
                            'ocr_page_number': ocr_page.page_number
                        }
                    )

                    return (page_num, ocr_page, request)

                except Exception as e:
                    self.logger.error(f"Failed to load page data", page=page_num, error=str(e))
                    return None

            # Parallel loading with ThreadPoolExecutor
            # Use CPU count for workers (good for I/O + CPU-bound downsampling)
            import os
            load_workers = os.cpu_count() or 4

            with ThreadPoolExecutor(max_workers=load_workers) as executor:
                # Submit all loading tasks
                future_to_page = {
                    executor.submit(load_page, page_num): page_num
                    for page_num in pages_to_process
                }

                # Collect results as they complete
                for future in as_completed(future_to_page):
                    result = future.result()
                    if result:
                        page_num, ocr_page, request = result
                        requests.append(request)
                        page_data_map[page_num] = {
                            'ocr_page': ocr_page,
                            'request': request
                        }

                    with load_lock:
                        completed_loads += 1
                        load_progress.update(completed_loads, suffix=f"{len(requests)} loaded")

            # Finish loading progress
            load_progress.finish()

            if len(requests) == 0:
                self.logger.info("No valid pages to process")
                print("✅ No valid pages to process")
                return

            # Setup progress tracking
            print(f"\n   Correcting {len(requests)} pages...")
            progress = ProgressBar(
                total=len(requests),
                prefix="   ",
                width=40,
                unit="pages"
            )
            progress.update(0, suffix="starting...")  # Show initial progress bar
            completed_count = 0
            failed_pages = []

            # Define event callback for progress updates
            def on_event(event: EventData):
                nonlocal progress
                if event.event_type == LLMEvent.PROGRESS:
                    # Update progress bar with aggregate stats
                    with self.stats_lock:
                        total_cost = self.stats['total_cost_usd']
                    rate_util = event.rate_limit_status.get('utilization', 0) if event.rate_limit_status else 0

                    # Show different message if no completions yet
                    if event.completed == 0:
                        suffix = f"{event.in_flight} executing..."
                    else:
                        suffix = f"${total_cost:.2f} | {rate_util:.0%} rate"

                    progress.update(event.completed, suffix=suffix)
                elif event.event_type == LLMEvent.RATE_LIMITED:
                    progress.set_status(f"⏸️  Rate limited, resuming in {event.eta_seconds:.0f}s")

            # Define result callback for checkpoint/stats
            def on_result(result: LLMResult):
                nonlocal completed_count, failed_pages

                page_num = result.request.metadata['page_num']

                if result.success:
                    try:
                        # Add metadata to correction data
                        correction_data = result.parsed_json
                        correction_data['page_number'] = result.request.metadata['ocr_page_number']
                        correction_data['model_used'] = self.model
                        correction_data['processing_cost'] = result.cost_usd
                        correction_data['timestamp'] = datetime.now().isoformat()

                        # Calculate summary stats
                        total_corrections = sum(
                            1 for block in correction_data['blocks']
                            for p in block.get('paragraphs', [])
                            if p.get('text') is not None
                        )

                        avg_conf = sum(
                            p.get('confidence', 1.0)
                            for b in correction_data['blocks']
                            for p in b.get('paragraphs', [])
                        ) / sum(len(b.get('paragraphs', [])) for b in correction_data['blocks']) if correction_data['blocks'] else 1.0

                        correction_data['total_blocks'] = len(correction_data['blocks'])
                        correction_data['total_corrections'] = total_corrections
                        correction_data['avg_confidence'] = round(avg_conf, 3)

                        # Validate output against schema
                        validated = CorrectionPageOutput(**correction_data)
                        correction_data = validated.model_dump()

                        # Save corrected output
                        output_file = Path(result.request.metadata['corrected_dir']) / f"page_{page_num:04d}.json"
                        with open(output_file, 'w', encoding='utf-8') as f:
                            json.dump(correction_data, f, indent=2)

                        # Update checkpoint & stats
                        if self.checkpoint:
                            self.checkpoint.mark_completed(page_num, cost_usd=result.cost_usd)

                        with self.stats_lock:
                            self.stats['pages_processed'] += 1
                            self.stats['total_cost_usd'] += result.cost_usd

                        completed_count += 1

                    except Exception as e:
                        self.logger.error(f"Failed to save page result", page=page_num, error=str(e))
                        failed_pages.append(page_num)
                else:
                    # Permanent failure
                    self.logger.error(f"Page correction failed permanently", page=page_num, error=result.error_message)
                    failed_pages.append(page_num)

            # JSON parser function
            def parse_correction_json(response_text):
                """Parse and validate correction JSON."""
                data = json.loads(response_text)
                return data

            # Process batch with new client
            results = self.batch_client.process_batch(
                requests,
                json_parser=parse_correction_json,
                on_event=on_event,
                on_result=on_result
            )

            # Finish progress bar
            progress.finish(f"   ✓ {completed_count}/{len(requests)} pages corrected")
            errors = len(failed_pages)
            if errors > 0:
                print(f"   ⚠️  {errors} pages failed: {sorted(failed_pages)[:10]}" + (f" and {len(failed_pages)-10} more" if len(failed_pages) > 10 else ""))

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
                metadata['correction_complete'] = True
                metadata['correction_completion_date'] = datetime.now().isoformat()
                metadata['correction_total_cost'] = total_cost

                with open(metadata_file, 'w') as f:
                    json.dump(metadata, f, indent=2)

                # Log completion to file (not stdout)
                self.logger.info(
                    "Correction complete",
                    pages_corrected=completed,
                    total_cost=total_cost,
                    avg_cost_per_page=total_cost / completed if completed > 0 else 0,
                    corrected_dir=str(corrected_dir)
                )

                # Print stage exit (success)
                print(f"\n✅ Correction complete: {completed}/{total_pages} pages")
                print(f"   Total cost: ${total_cost:.2f}")
                print(f"   Avg per page: ${total_cost/completed:.3f}" if completed > 0 else "")
            else:
                # Stage incomplete - some pages failed
                failed_pages = sorted([t['page_num'] for t in pending_tasks])
                print(f"\n⚠️  Correction incomplete: {completed}/{total_pages} pages succeeded")
                print(f"   Total cost: ${total_cost:.2f}")
                print(f"   Failed pages: {failed_pages}")
                print(f"\n   To retry failed pages:")
                print(f"   uv run python ar.py process correction {book_title} --resume")

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


    def _build_system_prompt(self):
        """Build the system prompt for vision correction."""
        return """<role>
You are an OCR correction specialist. Compare OCR text against page images to identify and fix character-reading errors only.
</role>

<output_schema>
Return JSON with corrected paragraphs. For each paragraph:
- text: Full corrected paragraph (null if no errors)
- notes: Brief correction description (max 100 characters)
- confidence: Error certainty score (0.0-1.0)

The JSON schema is enforced by the API. Focus on accuracy.
</output_schema>

<rules>
1. Use 1-based indexing: block_num and par_num start at 1 (not 0)
2. No errors detected: Set text=null with notes="No OCR errors detected" (exactly)
3. Errors found: Set text=FULL_CORRECTED_PARAGRAPH (not partial)
4. Notes must describe corrections actually applied to text field
5. Most paragraphs (80-90%) have no errors - expect text=null frequently
6. When text=null, notes must be "No OCR errors detected" (not correction descriptions)
</rules>

<examples>
<example type="no_errors">
  <ocr>The president announced the policy today.</ocr>
  <output>{"text": null, "notes": "No OCR errors detected", "confidence": 1.0}</output>
</example>

<example type="line_break_hyphen">
  <ocr>The cam- paign in Kan- sas</ocr>
  <image_content>The campaign in Kansas (no hyphens visible)</image_content>
  <correction>Remove hyphen AND space to join word parts: "cam- paign" becomes "campaign"</correction>
  <output>{"text": "The campaign in Kansas", "notes": "Removed line-break hyphens: 'cam-paign', 'Kan-sas'", "confidence": 0.97}</output>
  <note>Most common OCR error (70% of corrections). Line-break hyphens are printing artifacts where words split across lines.</note>
</example>

<example type="character_substitution">
  <ocr>The modem world</ocr>
  <image_content>modern</image_content>
  <output>{"text": "The modern world", "notes": "Fixed 'modem'→'modern' (rn→m)", "confidence": 0.95}</output>
</example>

<example type="ligature">
  <ocr>The first ofﬁce policy</ocr>
  <image_content>office (standard text, not ligature)</image_content>
  <output>{"text": "The first office policy", "notes": "Fixed ligature 'ffi' in 'office'", "confidence": 0.98}</output>
</example>

<example type="number_letter_confusion">
  <ocr>l9l5 presidential election</ocr>
  <image_content>1915 presidential election</image_content>
  <output>{"text": "1915 presidential election", "notes": "Fixed '1'/'l' confusion in '1915'", "confidence": 0.93}</output>
</example>

<example type="multiple_fixes">
  <ocr>The govern- ment an- nounced policy.</ocr>
  <image_content>The government announced policy.</image_content>
  <output>{"text": "The government announced policy.", "notes": "Removed line-break hyphens in 'government', 'announced'", "confidence": 0.96}</output>
</example>

<example type="historical_spelling">
  <ocr>The connexion between nations</ocr>
  <image_content>connexion (period-appropriate spelling)</image_content>
  <output>{"text": null, "notes": "No OCR errors detected", "confidence": 1.0}</output>
  <reasoning>Preserve historical spellings - not OCR errors</reasoning>
</example>
</examples>

<fix_these>
Character-level OCR reading errors only:

- Line-break hyphens: "cam- paign" becomes "campaign"
  Pattern: word-hyphen-space-word becomes single word
  Remove BOTH hyphen and space (join completely)

- Character substitutions: Common patterns include
  rn mistaken for m (e.g., "modem" for "modern")
  cl mistaken for d (e.g., "clistance" for "distance")
  li mistaken for h (e.g., "tlie" for "the")
  1 mistaken for l or I (e.g., "l9l5" for "1915")
  0 mistaken for O (e.g., "0ctober" for "October")
  5 mistaken for S (e.g., "5eptember" for "September")

- Ligature misreads: fi, fl, ff, ffi, ffl rendered as special characters

- Spacing errors:
  Missing spaces: "thebook" becomes "the book"
  Extra spaces: "a  book" becomes "a book"

- Punctuation: Smart quotes, em dashes, symbol misreads
</fix_these>

<do_not_fix>
Content and style elements (out of scope):

- Grammar, sentence structure, word choice
- Writing quality or style improvements
- Historical spellings: "connexion", "colour", "defence", archaic terms
- Legitimate compound hyphens: "self-aware", "Vice-President", "pre-WWI"
  Identification: No space after hyphen indicates real compound word
- Factual content, dates, numbers (not verifiable from image alone)
- Capitalization style preferences
</do_not_fix>

<confidence_guidelines>
Base confidence score on image clarity and error pattern obviousness:

- 0.95-1.0: Obvious error with clear image and common pattern
- 0.85-0.94: Clear error with minor ambiguity in image
- 0.70-0.84: Some ambiguity in image quality or error pattern
- Below 0.70: Too uncertain - use text=null instead

Do not express uncertainty in notes. Use confidence score for uncertainty level.
</confidence_guidelines>

<notes_format>
Keep notes brief (under 100 characters). Use standardized formats:

- "Removed line-break hyphen in 'campaign'"
- "Removed line-break hyphens: 'campaign', 'announced'"
- "Fixed 'modem'→'modern' (character substitution)"
- "Fixed ligature 'ffi' in 'office'"
- "Fixed '1'/'l' confusion in '1915'"
- "No OCR errors detected"

Do not write explanations or descriptions of thought process.
</notes_format>

<historical_documents>
This text may use period-appropriate conventions:
- Preserve archaic spellings unless clearly OCR errors
- Maintain historical capitalization patterns
- Keep period-specific punctuation conventions
</historical_documents>

<output_requirements>
Return ONLY valid JSON matching the schema.
Do not include markdown code fences.
Do not add explanatory text outside JSON structure.
Do not include reasoning or analysis.
</output_requirements>"""

    def _build_user_prompt(self, ocr_page, ocr_text, page_num, total_pages, book_metadata):
        """
        Build the user prompt with OCR data and document context.

        The page image is attached separately via the LLMRequest.images parameter
        and sent alongside this text prompt for multimodal vision correction.
        """
        # Extract metadata fields with defaults
        title = book_metadata.get('title', 'Unknown')
        author = book_metadata.get('author', 'Unknown')
        year = book_metadata.get('year', 'Unknown')
        book_type = book_metadata.get('type', 'Unknown')

        return f"""<document_context>
Title: {title}
Author: {author}
Year: {year}
Type: {book_type}
</document_context>

<page_context>
Scanned page {page_num} of {total_pages} (PDF page number, not printed page number)
</page_context>

<ocr_data>
{ocr_text}
</ocr_data>

<task>
Compare the OCR text above against the page image.

For each block and paragraph:
1. Visually check if OCR text matches the image character-by-character
2. If text matches image: Set text=null with notes="No OCR errors detected"
3. If OCR reading errors found: Output full corrected paragraph text
4. Provide brief notes using standardized format from examples
5. Assign confidence score based on image clarity and error obviousness

Remember: You are correcting character-level OCR reading errors only, not editing content. Most paragraphs (80-90%) should have text=null.
</task>"""

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
        logs_dir = book_dir / "logs"
        metadata_file = book_dir / "metadata.json"

        # Count what will be deleted
        corrected_files = list(corrected_dir.glob("*.json")) if corrected_dir.exists() else []
        log_files = list(logs_dir.glob("correction_*.jsonl")) if logs_dir.exists() else []

        print(f"\n🗑️  Clean Correction stage for: {scan_id}")
        print(f"   Corrected outputs: {len(corrected_files)} files")
        print(f"   Checkpoint: {'exists' if checkpoint_file.exists() else 'none'}")
        print(f"   Logs: {len(log_files)} files")

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

        # Delete log files
        if log_files:
            for log_file in log_files:
                log_file.unlink()
            print(f"   ✓ Deleted {len(log_files)} log files")

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
