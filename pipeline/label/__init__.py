"""
Label Stage - Vision-based page number extraction and block classification.

Uses multimodal LLM to extract printed page numbers and classify content blocks.
Processes pages in parallel using ThreadPoolExecutor (I/O-bound LLM calls).
"""

import json
import time
import threading
from pathlib import Path
from datetime import datetime
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.llm.batch_client import LLMBatchClient, LLMRequest, LLMResult
from infra.utils.pdf import downsample_for_vision
from infra.pipeline.rich_progress import RichProgressBar, RichProgressBarHierarchical
from infra.config import Config

# Import from local modules
from pipeline.label.prompts import SYSTEM_PROMPT, build_user_prompt
from pipeline.label.schemas import LabelPageOutput, LabelPageMetrics, LabelPageReport, BlockType
from pipeline.ocr.schemas import OCRPageOutput


class LabelStage(BaseStage):
    """
    Label Stage - Page number extraction and block classification.

    Reads: ocr/*.json (OCR outputs) + source/*.png (page images)
    Writes: labels/*.json (page numbers and block classifications)
    """

    name = "labels"  # Output directory name
    dependencies = ["ocr"]  # Requires OCR stage complete

    # Schema definitions
    input_schema = OCRPageOutput
    output_schema = LabelPageOutput
    checkpoint_schema = LabelPageMetrics
    report_schema = LabelPageReport  # Quality-focused report

    def __init__(self, model: str = None, max_workers: int = None, max_retries: int = 3, auto_analyze: bool = False):
        """
        Initialize Label stage.

        Args:
            model: LLM model to use (default: from Config.vision_model_primary)
            max_workers: Number of parallel workers (default: Config.max_workers)
            max_retries: Maximum retry attempts for failed pages (default: 3)
            auto_analyze: Automatically run analysis agent after stage completion (default: False)
        """
        self.model = model or Config.vision_model_primary
        self.max_workers = max_workers if max_workers is not None else Config.max_workers
        self.max_retries = max_retries
        self.auto_analyze = auto_analyze
        self.progress_lock = threading.Lock()
        self.batch_client = None  # Will be initialized in run()

    def before(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger):
        """Validate OCR outputs and source images exist 1-1."""
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
            f"Validated {len(source_pages)} pages ready for labeling",
            model=self.model,
            max_workers=self.max_workers
        )

    def run(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger) -> Dict[str, Any]:
        """Process pages with vision-based page number extraction and block classification."""
        # Get total pages from metadata
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        logger.start_stage(total_pages=total_pages, max_workers=self.max_workers)
        logger.info(f"Label Stage - Page number extraction and block classification with {self.model}")

        # Initialize batch LLM client with stage-specific log directory
        stage_log_dir = storage.stage(self.name).output_dir / "logs"
        self.batch_client = LLMBatchClient(
            max_workers=self.max_workers,
            # rate_limit uses Config.rate_limit_requests_per_minute by default
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

            Constrains block count to match OCR exactly.
            No paragraph-level data needed - we only classify blocks.
            """
            import copy

            base_schema = LabelPageOutput.model_json_schema()
            schema = copy.deepcopy(base_schema)

            # Constrain top-level blocks array to exact count from OCR
            num_blocks = len(ocr_page.blocks)
            schema['properties']['blocks']['minItems'] = num_blocks
            schema['properties']['blocks']['maxItems'] = num_blocks

            # Return constrained schema
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": "page_labeling",
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

                # Extract text from OCR for prompt
                ocr_text = ocr_page.get_all_text()

                # Load and downsample image
                page_image = Image.open(page_file)
                page_image = downsample_for_vision(page_image)

                # Build page-specific prompt
                user_prompt = build_user_prompt(
                    ocr_page=ocr_page.model_dump(),
                    ocr_text=ocr_text,
                    current_page=page_num,
                    total_pages=total_pages,
                    book_metadata=metadata
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

        # Setup progress tracking for labeling
        logger.info(f"Labeling {len(requests)} pages...")
        label_start_time = time.time()
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
            start_time=label_start_time,
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
                        # Add metadata to label data
                        label_data = result.parsed_json
                        if label_data is None:
                            raise ValueError("parsed_json is None for successful result")

                        # Add page-specific metadata
                        label_data['page_number'] = ocr_page.page_number
                        label_data['model_used'] = self.model
                        label_data['processing_cost'] = result.cost_usd
                        label_data['timestamp'] = datetime.now().isoformat()

                        # Calculate summary stats
                        avg_class_conf = sum(
                            b.get('classification_confidence', 0)
                            for b in label_data.get('blocks', [])
                        ) / len(label_data.get('blocks', [])) if label_data.get('blocks') else 0

                        label_data['total_blocks'] = len(label_data.get('blocks', []))
                        label_data['avg_classification_confidence'] = round(avg_class_conf, 3)

                        # Validate with schema
                        validated = LabelPageOutput(**label_data)

                        # Extract chapter/section heading info for build-structure stage
                        # Note: We can't get text here because merged stage runs AFTER labels
                        # Build-structure will load merged pages to get actual chapter text
                        has_chapter_heading = False
                        has_section_heading = False
                        chapter_heading_text = None  # Not available until merged stage

                        for block_class in validated.blocks:
                            if block_class.classification == BlockType.CHAPTER_HEADING:
                                has_chapter_heading = True
                            elif block_class.classification == BlockType.SECTION_HEADING:
                                has_section_heading = True

                        # Validate metrics against schema
                        from pipeline.label.schemas import LabelPageMetrics
                        metrics = LabelPageMetrics(
                            page_num=page_num,
                            processing_time_seconds=result.total_time_seconds,
                            cost_usd=result.cost_usd,
                            attempts=result.attempts,
                            tokens_total=result.tokens_received,
                            tokens_per_second=result.tokens_per_second,
                            model_used=result.model_used,
                            provider=result.provider,
                            queue_time_seconds=result.queue_time_seconds,
                            execution_time_seconds=result.execution_time_seconds,
                            total_time_seconds=result.total_time_seconds,
                            ttft_seconds=result.ttft_seconds,
                            usage=result.usage,
                            # Label-specific metrics
                            total_blocks_classified=label_data['total_blocks'],
                            avg_classification_confidence=label_data['avg_classification_confidence'],
                            page_number_extracted=label_data.get('printed_page_number') is not None,
                            page_region_classified=label_data.get('page_region') is not None,
                            # Book structure fields (for report)
                            printed_page_number=label_data.get('printed_page_number'),
                            numbering_style=label_data.get('numbering_style'),
                            page_region=label_data.get('page_region'),
                            # Chapter/section structure (for build-structure stage)
                            has_chapter_heading=has_chapter_heading,
                            has_section_heading=has_section_heading,
                            chapter_heading_text=chapter_heading_text,
                        )

                        # Save page output with validated metrics (save_page will call checkpoint.mark_completed)
                        storage.stage(self.name).save_page(
                            page_num=page_num,
                            data=validated.model_dump(),
                            schema=LabelPageOutput,
                            cost_usd=result.cost_usd,
                            metrics=metrics.model_dump()
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
        label_elapsed = time.time() - label_start_time
        batch_stats = self.batch_client.get_batch_stats(total_requests=len(requests))
        progress.finish(f"   ✓ {batch_stats.completed}/{len(requests)} pages labeled in {label_elapsed:.1f}s")

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

    def generate_report(self, storage: BookStorage, logger: Optional[PipelineLogger] = None) -> Optional[Path]:
        """Generate report from labels page files (source of truth)."""
        import csv

        stage_storage = storage.stage(self.name)
        page_files = sorted(stage_storage.list_output_pages())

        if not page_files:
            if logger:
                logger.info("No pages to report")
            return None

        # Extract report data from each page file
        report_rows = []
        for page_file in page_files:
            page_num = int(page_file.stem.split('_')[1])

            try:
                # Load page data (returns dict, validated against schema)
                page_dict = stage_storage.load_page(page_num, schema=LabelPageOutput)

                # Extract chapter/section heading info
                blocks = page_dict.get('blocks', [])
                has_chapter_heading = any(
                    b.get('classification') == 'CHAPTER_HEADING'
                    for b in blocks
                )
                has_section_heading = any(
                    b.get('classification') == 'SECTION_HEADING'
                    for b in blocks
                )

                # Build report row (matching LabelPageReport schema)
                report_row = LabelPageReport(
                    page_num=page_num,
                    printed_page_number=page_dict.get('printed_page_number'),
                    numbering_style=page_dict.get('numbering_style'),
                    page_region=page_dict.get('page_region'),
                    page_number_extracted=page_dict.get('printed_page_number') is not None,
                    page_region_classified=page_dict.get('page_region') is not None,
                    total_blocks_classified=page_dict.get('total_blocks', 0),
                    avg_classification_confidence=page_dict.get('avg_classification_confidence', 0.0),
                    has_chapter_heading=has_chapter_heading,
                    has_section_heading=has_section_heading,
                    chapter_heading_text=None,  # Not available in labels stage
                )

                report_rows.append(report_row.model_dump())

            except Exception as e:
                if logger:
                    logger.error(f"Failed to process page {page_num} for report", error=str(e))
                continue

        if not report_rows:
            return None

        # Write CSV
        report_path = stage_storage.output_dir / "report.csv"

        try:
            with open(report_path, 'w', newline='') as f:
                fieldnames = list(report_rows[0].keys())
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(report_rows)

            if logger:
                logger.info(f"Generated report: {report_path}")

            return report_path

        except Exception as e:
            if logger:
                logger.error(f"Failed to write report: {e}")
            return None

    def after(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger, stats: Dict[str, Any]):
        """Generate label quality report from page files."""
        # Generate report from page files (source of truth)
        self.generate_report(storage, logger)

        # Auto-run analysis if enabled
        if self.auto_analyze:
            # Check if analysis already exists
            existing_analysis = checkpoint._state.get('metadata', {}).get('analysis')
            if existing_analysis and existing_analysis.get('report_path'):
                from pathlib import Path
                report_path = Path(existing_analysis['report_path'])
                if report_path.exists():
                    logger.info(
                        f"Analysis already exists",
                        report=str(report_path),
                        cost_usd=existing_analysis.get('cost_usd', 0)
                    )
                    return

            logger.info("Running automatic stage analysis...")
            try:
                result = self.analyze(storage=storage)

                # Add analysis cost to checkpoint metadata
                with checkpoint._lock:
                    if 'analysis' not in checkpoint._state['metadata']:
                        checkpoint._state['metadata']['analysis'] = {}

                    checkpoint._state['metadata']['analysis'] = {
                        'cost_usd': result['cost_usd'],
                        'iterations': result['iterations'],
                        'model': result['model'],
                        'run_hash': result['run_hash'],
                        'report_path': str(result['analysis_path'])
                    }
                    checkpoint._save_checkpoint()

                logger.info(
                    f"Analysis complete",
                    report=str(result['analysis_path']),
                    cost_usd=result['cost_usd'],
                    iterations=result['iterations']
                )
            except Exception as e:
                logger.error(f"Analysis failed", error=str(e))

    @staticmethod
    def analyze(storage: BookStorage, model: str = None, focus_areas: list = None) -> Dict[str, Any]:
        """
        Launch analysis agent for Label stage.

        Analyzes the label stage report and outputs to identify:
        - Page numbering issues (gaps, style changes, missing numbers)
        - Region classification quality (unexpected transitions, low confidence)
        - Block classification issues (misclassified content types)
        - Patterns in failures (systematic vs. isolated)

        Args:
            storage: BookStorage instance for the book
            model: OpenRouter model to use (default: Config.text_model_primary)
            focus_areas: Optional list of specific areas to focus on
                        (e.g., ['page_numbers', 'regions'])

        Returns:
            Dict with analysis_path, cost_usd, iterations, model

        Example:
            storage = BookStorage('modest-lovelace')
            result = LabelStage.analyze(storage)
            print(f"Analysis: {result['analysis_path']}")
            print(f"Cost: ${result['cost_usd']:.4f}")
        """
        from infra.agents.stage_analyzer import StageAnalyzer

        analyzer = StageAnalyzer(
            storage=storage,
            stage_name='labels',
            model=model
        )

        return analyzer.analyze(focus_areas=focus_areas)
