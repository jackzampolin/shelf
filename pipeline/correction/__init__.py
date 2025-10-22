"""
Correction Stage - Vision-based OCR error correction.

Uses multimodal LLM to correct OCR errors by comparing text against page images.
Processes pages in parallel using ThreadPoolExecutor (I/O-bound LLM calls).
"""

import json
import time
import threading
from pathlib import Path
from datetime import datetime
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_client import LLMBatchClient, LLMRequest, LLMResult
from infra.utils.pdf import downsample_for_vision
from infra.pipeline.rich_progress import RichProgressBar, RichProgressBarHierarchical
from infra.config import Config

# Import from local modules
from pipeline.correction.prompts import SYSTEM_PROMPT, build_user_prompt
from pipeline.correction.schemas import CorrectionLLMResponse, CorrectionPageOutput
from pipeline.correction.report import analyze_book
from pipeline.ocr.schemas import OCRPageOutput


class CorrectionStage(BaseStage):
    """
    Correction Stage - Vision-based OCR error correction.

    Reads: ocr/*.json (OCR outputs) + source/*.png (page images)
    Writes: corrected/*.json (corrections with confidence scores)
    """

    name = "corrected"  # Output directory name
    dependencies = ["ocr"]  # Requires OCR stage complete

    def __init__(self, model: str = None, max_workers: int = 30, max_retries: int = 3):
        """
        Initialize Correction stage.

        Args:
            model: LLM model to use (default: from Config.VISION_MODEL)
            max_workers: Number of parallel workers (default: 30)
            max_retries: Maximum retry attempts for failed pages (default: 3)
        """
        self.model = model or Config.VISION_MODEL
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.progress_lock = threading.Lock()
        self.batch_client = None  # Will be initialized in run()

    def before(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger):
        """Validate OCR outputs exist 1-1 with source pages."""
        # Get source pages
        source_stage = storage.stage('source')
        source_pages = source_stage.list_output_pages(extension='png')

        if not source_pages:
            raise FileNotFoundError(
                f"No source pages found in {source_stage.output_dir}. "
                f"Run OCR stage first."
            )

        # Get OCR outputs
        ocr_stage = storage.stage('ocr')
        ocr_pages = ocr_stage.list_output_pages(extension='json')

        if not ocr_pages:
            raise FileNotFoundError(
                f"No OCR outputs found in {ocr_stage.output_dir}. "
                f"Run OCR stage first."
            )

        # Verify 1-1 correspondence
        source_nums = set(int(p.stem.split('_')[1]) for p in source_pages)
        ocr_nums = set(int(p.stem.split('_')[1]) for p in ocr_pages)

        if source_nums != ocr_nums:
            missing_in_ocr = source_nums - ocr_nums
            missing_in_source = ocr_nums - source_nums

            error_parts = []
            if missing_in_ocr:
                error_parts.append(f"Missing OCR for pages: {sorted(list(missing_in_ocr))[:10]}")
            if missing_in_source:
                error_parts.append(f"Missing source images for pages: {sorted(list(missing_in_source))[:10]}")

            raise FileNotFoundError(
                f"OCR outputs and source pages don't match 1-1. {' '.join(error_parts)}"
            )

        logger.info(
            f"Validated {len(source_pages)} pages ready for correction",
            model=self.model,
            max_workers=self.max_workers
        )

    def run(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger) -> Dict[str, Any]:
        """Process pages with vision-based OCR correction."""
        # Get total pages from metadata
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        logger.start_stage(total_pages=total_pages, max_workers=self.max_workers)
        logger.info(f"Correction Stage - Vision-based error correction with {self.model}")

        # Initialize batch LLM client with stage-specific log directory
        stage_log_dir = storage.stage(self.name).output_dir / "logs"
        self.batch_client = LLMBatchClient(
            max_workers=self.max_workers,
            rate_limit=150,  # OpenRouter default
            max_retries=self.max_retries,
            retry_jitter=(1.0, 3.0),
            verbose=True,  # Enable per-request events
            log_dir=stage_log_dir,
            log_timestamp=logger.log_file.stem.split('_', 1)[1] if hasattr(logger, 'log_file') else None
        )

        # Get pages to process
        pages = checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)

        if not pages:
            logger.info("No pages to process (all complete)")
            return checkpoint.get_status().get('metadata', {})

        logger.info(f"Processing {len(pages)} pages with {self.max_workers} workers")

        # Note: Response schema is now generated PER-PAGE based on OCR structure
        # See build_page_specific_schema() below

        # Pre-load OCR data and prepare requests (parallelized)
        logger.info(f"Loading {len(pages)} pages...")
        load_start_time = time.time()
        load_progress = RichProgressBar(
            total=len(pages),
            prefix="   ",
            width=40,
            unit="pages"
        )
        load_progress.update(0, suffix="loading...")

        requests = []
        page_data_map = {}  # Store loaded data for saving later
        completed_loads = 0
        load_lock = threading.Lock()

        def build_page_specific_schema(ocr_page: OCRPageOutput) -> dict:
            """
            Generate JSON schema tailored to THIS page's OCR structure.

            Constrains block count and paragraph count per block to match OCR exactly.
            This prevents the LLM from adding/removing blocks or paragraphs.
            """
            import copy

            base_schema = CorrectionLLMResponse.model_json_schema()
            schema = copy.deepcopy(base_schema)

            # Constrain top-level blocks array to exact count from OCR
            num_blocks = len(ocr_page.blocks)
            schema['properties']['blocks']['minItems'] = num_blocks
            schema['properties']['blocks']['maxItems'] = num_blocks

            # Use prefixItems to constrain paragraph count for each block
            block_items = []
            for block in ocr_page.blocks:
                para_count = len(block.paragraphs)

                # Get the BlockCorrection schema from $defs
                block_schema = copy.deepcopy(schema['$defs']['BlockCorrection'])

                # Constrain this specific block's paragraph array
                block_schema['properties']['paragraphs']['minItems'] = para_count
                block_schema['properties']['paragraphs']['maxItems'] = para_count

                block_items.append(block_schema)

            # Replace items with prefixItems for tuple validation
            schema['properties']['blocks']['prefixItems'] = block_items
            # items: false means no additional items beyond prefixItems
            schema['properties']['blocks']['items'] = False

            return {
                "type": "json_schema",
                "json_schema": {
                    "name": "ocr_correction",
                    "strict": True,
                    "schema": schema
                }
            }

        def load_page(page_num):
            """Load and prepare a single page (called in parallel)."""
            # Load OCR data
            ocr_stage = storage.stage('ocr')
            ocr_file = ocr_stage.output_page(page_num, extension='json')

            # Load source image
            source_stage = storage.stage('source')
            page_file = source_stage.output_page(page_num, extension='png')

            if not ocr_file.exists() or not page_file.exists():
                return None

            try:
                # Load OCR data
                with open(ocr_file, 'r') as f:
                    ocr_data = json.load(f)
                ocr_page = OCRPageOutput(**ocr_data)

                # Generate page-specific schema
                response_schema = build_page_specific_schema(ocr_page)

                # Load and downsample image
                page_image = Image.open(page_file)
                page_image = downsample_for_vision(page_image)

                # Build page-specific prompt
                user_prompt = build_user_prompt(
                    page_num=page_num,
                    total_pages=total_pages,
                    book_metadata=metadata,
                    ocr_data=ocr_page.model_dump()
                )

                # Create LLM request (multimodal) with page-specific schema
                request = LLMRequest(
                    id=f"page_{page_num:04d}",
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    images=[page_image],  # Vision input
                    response_format=response_schema,  # Now page-specific!
                    metadata={
                        'page_num': page_num,
                        'storage': storage,
                        'ocr_page': ocr_page
                    }
                )

                return (page_num, ocr_page, request)

            except Exception as e:
                logger.error(f"Failed to load page {page_num}", error=str(e))
                return None

        # Load pages in parallel with ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_page = {
                executor.submit(load_page, page_num): page_num
                for page_num in pages
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
        load_elapsed = time.time() - load_start_time
        load_progress.finish(f"   ✓ {len(requests)} pages loaded in {load_elapsed:.1f}s")

        if len(requests) == 0:
            logger.info("No valid pages to process")
            return {'pages_processed': 0, 'pages_failed': 0, 'total_cost_usd': 0.0}

        # Setup progress tracking for correction
        logger.info(f"Correcting {len(requests)} pages...")
        correction_start_time = time.time()
        progress = RichProgressBarHierarchical(
            total=len(requests),
            prefix="   ",
            width=40,
            unit="pages"
        )
        progress.update(0, suffix="starting...")

        failed_pages = []

        # Create event handler
        on_event = progress.create_llm_event_handler(
            batch_client=self.batch_client,
            start_time=correction_start_time,
            model=self.model,
            total_requests=len(requests),
            checkpoint=checkpoint
        )

        def on_result(result: LLMResult):
            """Handle LLM result - save successful pages, track failures."""
            try:
                page_num = result.request.metadata['page_num']
                ocr_page = result.request.metadata['ocr_page']

                if result.success:
                    try:
                        # Add metadata to correction data
                        correction_data = result.parsed_json
                        if correction_data is None:
                            raise ValueError("parsed_json is None for successful result")

                        # Build full page output with metadata
                        page_output = {
                            'page_number': page_num,
                            'blocks': correction_data['blocks'],
                            'model_used': self.model,
                            'processing_cost': result.cost_usd,
                            'timestamp': datetime.now().isoformat(),
                            'total_blocks': len(correction_data['blocks']),
                            'total_corrections': sum(
                                1 for block in correction_data['blocks']
                                for para in block['paragraphs']
                                if para.get('text') is not None
                            ),
                            'avg_confidence': sum(
                                para['confidence']
                                for block in correction_data['blocks']
                                for para in block['paragraphs']
                            ) / max(1, sum(
                                len(block['paragraphs'])
                                for block in correction_data['blocks']
                            ))
                        }

                        # Validate with schema
                        validated = CorrectionPageOutput(**page_output)

                        # Save page output with rich metrics (save_page will call checkpoint.mark_completed)
                        storage.stage(self.name).save_page(
                            page_num=page_num,
                            data=validated.model_dump(),
                            schema=CorrectionPageOutput,
                            cost_usd=result.cost_usd,
                            metrics={
                                "page_num": page_num,
                                "cost_usd": result.cost_usd,
                                "attempts": result.attempts,
                                "total_time_seconds": result.total_time_seconds,
                                "queue_time_seconds": result.queue_time_seconds,
                                "execution_time_seconds": result.execution_time_seconds,
                                "ttft_seconds": result.ttft_seconds,
                                "tokens_total": result.tokens_received,
                                "tokens_per_second": result.tokens_per_second,
                                "model_used": result.model_used,
                                "provider": result.provider,
                                "usage": result.usage
                            }
                        )

                    except Exception as e:
                        logger.error(f"Failed to save page {page_num}", error=str(e))
                        failed_pages.append(page_num)
                else:
                    # LLM call failed
                    logger.error(f"Page {page_num} failed", error=result.error)
                    failed_pages.append(page_num)

            except Exception as e:
                logger.error(f"Error handling result", error=str(e))

        # Process batch with streaming and structured responses
        results = self.batch_client.process_batch(
            requests,
            on_event=on_event,
            on_result=on_result
        )

        # Finish progress
        correction_elapsed = time.time() - correction_start_time
        batch_stats = self.batch_client.get_batch_stats(total_requests=len(requests))
        progress.finish(f"   ✓ {batch_stats.completed}/{len(requests)} pages corrected in {correction_elapsed:.1f}s")

        # Get final stats
        final_stats = self.batch_client.get_batch_stats(total_requests=total_pages)
        completed = final_stats.completed
        total_cost = final_stats.total_cost_usd
        errors = len(failed_pages)

        if errors > 0:
            logger.warning(f"{errors} pages failed: {sorted(failed_pages)[:10]}")

        # Return stats
        return {
            'pages_processed': completed,
            'pages_failed': errors,
            'total_cost_usd': total_cost
        }

    def after(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger, stats: Dict[str, Any]):
        """Generate correction quality report."""
        logger.info("Generating correction quality report...")

        # Write correction report to corrected/report.txt
        analyze_book(
            scan_id=storage.scan_id,
            storage_root=storage.storage_root,
            silent=True,  # No terminal output
            write_report=True  # Write report.txt file
        )

        logger.info("Correction report complete")
