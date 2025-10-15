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
import base64
import io
from pathlib import Path
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

    def __init__(self, storage_root=None, model="google/gemini-2.5-flash-lite-preview-09-2025", max_workers=30, enable_checkpoints=True, max_retries=3):
        """
        Initialize the VisionCorrector.

        Args:
            storage_root: Root directory for book storage (default: ~/Documents/book_scans)
            model: LLM model to use for correction (default: google/gemini-2.5-flash-lite-preview-09-2025)
            max_workers: Number of parallel workers (default: 30)
            enable_checkpoints: Enable checkpoint-based resume (default: True)
            max_retries: Maximum retry attempts for failed pages (default: 3, use 1 for no retries)
        """
        self.storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
        self.model = model
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
                    'corrected_dir': corrected_dir
                })

            if len(tasks) == 0:
                self.logger.info("All pages already corrected, skipping")
                print("✅ All pages already corrected")
                return

            # Process with single-pass retry logic
            # Progress bar tracks total pages (not iterations)
            print(f"\n   Correcting {len(tasks)} pages...")
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
                        # Max retries reached - update pending_tasks to final failures
                        pending_tasks = failed_tasks
                        print(f"\n   ⚠️  {len(pending_tasks)} page(s) failed after {self.max_retries} attempts")
                        break
                else:
                    # All succeeded
                    break

            # Finish progress bar
            errors = len(pending_tasks) if retry_count >= self.max_retries else 0
            progress.finish(f"   ✓ {completed}/{len(tasks)} pages corrected")
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

            # Call vision model for correction only
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

    def _image_to_base64(self, pil_image):
        """Convert PIL Image to base64 string for vision API."""
        buffered = io.BytesIO()
        pil_image.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()
        return base64.b64encode(img_bytes).decode('utf-8')

    def _correct_page_with_vision(self, ocr_page, page_image):
        """
        Correct OCR errors using vision model (text corrections only).

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

        # Call vision model with automatic JSON retry on parse failures
        def parse_correction_json(response_text):
            """Parse and validate correction JSON."""
            data = json.loads(response_text)  # Will raise JSONDecodeError if invalid
            return data

        correction_data, usage, cost = self.llm_client.call_with_json_retry(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": '{"blocks": ['}  # Response prefilling for structure enforcement
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

        avg_conf = sum(
            p.get('confidence', 1.0)
            for b in correction_data['blocks']
            for p in b.get('paragraphs', [])
        ) / sum(len(b.get('paragraphs', [])) for b in correction_data['blocks']) if correction_data['blocks'] else 1.0

        correction_data['total_blocks'] = len(correction_data['blocks'])
        correction_data['total_corrections'] = total_corrections
        correction_data['avg_confidence'] = round(avg_conf, 3)

        return correction_data, cost

    def _build_system_prompt(self):
        """Build the system prompt for vision correction."""
        return """Fix OCR character-reading errors by comparing text to the page image.

═══════════════════════════════════════════════════════════════════════
CRITICAL RULES (READ THESE FIRST)
═══════════════════════════════════════════════════════════════════════

1. OUTPUT FORMAT:
   - Use 1-based numbering: block_num and par_num start at 1 (not 0)
   - If NO errors: text=null, notes="No OCR errors detected"
   - If errors found: text=CORRECTED_FULL_PARAGRAPH, notes="Brief description"

2. WHEN YOU WRITE NOTES, YOU MUST APPLY THOSE CHANGES TO TEXT:
   ❌ WRONG: notes="Fixed X", but text still has X
   ✅ CORRECT: notes="Fixed X", text has X corrected

3. WHEN text=null, notes MUST be "No OCR errors detected" (exactly)
   ❌ WRONG: text=null but notes describes changes
   ❌ WRONG: text=full_paragraph with notes="No OCR errors detected"

4. MOST PARAGRAPHS (80-90%) HAVE NO ERRORS → text=null

═══════════════════════════════════════════════════════════════════════
EXAMPLES (Learn from these)
═══════════════════════════════════════════════════════════════════════

Example 1: No Errors
OCR: "The president announced the policy today."
→ Output: {"text": null, "notes": "No OCR errors detected", "confidence": 1.0}

Example 2: Line-Break Hyphen (Most Common - 70% of fixes)
OCR: "The cam- paign in Kan- sas"
Image shows: "The campaign in Kansas" (no hyphens in original)
→ Output: {"text": "The campaign in Kansas", "notes": "Removed line-break hyphens: 'cam- paign'→'campaign', 'Kan- sas'→'Kansas'", "confidence": 0.97}

CRITICAL: Remove BOTH the hyphen AND the space (join word parts completely)
❌ WRONG: "cam-paign" (kept hyphen, removed space)
✅ CORRECT: "campaign" (removed hyphen AND space)

Example 3: Character Substitution
OCR: "The modem world"
Image shows: "modern"
→ Output: {"text": "The modern world", "notes": "Fixed 'modem'→'modern' (rn→m)", "confidence": 0.95}

Example 4: Multiple Fixes
OCR: "The govern- ment an- nounced policy."
→ Output: {"text": "The government announced policy.", "notes": "Removed line-break hyphens in 'government', 'announced'", "confidence": 0.96}

═══════════════════════════════════════════════════════════════════════
WHAT TO FIX
═══════════════════════════════════════════════════════════════════════

✅ FIX THESE (Character-Level OCR Errors Only):
• Line-break hyphens: "cam- paign" → "campaign" (remove BOTH hyphen + space)
  Pattern: [word]- [space][word] → join into single word
  Note: These are printing artifacts where words split across lines
• Character swaps: rn→m, cl→d, li→h, 1→l, 0→O
• Ligatures: fi, fl, ff, ffi, ffl misread
• Spacing: "thebook"→"the book" or "a  book"→"a book"
• Punctuation: smart quotes, em dashes, symbol misreads

❌ DO NOT FIX:
• Grammar, writing quality, word choice
• Historical spellings (keep "connexion", old terms)
• Real compound hyphens: Keep "self-aware", "Vice-President", "pre-WWI", "T-Force"
  (No space after hyphen = real hyphen, keep it!)
• Facts, dates, numbers (not your job to validate)
• Capitalization style preferences

═══════════════════════════════════════════════════════════════════════
CONFIDENCE SCORES
═══════════════════════════════════════════════════════════════════════

Based ONLY on image clarity and error obviousness:
• 0.95-1.0: Obvious error, clear image (line-break hyphens, clear substitutions)
• 0.85-0.94: Clear error, minor ambiguity
• 0.70-0.84: Some ambiguity in image or error pattern
• <0.70: Uncertain - consider text=null instead

═══════════════════════════════════════════════════════════════════════
NOTES FORMAT
═══════════════════════════════════════════════════════════════════════

Keep brief (under 100 chars):
• "Removed line-break hyphen in 'word'"
• "Fixed 'X'→'Y' (character substitution)"
• "No OCR errors detected" (when text=null)

DO NOT write long explanations, analysis, or uncertainty.
If uncertain, lower confidence score instead.

═══════════════════════════════════════════════════════════════════════
REMEMBER
═══════════════════════════════════════════════════════════════════════

1. Text=null means "No OCR errors detected" (use this 80-90% of the time)
2. When you document a correction in notes, APPLY it in text
3. Output FULL corrected paragraph, not partial fixes
4. Keep notes brief and factual"""

    def _build_user_prompt(self, ocr_page, ocr_text):
        """Build the user prompt with OCR data."""
        return f"""Page {ocr_page.page_number} OCR output to verify:

{ocr_text}

Compare this OCR text to the page image you see above.

For each block/paragraph:
1. Visually check if OCR text matches what you SEE in the image (character by character)
2. If characters match → Set `text` to null (no correction needed)
3. If you find character-level OCR reading errors → Output full corrected text
4. Add brief `notes` explaining what you fixed (use standardized format)
5. Provide `confidence` score based on image clarity and error certainty

Remember: You are correcting OCR reading errors, not editing content. Most paragraphs (80-90%) should have `text: null`."""

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
