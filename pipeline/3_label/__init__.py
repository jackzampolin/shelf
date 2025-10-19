#!/usr/bin/env python3
"""
Vision-Based Page Labeling

Extracts page numbers and classifies content blocks using multimodal LLM.
Text correction is handled in Stage 2 (Correct).
"""

import json
import sys
import time
import os
from pathlib import Path
from datetime import datetime
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from infra.config import Config
from infra.pipeline.logger import create_logger
from infra.llm.batch_client import LLMBatchClient
from infra.llm.models import LLMRequest, LLMResult, EventData, LLMEvent, RequestPhase
from infra.utils.pdf import downsample_for_vision
from infra.pipeline.rich_progress import RichProgressBar, RichProgressBarHierarchical
from infra.storage.book_storage import BookStorage

# Import schemas
import importlib
ocr_schemas = importlib.import_module('pipeline.1_ocr.schemas')
OCRPageOutput = ocr_schemas.OCRPageOutput

label_schemas = importlib.import_module('pipeline.3_label.schemas')
LabelPageOutput = label_schemas.LabelPageOutput
BlockClassification = label_schemas.BlockClassification
ParagraphLabel = label_schemas.ParagraphLabel

# Import prompts
label_prompts = importlib.import_module('pipeline.3_label.prompts')
SYSTEM_PROMPT = label_prompts.SYSTEM_PROMPT
build_user_prompt = label_prompts.build_user_prompt
get_default_region = label_prompts.get_default_region


def extract_metrics_from_result(result: LLMResult) -> dict:
    """
    Extract detailed metrics from LLMResult for checkpoint storage.

    Converts LLMResult telemetry into checkpoint-compatible metrics format.
    Handles both streaming and non-streaming requests.

    Args:
        result: LLMResult from LLM batch client

    Returns:
        Metrics dict with fields:
        - ttft_seconds (float or None): Time to first token
        - execution_time_seconds (float): LLM execution time
        - total_time_seconds (float): Total time including queue
        - tokens_input (int): Prompt tokens
        - tokens_output (int): Completion tokens
        - tokens_total (int): Total tokens
        - cost_usd (float): Request cost
        - model_used (str): Actual model used
        - attempts (int): Retry attempts
        - timestamp (str): ISO timestamp
        - streaming_duration (float, optional): Execution time - TTFT
        - tokens_per_second (float, optional): Token generation rate
    """
    # Extract token counts from usage dict
    usage = result.usage or {}
    tokens_input = usage.get('prompt_tokens', 0)
    tokens_output = usage.get('completion_tokens', 0)

    # Build base metrics
    metrics = {
        # Timing (all requests)
        'ttft_seconds': result.ttft_seconds,  # None for non-streaming
        'execution_time_seconds': result.execution_time_seconds,
        'total_time_seconds': result.total_time_seconds,

        # Tokens
        'tokens_input': tokens_input,
        'tokens_output': tokens_output,
        'tokens_total': tokens_input + tokens_output,

        # Cost & Model
        'cost_usd': result.cost_usd,
        'model_used': result.model_used or result.request.model,
        'attempts': result.attempts,

        # Timestamp
        'timestamp': datetime.now().isoformat(),
    }

    # Add streaming-specific metrics if available
    if result.ttft_seconds is not None and result.execution_time_seconds > 0:
        metrics['streaming_duration'] = result.execution_time_seconds - result.ttft_seconds

    if result.tokens_per_second and result.tokens_per_second > 0:
        metrics['tokens_per_second'] = round(result.tokens_per_second, 2)

    return metrics


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
        self.logger = None  # Will be initialized per book
        self.enable_checkpoints = enable_checkpoints
        self.batch_client = None  # Will be initialized per book

    def process_book(self, book_title, resume=False):
        """
        Process all pages for page number extraction and block classification.

        Args:
            book_title: Scan ID of the book to process
            resume: If True, resume from checkpoint (default: False)
        """
        # Initialize storage manager
        try:
            storage = BookStorage(scan_id=book_title, storage_root=self.storage_root)
            storage.label.validate_inputs()  # Validates OCR outputs exist
        except FileNotFoundError as e:
            print(f"❌ {e}")
            return

        # Load metadata
        metadata = storage.load_metadata()
        book_dir = storage.book_dir

        # Initialize logger (file only, no console spam)
        logs_dir = storage.logs_dir
        logs_dir.mkdir(exist_ok=True)
        self.logger = create_logger(book_title, "label", log_dir=logs_dir, console_output=False)

        # Use checkpoint property from storage
        if self.enable_checkpoints:
            checkpoint = storage.label.checkpoint
            if not resume:
                if not checkpoint.reset(confirm=True):
                    print("   Use --resume to continue from checkpoint.")
                    return

        # Initialize batch LLM client with failure logging
        self.batch_client = LLMBatchClient(
            max_workers=self.max_workers,
            rate_limit=150,
            max_retries=self.max_retries,
            retry_jitter=(1.0, 3.0),
            json_retry_budget=2,
            verbose=True,
            progress_interval=1.0,  # Increased to reduce PROGRESS event frequency
            log_dir=storage.label.get_log_dir()
        )

        self.logger.info(f"Processing book: {metadata.get('title', book_title)}", resume=resume, model=self.model)

        try:
            # Get pages to process (checkpoint auto-detects total_pages from source directory)
            if self.enable_checkpoints:
                pages_to_process = storage.label.checkpoint.get_remaining_pages(resume=resume)
                total_pages = storage.label.checkpoint._state['total_pages']
            else:
                # Non-checkpoint mode: count pages manually
                total_pages = len(storage.ocr.list_output_pages())
                pages_to_process = list(range(1, total_pages + 1))

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

            if len(pages_to_process) == 0:
                self.logger.info("All pages already labeled, skipping")
                print("✅ All pages already labeled")
                return

            # Pre-load OCR data and prepare requests (parallelized)
            print(f"\n   Loading {len(pages_to_process)} pages...")
            load_start_time = time.time()
            load_progress = RichProgressBar(total=len(pages_to_process), prefix="   ", width=40, unit="pages")
            load_progress.update(0, suffix="loading...")

            requests = []
            page_data_map = {}
            completed_loads = 0
            load_lock = threading.Lock()

            # Build JSON schema once (shared across all requests)
            response_schema = {
                "type": "json_schema",
                "json_schema": {
                    "name": "page_labeling",
                    "strict": True,
                    "schema": LabelPageOutput.model_json_schema()
                }
            }

            def load_page(page_num):
                """Load and prepare a single page (called in parallel)."""
                ocr_file = storage.ocr.output_dir / f"page_{page_num:04d}.json"
                page_file = storage.source.output_dir / f"page_{page_num:04d}.png"

                try:
                    # Load OCR data
                    with open(ocr_file, 'r') as f:
                        ocr_data = json.load(f)
                    ocr_page = OCRPageOutput(**ocr_data)

                    # Load and downsample image
                    page_image = Image.open(page_file)
                    page_image = downsample_for_vision(page_image)

                    # Build page-specific prompt with book context
                    ocr_text = json.dumps(ocr_page.model_dump(), indent=2)
                    user_prompt = build_user_prompt(
                        ocr_page=ocr_page,
                        ocr_text=ocr_text,
                        current_page=page_num,
                        total_pages=total_pages,
                        book_metadata=metadata
                    )

                    # Create LLM request
                    request = LLMRequest(
                        id=f"page_{page_num:04d}",
                        model=self.model,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        temperature=0.1,
                        timeout=180,
                        images=[page_image],
                        response_format=response_schema,
                        fallback_models=Config.FALLBACK_MODELS if Config.FALLBACK_MODELS else None,
                        metadata={
                            'page_num': page_num,
                            'ocr_page_number': ocr_page.page_number,
                            'ocr_tokens': len(ocr_text) // 3  # Estimate for ETA calculation
                        }
                    )

                    return (page_num, ocr_page, request)

                except Exception as e:
                    print(f"❌ Failed to load page {page_num}: {e}", file=sys.stderr)
                    return None

            # Parallel loading
            load_workers = os.cpu_count() or 4

            with ThreadPoolExecutor(max_workers=load_workers) as executor:
                future_to_page = {
                    executor.submit(load_page, page_num): page_num
                    for page_num in pages_to_process
                }

                for future in as_completed(future_to_page):
                    result = future.result()
                    if result:
                        page_num, ocr_page, request = result
                        requests.append(request)
                        page_data_map[page_num] = {'ocr_page': ocr_page, 'request': request}

                    with load_lock:
                        completed_loads += 1
                        load_progress.update(completed_loads, suffix=f"{len(requests)} loaded")

            load_elapsed = time.time() - load_start_time
            load_progress.finish(f"   ✓ {len(requests)} pages loaded in {load_elapsed:.1f}s")

            if len(requests) == 0:
                print("✅ No valid pages to process")
                return

            # Setup progress tracking
            print(f"\n   Labeling {len(requests)} pages...")
            label_start_time = time.time()
            progress = RichProgressBarHierarchical(total=len(requests), prefix="   ", width=40, unit="pages")
            progress.update(0, suffix="starting...")
            failed_pages = []

            # Create event handler using progress bar's built-in factory
            on_event = progress.create_llm_event_handler(
                batch_client=self.batch_client,
                start_time=label_start_time,
                model=self.model,
                total_requests=len(requests)
            )

            def on_result(result: LLMResult):
                self._handle_result(result, failed_pages, storage)

            # Process batch with callbacks
            # Note: json_parser removed - structured outputs guarantee valid JSON
            results = self.batch_client.process_batch(
                requests,
                json_parser=json.loads,
                on_event=on_event,
                on_result=on_result
            )

            # Finish progress bar
            label_elapsed = time.time() - label_start_time
            batch_stats = self.batch_client.get_batch_stats(total_requests=len(requests))
            progress.finish(f"   ✓ {batch_stats.completed}/{len(requests)} pages labeled in {label_elapsed:.1f}s")

            errors = len(failed_pages)
            if errors > 0:
                print(f"   ⚠️  {errors} pages failed: {sorted(failed_pages)[:10]}" +
                      (f" and {len(failed_pages)-10} more" if len(failed_pages) > 10 else ""))

            # Get final stats from batch client (single source of truth)
            final_stats = self.batch_client.get_batch_stats(total_requests=len(requests))
            completed = final_stats.completed
            total_cost = final_stats.total_cost_usd

            # Only mark stage complete if ALL pages succeeded
            if errors == 0:
                # Mark stage complete with cost in metadata
                if self.enable_checkpoints:
                    checkpoint.mark_stage_complete(metadata={
                        "model": self.model,
                        "total_cost_usd": total_cost,
                        "pages_processed": completed
                    })

                # Update metadata
                storage.update_metadata({
                    'labels_complete': True,
                    'labels_completion_date': datetime.now().isoformat(),
                    'labels_total_cost': total_cost
                })

                # Log completion to file (not stdout)
                self.logger.info(
                    "Labeling complete",
                    pages_labeled=completed,
                    total_cost=total_cost,
                    avg_cost_per_page=total_cost / completed if completed > 0 else 0,
                    labels_dir=str(storage.label.output_dir)
                )

                # Print stage exit (success)
                print(f"\n✅ Label complete: {completed}/{total_pages} pages")
                print(f"   Total cost: ${total_cost:.2f}")
                print(f"   Avg per page: ${total_cost/completed:.3f}" if completed > 0 else "")
            else:
                # Stage incomplete - some pages failed
                failed_page_nums = sorted(failed_pages)
                print(f"\n⚠️  Label incomplete: {completed}/{total_pages} pages succeeded")
                print(f"   Total cost: ${total_cost:.2f}")
                print(f"   Failed pages: {failed_page_nums}")
                print(f"\n   To retry failed pages:")
                print(f"   uv run python ar.py process label {book_title} --resume")

        except Exception as e:
            # Stage-level error handler
            if self.logger:
                self.logger.error(f"Labeling stage failed", error=str(e))
            if self.enable_checkpoints:
                checkpoint.mark_stage_failed(error=str(e))
            print(f"\n❌ Labeling stage failed: {e}")
            raise
        finally:
            # Always clean up logger
            if self.logger:
                self.logger.close()

    def _handle_result(self, result: LLMResult, failed_pages: list, storage: BookStorage) -> int:
        """Handle LLM result - save successful pages, track failures."""
        try:
            page_num = result.request.metadata['page_num']

            if result.success:
                try:
                    # Add metadata to label data
                    label_data = result.parsed_json
                    if label_data is None:
                        raise ValueError("parsed_json is None for successful result")

                    label_data['page_number'] = result.request.metadata['ocr_page_number']
                    label_data['model_used'] = self.model
                    label_data['processing_cost'] = result.cost_usd
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

                    # Validate output against schema
                    validated = LabelPageOutput(**label_data)
                    label_data = validated.model_dump()

                    # Extract detailed metrics from LLM result
                    metrics = extract_metrics_from_result(result)

                    # Save using storage API (atomic write and checkpoint handled internally)
                    storage.label.save_page(
                        page_num=page_num,
                        data=label_data,
                        cost_usd=result.cost_usd,
                        processing_time=result.total_time_seconds,
                        metrics=metrics
                    )

                    return 1  # Success

                except Exception as e:
                    import traceback
                    failed_pages.append(page_num)
                    print(f"❌ Failed to save page {page_num} result: {traceback.format_exc()}",
                          file=sys.stderr, flush=True)
                    return 0
            else:
                # Permanent failure (already logged by LLMBatchClient)
                failed_pages.append(page_num)
                return 0

        except Exception as e:
            # Critical: Catch errors from metadata access
            import traceback
            error_msg = f"CRITICAL: on_result callback failed: {type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            print(error_msg, file=sys.stderr, flush=True)

            try:
                if hasattr(result, 'request') and result.request and hasattr(result.request, 'metadata'):
                    page_num = result.request.metadata.get('page_num', 'unknown')
                    if page_num != 'unknown':
                        failed_pages.append(page_num)
            except:
                pass

            return 0

    def clean_stage(self, scan_id: str, confirm: bool = False) -> bool:
        """
        Clean/delete all label stage outputs, checkpoint, and logs.

        Args:
            scan_id: Scan identifier
            confirm: If False, prompts for confirmation before deleting

        Returns:
            True if cleaned, False if cancelled
        """
        from infra.storage.book_storage import BookStorage

        storage = BookStorage(scan_id=scan_id, storage_root=self.storage_root)
        return storage.label.clean_stage(confirm=confirm)
