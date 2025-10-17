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
import time
from pathlib import Path
from datetime import datetime
from PIL import Image
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from infra.config import Config
from infra.llm_batch_client import LLMBatchClient
from infra.llm_models import LLMRequest, LLMResult, EventData, LLMEvent, RequestPhase
from infra.pdf_utils import downsample_for_vision
from infra.progress import ProgressBar
from infra.book_storage import BookStorage

# Import schemas
import importlib
ocr_schemas = importlib.import_module('pipeline.1_ocr.schemas')
OCRPageOutput = ocr_schemas.OCRPageOutput

correction_schemas = importlib.import_module('pipeline.2_correction.schemas')
CorrectionPageOutput = correction_schemas.CorrectionPageOutput
CorrectionLLMResponse = correction_schemas.CorrectionLLMResponse
BlockCorrection = correction_schemas.BlockCorrection
ParagraphCorrection = correction_schemas.ParagraphCorrection

# Import prompts
correction_prompts = importlib.import_module('pipeline.2_correction.prompts')
SYSTEM_PROMPT = correction_prompts.SYSTEM_PROMPT
build_user_prompt = correction_prompts.build_user_prompt


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
        # Initialize storage manager
        try:
            storage = BookStorage(scan_id=book_title, storage_root=self.storage_root)
            storage.correction.validate_inputs()  # Validates book exists, OCR complete, metadata exists
        except FileNotFoundError as e:
            print(f"❌ {e}")
            return

        # Load metadata
        metadata = storage.load_metadata()

        # Ensure directories (creates corrected/, logs/, checkpoints/)
        storage.correction.ensure_directories()

        # Initialize batch LLM client with failure logging
        self.batch_client = LLMBatchClient(
            max_workers=self.max_workers,
            rate_limit=150,  # OpenRouter default
            max_retries=self.max_retries,
            retry_jitter=(1.0, 3.0),
            json_retry_budget=2,
            verbose=True,  # Enable per-request events for progress tracking
            progress_interval=0.5,  # Update progress every 0.5s
            log_dir=storage.correction.get_log_dir()  # Log failed LLM calls to corrected/logs/llm_failures.jsonl
        )

        # Handle checkpoint (integrated into storage.correction)
        if self.enable_checkpoints:
            checkpoint = storage.correction.checkpoint
            if not resume:
                # Check if checkpoint exists with progress before resetting
                if checkpoint.checkpoint_file.exists():
                    status = checkpoint.get_status()
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

                checkpoint.reset()

        try:
            # Get list of OCR outputs
            ocr_files = storage.ocr.list_output_pages()
            total_pages = len(ocr_files)  # For logging/display only

            # Stage entry
            print(f"\n🔧 Correction Stage ({book_title})")
            print(f"   Pages:     {total_pages}")
            print(f"   Workers:   {self.max_workers}")
            print(f"   Model:     {self.model}")

            # Get pages to process (auto-detects total_pages from source directory)
            if self.enable_checkpoints:
                pages_to_process = storage.correction.checkpoint.get_remaining_pages(resume=resume)
            else:
                pages_to_process = list(range(1, total_pages + 1))

            # Pre-load OCR data and prepare requests (parallelized)
            print(f"\n   Loading {len(pages_to_process)} pages...")
            load_start_time = time.time()
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
            # Generate schema from Pydantic model (single source of truth)
            response_schema = {
                "type": "json_schema",
                "json_schema": {
                    "name": "ocr_correction",
                    "strict": True,
                    "schema": CorrectionLLMResponse.model_json_schema()
                }
            }

            # System prompt is imported from prompts.py (same for all pages)
            system_prompt = SYSTEM_PROMPT

            def load_page(page_num):
                """Load and prepare a single page (called in parallel)."""
                ocr_file = storage.correction.input_page(page_num)
                page_file = storage.correction.source_image(page_num)

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
                    user_prompt = build_user_prompt(
                        page_num=page_num,
                        total_pages=total_pages,
                        book_metadata=metadata,
                        ocr_data=ocr_page.model_dump()
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
                            'storage': storage,  # Pass storage for output path
                            'ocr_page_number': ocr_page.page_number
                        }
                    )

                    return (page_num, ocr_page, request)

                except Exception as e:
                    print(f"❌ Failed to load page {page_num}: {e}", file=sys.stderr)
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

            # Finish loading progress with elapsed time
            load_elapsed = time.time() - load_start_time
            load_progress.finish(f"   ✓ {len(requests)} pages loaded in {load_elapsed:.1f}s")

            if len(requests) == 0:
                print("✅ No valid pages to process")
                return

            # Setup progress tracking
            print(f"\n   Correcting {len(requests)} pages...")
            correction_start_time = time.time()
            progress = ProgressBar(
                total=len(requests),
                prefix="   ",
                width=40,
                unit="pages"
            )
            progress.update(0, suffix="starting...")  # Show initial progress bar
            completed_count = 0
            failed_pages = []

            # Callback wrappers (bind local state to class methods)
            def on_event(event: EventData):
                self._handle_progress_event(event, progress, len(requests))

            def on_result(result: LLMResult):
                nonlocal completed_count
                completed_count += self._handle_result(result, failed_pages)

            # Process batch with new client
            results = self.batch_client.process_batch(
                requests,
                json_parser=json.loads,
                on_event=on_event,
                on_result=on_result
            )

            # Finish progress bar with elapsed time
            correction_elapsed = time.time() - correction_start_time
            progress.finish(f"   ✓ {completed_count}/{len(requests)} pages corrected in {correction_elapsed:.1f}s")
            errors = len(failed_pages)
            if errors > 0:
                print(f"   ⚠️  {errors} pages failed: {sorted(failed_pages)[:10]}" + (f" and {len(failed_pages)-10} more" if len(failed_pages) > 10 else ""))

            # Get final stats from batch client
            batch_stats = self.batch_client.get_batch_stats(total_requests=total_pages)
            completed = batch_stats.completed
            total_cost = batch_stats.total_cost_usd

            # Only mark stage complete if ALL pages succeeded
            if errors == 0:
                # Mark stage complete with cost in metadata
                if self.enable_checkpoints:
                    storage.correction.checkpoint.mark_stage_complete(metadata={
                        "model": self.model,
                        "total_cost_usd": total_cost,
                        "pages_processed": completed
                    })

                # Update metadata
                storage.update_metadata({
                    'correction_complete': True,
                    'correction_completion_date': datetime.now().isoformat(),
                    'correction_total_cost': total_cost
                })

                # Print stage exit (success)
                print(f"\n✅ Correction complete: {completed}/{total_pages} pages")
                print(f"   Total cost: ${total_cost:.2f}")
                print(f"   Avg per page: ${total_cost/completed:.3f}" if completed > 0 else "")
            else:
                # Stage incomplete - some pages failed
                failed_page_nums = sorted(failed_pages)
                print(f"\n⚠️  Correction incomplete: {completed}/{total_pages} pages succeeded")
                print(f"   Total cost: ${total_cost:.2f}")
                print(f"   Failed pages: {failed_page_nums}")
                print(f"\n   To retry failed pages:")
                print(f"   uv run python ar.py process correction {book_title} --resume")

        except Exception as e:
            # Stage-level error handler
            if self.enable_checkpoints:
                storage.correction.checkpoint.mark_stage_failed(error=str(e))
            print(f"\n❌ Correction stage failed: {e}")
            raise

    def _handle_progress_event(self, event: EventData, progress: ProgressBar, total_requests: int):
        """Handle progress event for batch processing."""
        try:
            if event.event_type == LLMEvent.PROGRESS:
                # Query batch client for current state
                active = self.batch_client.get_active_requests()
                recent = self.batch_client.get_recent_completions()

                # Update progress bar
                batch_stats = self.batch_client.get_batch_stats(total_requests=total_requests)
                rate_util = event.rate_limit_status.get('utilization', 0) if event.rate_limit_status else 0
                suffix = f"${batch_stats.total_cost_usd:.2f} | {rate_util:.0%} rate"

                # Show executing requests
                for req_id, status in active.items():
                    if status.phase == RequestPhase.EXECUTING:
                        page_id = req_id.replace('page_', 'p')
                        elapsed = status.phase_elapsed

                        if status.retry_count > 0:
                            progress.add_sub_line(req_id,
                                f"{page_id}: Executing... ({elapsed:.1f}s, retry {status.retry_count}/{self.max_retries})")
                        else:
                            progress.add_sub_line(req_id, f"{page_id}: Executing... ({elapsed:.1f}s)")

                # Show recent completions
                for req_id, comp in recent.items():
                    page_id = req_id.replace('page_', 'p')

                    if comp.success:
                        progress.add_sub_line(req_id,
                            f"{page_id}: ✓ ({comp.total_time_seconds:.1f}s, ${comp.cost_usd:.4f})")
                    else:
                        error_preview = comp.error_message[:30] if comp.error_message else 'unknown'
                        progress.add_sub_line(req_id,
                            f"{page_id}: ✗ ({comp.total_time_seconds:.1f}s) - {error_preview}")

                progress.update(event.completed, suffix=suffix)

            elif event.event_type == LLMEvent.RATE_LIMITED:
                progress.set_status(f"⏸️  Rate limited, resuming in {event.eta_seconds:.0f}s")

        except Exception as e:
            # Don't let progress bar issues crash the worker thread
            import sys, traceback
            error_msg = f"ERROR: Progress update failed: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            print(error_msg, file=sys.stderr, flush=True)
            # Don't raise - let processing continue even if progress display fails

    def _handle_result(self, result: LLMResult, failed_pages: list) -> int:
        """
        Handle LLM result - save successful pages, track failures.

        Returns:
            1 if page completed successfully, 0 otherwise
        """
        try:
            # Extract metadata with defensive error handling
            page_num = result.request.metadata['page_num']
            result_storage = result.request.metadata['storage']

            if result.success:
                try:
                    # Add metadata to correction data
                    correction_data = result.parsed_json
                    if correction_data is None:
                        raise ValueError("parsed_json is None for successful result")

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

                    # Save corrected output (handles file write + checkpoint atomically)
                    result_storage.correction.save_page(
                        page_num=page_num,
                        data=correction_data,
                        cost_usd=result.cost_usd,
                        processing_time=result.total_time_seconds
                    )

                    return 1  # Success

                except Exception as e:
                    import sys, traceback
                    failed_pages.append(page_num)
                    print(f"❌ Failed to save page {page_num} result: {traceback.format_exc()}",
                          file=sys.stderr, flush=True)
                    return 0
            else:
                # Permanent failure (already logged by LLMBatchClient)
                failed_pages.append(page_num)
                return 0

        except Exception as e:
            # Critical: Catch errors from metadata access or other outer-level failures
            import sys, traceback
            error_msg = f"CRITICAL: on_result callback failed: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            print(error_msg, file=sys.stderr, flush=True)

            # Try to extract page_num if possible and mark as failed
            try:
                if hasattr(result, 'request') and result.request and hasattr(result.request, 'metadata'):
                    page_num = result.request.metadata.get('page_num', 'unknown')
                    if page_num != 'unknown':
                        failed_pages.append(page_num)
            except:
                pass  # Give up gracefully

            return 0
