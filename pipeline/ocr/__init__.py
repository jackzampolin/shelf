"""
OCR Stage - Extracts text and images from page images.

Uses Tesseract for hierarchical text extraction and OpenCV for image detection.
Processes pages in parallel using ProcessPoolExecutor (CPU-bound).
"""

import json
import csv
import io
import time
from pathlib import Path
from datetime import datetime
from PIL import Image
import cv2
import numpy as np
import pytesseract
from concurrent.futures import ProcessPoolExecutor, as_completed
import threading
import multiprocessing
from typing import Dict, Any, Tuple

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

# Import from local modules
from pipeline.ocr.schemas import OCRPageOutput, OCRPageMetrics, OCRPageReport
from pipeline.ocr.parsers import (
    parse_tesseract_hierarchy,
    parse_hocr_typography,
    merge_typography_into_blocks
)
from pipeline.ocr.image_detection import validate_image_candidates, ImageDetector
from pipeline.ocr.psm_worker import process_page_psm_worker


class OCRStage(BaseStage):
    """
    OCR Stage - First pipeline stage.

    Reads: source/*.png (page images from ingest process)
    Writes: ocr_psm3/, ocr_psm4/, ocr_psm6/ (multi-PSM outputs)
    Also creates: images/ (extracted image regions)
    """

    name = "ocr"
    dependencies = []  # First stage, no dependencies

    # Schema definitions
    input_schema = None  # No input (reads raw images)
    output_schema = OCRPageOutput
    checkpoint_schema = OCRPageMetrics
    report_schema = OCRPageReport  # Quality-focused report

    def __init__(self, max_workers: int = None, psm_modes: list = None):
        """
        Initialize OCR stage.

        Args:
            max_workers: Number of parallel workers (default: all CPU cores)
            psm_modes: List of PSM modes to run (default: [3, 4, 6])
        """
        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.psm_modes = psm_modes or [3, 4, 6]
        self.progress_lock = threading.Lock()

    def before(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger):
        """Validate source images exist and create PSM-specific subdirectories."""
        source_stage = storage.stage('source')
        source_pages = source_stage.list_output_pages(extension='png')

        if not source_pages:
            raise FileNotFoundError(
                f"No source page images found in {source_stage.output_dir}. "
                f"Run 'ar add <pdf>' to extract pages first."
            )

        logger.info(f"Found {len(source_pages)} source pages to OCR")
        logger.info(f"Will run PSM modes: {self.psm_modes}")

        # Create main OCR directory
        ocr_dir = storage.stage(self.name).output_dir
        ocr_dir.mkdir(exist_ok=True)

        # Create PSM-specific subdirectories under ocr/
        for psm in self.psm_modes:
            psm_dir = ocr_dir / f"psm{psm}"
            psm_dir.mkdir(exist_ok=True)
            logger.info(f"Created directory: ocr/psm{psm}/")

    def _get_remaining_pages_for_psm(
        self,
        checkpoint: CheckpointManager,
        total_pages: int,
        psm: int
    ) -> list:
        """
        Get remaining pages for a specific PSM mode from main checkpoint.

        Args:
            checkpoint: Main OCR checkpoint
            total_pages: Total pages in book
            psm: PSM mode (3, 4, 6, etc.)

        Returns:
            List of page numbers that need processing for this PSM
        """
        # Delegate to checkpoint's sub-stage API
        return checkpoint.get_remaining_pages_for_substage(total_pages, f'psm{psm}')

    def run(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger) -> Dict[str, Any]:
        """Process pages in parallel with multiple PSM modes."""
        # Get total pages from metadata
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        # Initialize main checkpoint with total_pages (enables resume)
        checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)

        logger.start_stage(total_pages=total_pages, max_workers=self.max_workers)
        logger.info("OCR Stage - Multi-PSM Tesseract extraction + OpenCV image detection")

        # Track overall stats
        total_completed = 0
        total_failed = 0
        stage_start_time = time.time()
        any_work_done = False

        # Check if all PSMs are already complete before entering processing loop
        all_psms_complete = True
        for psm in self.psm_modes:
            pages = self._get_remaining_pages_for_psm(checkpoint, total_pages, psm)
            if pages:
                all_psms_complete = False
                break

        if all_psms_complete:
            logger.info("All PSM modes already complete - skipping to vision selection")
        else:
            # Process each PSM mode sequentially with separate progress tracking
            for psm_idx, psm in enumerate(self.psm_modes, 1):
                psm_start_time = time.time()
                logger.info(f"[PSM {psm}] Starting extraction ({psm_idx}/{len(self.psm_modes)})")

                # Get pages to process for this PSM from main checkpoint
                pages = self._get_remaining_pages_for_psm(checkpoint, total_pages, psm)

                if not pages:
                    logger.info(f"[PSM {psm}] All pages already complete, skipping")
                    continue

                any_work_done = True
                logger.info(f"[PSM {psm}] Processing {len(pages)} pages with {self.max_workers} workers")

                # Build tasks for this PSM
                tasks = []
                for page_num in pages:
                    tasks.append({
                        'storage_root': str(storage.storage_root),
                        'scan_id': storage.scan_id,
                        'page_number': page_num,
                        'psm_mode': psm
                    })

                # Track PSM-specific stats
                psm_completed = 0
                psm_failed = 0

                # Progress bar for this PSM
                progress = RichProgressBar(
                    total=len(pages),
                    prefix=f"   PSM {psm}",
                    width=40,
                    unit="pages"
                )

                # Process in parallel using all CPU cores
                with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                    future_to_page = {
                        executor.submit(process_page_psm_worker, task): task['page_number']
                        for task in tasks
                    }

                    for future in as_completed(future_to_page):
                        page_num = future_to_page[future]

                        try:
                            success, returned_page_num, error_msg, page_data, metrics = future.result()

                            if success:
                                # Validate metrics against schema
                                from pipeline.ocr.schemas import OCRPageMetrics
                                validated_metrics = OCRPageMetrics(**metrics)

                                # Save to PSM-specific subdirectory under ocr/
                                ocr_dir = storage.stage(self.name).output_dir
                                psm_dir = ocr_dir / f"psm{psm}"
                                page_file = psm_dir / f"page_{returned_page_num:04d}.json"

                                # Write page data
                                validated_page = OCRPageOutput(**page_data)
                                page_file.write_text(validated_page.model_dump_json(indent=2))

                                # Mark PSM complete in checkpoint (atomic, preserves other sub-stages)
                                checkpoint.mark_substage_completed(
                                    page_num=returned_page_num,
                                    substage=f'psm{psm}',
                                    value=True,
                                    cost_usd=0.0
                                )
                                psm_completed += 1
                            else:
                                logger.error(f"[PSM {psm}] Page {page_num} failed", error=error_msg)
                                psm_failed += 1

                        except Exception as e:
                            logger.error(f"[PSM {psm}] Page {page_num} exception", error=str(e))
                            psm_failed += 1

                        # Update progress
                        with self.progress_lock:
                            current = psm_completed + psm_failed
                            suffix = f"{psm_completed} ok" + (f", {psm_failed} failed" if psm_failed > 0 else "")
                            progress.update(current, suffix=suffix)

                # Calculate PSM elapsed time
                psm_elapsed = time.time() - psm_start_time
                minutes = int(psm_elapsed // 60)
                seconds = int(psm_elapsed % 60)

                # Finish PSM progress
                progress.finish(f"   ✓ PSM {psm}: {psm_completed}/{len(pages)} pages in {minutes}m {seconds}s")

                if psm_failed > 0:
                    logger.warning(f"[PSM {psm}] {psm_failed} pages failed")

                # Accumulate stats
                total_completed += psm_completed
                total_failed += psm_failed

        # Calculate total elapsed time
        stage_elapsed = time.time() - stage_start_time
        total_minutes = int(stage_elapsed // 60)
        total_seconds = int(stage_elapsed % 60)

        # Log final summary with timing
        if not any_work_done:
            logger.info("All PSM modes already complete")
        else:
            logger.info(f"Completed all PSM modes: {total_completed} pages processed, {total_failed} failures")
            logger.info(f"Total stage time: {total_minutes}m {total_seconds}s")

        # Phase 2: Vision-based PSM selection (always run, even if PSMs were cached)
        vision_stats = self._run_vision_selection(storage, checkpoint, logger, metadata)

        # Return combined stats
        return {
            'pages_processed': total_completed,
            'pages_failed': total_failed,
            'total_cost_usd': vision_stats.get('total_cost_usd', 0.0),
            'psm_modes': self.psm_modes,
            'total_time_seconds': stage_elapsed + vision_stats.get('total_time_seconds', 0.0),
            'vision_selection_pages': vision_stats.get('pages_processed', 0)
        }

    def after(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger, stats: Dict[str, Any]):
        """Generate PSM analysis reports, PSM selection, and extract book metadata."""
        # Check if ALL sub-stages (PSMs + vision selection) are complete
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        # Build list of required sub-stages
        required_substages = [f'psm{psm}' for psm in self.psm_modes] + ['vision_psm']

        # Check completion using clean checkpoint API
        all_complete = checkpoint.check_substages_complete(total_pages, required_substages)

        if not all_complete:
            # Get detailed counts for logging
            counts = checkpoint.get_substage_completion_counts(total_pages, required_substages)
            for substage, count in counts.items():
                if count < total_pages:
                    logger.warning(f"{substage} not fully complete: {count}/{total_pages} pages")
            logger.warning("Sub-stages incomplete - main checkpoint not marked complete")
        else:
            logger.info("All PSM modes and vision selection complete - marking main checkpoint")
            checkpoint.mark_stage_complete()

        # Generate PSM comparison reports (includes agreement analysis)
        from pipeline.ocr.analyze_psm_reports import generate_all_reports
        generate_all_reports(storage, logger, self.psm_modes)

        # Generate/update PSM selection file from checkpoint
        # This updates the deterministic selections with vision LLM results
        logger.info("Updating PSM selection file from checkpoint...")
        self._generate_psm_selection_from_checkpoint(storage, logger, total_pages)

        # Extract book metadata from first 15 pages (stage-specific)
        logger.info("Extracting book metadata from OCR text...")
        metadata_extracted = self._extract_metadata(storage, logger)

        if metadata_extracted:
            logger.info("Metadata extraction complete")
        else:
            logger.warning("Metadata extraction failed or low confidence")

    def _extract_metadata(self, storage: BookStorage, logger: PipelineLogger, num_pages: int = 15) -> bool:
        """
        Extract book metadata from first N pages of OCR output.

        Args:
            storage: BookStorage instance
            logger: Logger instance
            num_pages: Number of pages to analyze (default: 15)

        Returns:
            True if metadata extracted and updated, False otherwise
        """
        from infra.llm.client import LLMClient
        from infra.config import Config

        # Use PSM 4 for metadata extraction (optimized for single-column book text)
        ocr_dir = storage.stage('ocr').output_dir
        psm4_dir = ocr_dir / 'psm4'
        ocr_files = sorted(psm4_dir.glob("page_*.json"))

        if not ocr_files:
            logger.warning("No OCR files found for metadata extraction")
            return False

        # Collect text from first N pages
        pages_text = []
        for i, ocr_file in enumerate(ocr_files[:num_pages], 1):
            try:
                with open(ocr_file, 'r') as f:
                    ocr_data = json.load(f)

                # Extract all text from blocks/paragraphs
                page_text = []
                for block in ocr_data.get('blocks', []):
                    for para in block.get('paragraphs', []):
                        text = para.get('text', '').strip()
                        if text:
                            page_text.append(text)

                if page_text:
                    pages_text.append(f"--- Page {i} ---\n" + "\n".join(page_text))

            except Exception as e:
                logger.warning(f"Failed to read OCR page {i}", error=str(e))
                continue

        if not pages_text:
            logger.error("No text extracted from OCR files")
            return False

        combined_text = "\n\n".join(pages_text)
        logger.info(f"Extracted {len(combined_text)} characters from {len(pages_text)} pages")

        # Build prompt for metadata extraction
        prompt = f"""<task>
Analyze the text from the FIRST PAGES of this scanned book and extract bibliographic metadata.

These pages typically contain:
- Title page (large title text)
- Copyright page (publisher, year, ISBN)
- Table of contents
- Dedication or foreword

Extract the following information:
- title: Complete book title including subtitle
- author: Author name(s) - format as "First Last" or "First Last and First Last"
- year: Publication year (integer)
- publisher: Publisher name
- type: Book genre/type (biography, history, memoir, political_analysis, military_history, etc.)
- isbn: ISBN if visible (can be null)

Return ONLY information you can clearly identify from the text. Do not guess.
Set confidence to 0.9+ if information is on a clear title/copyright page.
Set confidence to 0.5-0.8 if inferred from content.
Set confidence below 0.5 if uncertain.
</task>

<text>
{combined_text[:15000]}
</text>

<output_format>
Return JSON only. No explanations.
</output_format>"""

        # Define JSON schema for structured output
        response_schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "book_metadata",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": ["string", "null"]},
                        "author": {"type": ["string", "null"]},
                        "year": {"type": ["integer", "null"]},
                        "publisher": {"type": ["string", "null"]},
                        "type": {"type": ["string", "null"]},
                        "isbn": {"type": ["string", "null"]},
                        "confidence": {"type": "number"}
                    },
                    "required": ["title", "author", "year", "publisher", "type", "isbn", "confidence"],
                    "additionalProperties": False
                }
            }
        }

        try:
            # Use batch client for consistent logging and telemetry
            from infra.llm.batch_client import LLMBatchClient, LLMRequest

            # Use stage-specific log directory
            stage_log_dir = storage.stage('ocr').output_dir / "logs"
            batch_client = LLMBatchClient(
                max_workers=1,
                # rate_limit uses Config.rate_limit_requests_per_minute by default
                max_retries=3,
                verbose=True,  # Enable detailed progress
                log_dir=stage_log_dir,
                log_timestamp=logger.log_file.stem.split('_', 1)[1] if hasattr(logger, 'log_file') else None
            )

            # Create single request for metadata extraction
            request = LLMRequest(
                id="metadata_extraction",
                model=Config.vision_model_primary,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                response_format=response_schema,
                metadata={}
            )

            logger.info(
                "Calling LLM for metadata extraction",
                model=Config.vision_model_primary,
                num_pages=len(pages_text),
                text_length=len(combined_text)
            )

            # Process batch with single request (gets full telemetry)
            results = batch_client.process_batch([request])

            if not results or len(results) == 0:
                logger.error("No result returned from metadata extraction")
                return False

            result = results[0]

            if not result.success:
                logger.error("Metadata extraction failed", error=result.error_message)
                return False

            # Parse JSON response
            metadata = json.loads(result.response)
            confidence = metadata.get('confidence', 0)

            # Log detailed extraction results with full telemetry
            logger.info(
                "Metadata extracted successfully",
                confidence=confidence,
                title=metadata.get('title', 'Unknown'),
                author=metadata.get('author', 'Unknown'),
                year=metadata.get('year', 'Unknown'),
                publisher=metadata.get('publisher', 'Unknown'),
                book_type=metadata.get('type', 'Unknown'),
                cost_usd=result.cost_usd,
                input_tokens=result.usage.get('prompt_tokens', 0),
                output_tokens=result.usage.get('completion_tokens', 0),
                reasoning_tokens=result.usage.get('reasoning_tokens', 0),
                total_tokens=result.usage.get('total_tokens', 0),
                ttft_seconds=result.ttft_seconds,
                tokens_per_second=result.tokens_per_second,
                execution_time=result.execution_time_seconds
            )

            # Only update if confidence >= 0.5
            if confidence < 0.5:
                logger.warning(f"Low confidence ({confidence:.2f}) - metadata not updated")
                return False

            # Update metadata.json
            current_metadata = storage.load_metadata()

            # Update fields (preserve existing non-None values if extraction is None)
            for field in ['title', 'author', 'year', 'publisher', 'type', 'isbn']:
                extracted_value = metadata.get(field)
                if extracted_value is not None:
                    current_metadata[field] = extracted_value

            current_metadata['metadata_extraction_confidence'] = confidence

            # Save updated metadata
            storage.save_metadata(current_metadata)

            logger.info("Metadata saved to metadata.json")
            return True

        except Exception as e:
            logger.error("Metadata extraction failed", error=str(e))
            import traceback
            logger.error("Traceback", error=traceback.format_exc())
            return False

    def _select_winning_psm_for_page(
        self,
        storage: BookStorage,
        page_num: int,
        confidence_threshold: float = 0.85
    ) -> Dict[str, Any]:
        """
        Select the best PSM mode for a single page based on quality heuristics.

        Selection criteria:
        1. Highest mean confidence (primary)
        2. Fewest paragraphs below threshold (tie-breaker if within 1%)

        Args:
            storage: BookStorage instance
            page_num: Page number to analyze
            confidence_threshold: Threshold for low-confidence detection (default: 0.85)

        Returns:
            {
                "winning_psm": 4,
                "reason": "highest_confidence",
                "scores": {
                    3: {"mean_confidence": 0.91, "below_threshold_pct": 12.5, ...},
                    4: {"mean_confidence": 0.93, "below_threshold_pct": 8.2, ...},
                    6: {"mean_confidence": 0.89, "below_threshold_pct": 15.1, ...}
                }
            }
        """
        from pipeline.ocr.schemas import OCRPageOutput

        ocr_dir = storage.stage('ocr').output_dir
        scores = {}

        # Load and score each PSM output
        for psm in self.psm_modes:
            psm_file = ocr_dir / f'psm{psm}' / f'page_{page_num:04d}.json'

            if not psm_file.exists():
                continue

            try:
                page_data = OCRPageOutput.model_validate_json(psm_file.read_text())
            except Exception:
                # Invalid JSON or schema validation failed - skip
                continue

            # Collect paragraph-level confidence scores
            all_confidences = []
            below_threshold_count = 0

            for block in page_data.blocks:
                for para in block.paragraphs:
                    all_confidences.append(para.avg_confidence)
                    if para.avg_confidence < confidence_threshold:
                        below_threshold_count += 1

            # Skip PSMs that found no text
            if len(all_confidences) == 0:
                continue

            # Calculate quality metrics
            mean_confidence = sum(all_confidences) / len(all_confidences)
            below_threshold_pct = (below_threshold_count / len(all_confidences)) * 100

            scores[psm] = {
                'mean_confidence': round(mean_confidence, 4),
                'below_threshold_pct': round(below_threshold_pct, 2),
                'block_count': len(page_data.blocks),
                'paragraph_count': len(all_confidences),
                'image_count': len(page_data.images)
            }

        # Handle edge case: no valid PSM outputs
        if not scores:
            return {
                'winning_psm': None,
                'reason': 'no_valid_outputs',
                'scores': {}
            }

        # Primary selection: highest mean confidence
        winner = max(scores.keys(), key=lambda psm: scores[psm]['mean_confidence'])
        reason = "highest_confidence"

        # Check for ties (within 1% confidence)
        winner_conf = scores[winner]['mean_confidence']
        ties = [
            psm for psm in scores.keys()
            if abs(scores[psm]['mean_confidence'] - winner_conf) < 0.01
        ]

        # Tie-breaker: fewest paragraphs below threshold
        if len(ties) > 1:
            winner = min(ties, key=lambda psm: scores[psm]['below_threshold_pct'])
            reason = "tie_broken_by_threshold"

        return {
            'winning_psm': winner,
            'reason': reason,
            'scores': scores
        }

    def _generate_psm_selection(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
        total_pages: int
    ):
        """
        Generate psm_selection.json file mapping each page to its winning PSM.

        Args:
            storage: BookStorage instance
            logger: PipelineLogger instance
            total_pages: Total number of pages in the book
        """
        ocr_dir = storage.stage('ocr').output_dir
        selection_file = ocr_dir / 'psm_selection.json'

        # Skip if already exists
        if selection_file.exists():
            logger.info("  PSM selection file already exists, skipping generation")
            return

        logger.info(f"  Selecting best PSM for {total_pages} pages...")

        page_selections = {}
        psm_win_counts = {psm: 0 for psm in self.psm_modes}
        tie_broken_count = 0
        no_output_count = 0

        for page_num in range(1, total_pages + 1):
            result = self._select_winning_psm_for_page(storage, page_num)

            winner = result['winning_psm']
            reason = result['reason']

            if winner is None:
                no_output_count += 1
                # Store None for pages with no valid outputs
                page_selections[str(page_num)] = None
            else:
                page_selections[str(page_num)] = winner
                psm_win_counts[winner] += 1

                if reason == 'tie_broken_by_threshold':
                    tie_broken_count += 1

        # Build selection document
        selection_data = {
            'scan_id': storage.scan_id,
            'selection_criteria': 'highest_mean_confidence',
            'confidence_threshold': 0.85,
            'psm_modes': self.psm_modes,
            'page_selections': page_selections,
            'summary': {
                'total_pages': total_pages,
                'psm_win_counts': psm_win_counts,
                'ties_broken': tie_broken_count,
                'no_valid_outputs': no_output_count
            }
        }

        # Save to file
        selection_file.write_text(json.dumps(selection_data, indent=2))
        logger.info(f"  Saved: ocr/psm_selection.json")

        # Log summary
        for psm, count in sorted(psm_win_counts.items()):
            pct = (count / total_pages * 100) if total_pages > 0 else 0
            logger.info(f"    PSM {psm}: {count} pages ({pct:.1f}%)")

        if tie_broken_count > 0:
            logger.info(f"    Ties broken by threshold: {tie_broken_count}")

        if no_output_count > 0:
            logger.warning(f"    Pages with no valid outputs: {no_output_count}")

    def _generate_psm_selection_from_checkpoint(
        self,
        storage: BookStorage,
        logger: PipelineLogger,
        total_pages: int
    ):
        """
        Generate/update psm_selection.json from vision selection checkpoint.

        Merges deterministic confidence-based selections with LLM vision selections.
        """
        ocr_dir = storage.stage('ocr').output_dir
        selection_file = ocr_dir / 'psm_selection.json'

        # Load vision selection checkpoint if it exists
        vision_checkpoint_file = ocr_dir / 'psm_selection' / '.checkpoint'
        vision_selections = {}

        if vision_checkpoint_file.exists():
            try:
                with open(vision_checkpoint_file) as f:
                    vision_checkpoint_data = json.load(f)

                # Extract vision selections from page_metrics
                vision_model = None
                for page_num_str, metrics in vision_checkpoint_data.get('page_metrics', {}).items():
                    page_num = int(page_num_str)
                    vision_selections[page_num] = {
                        'selected_psm': metrics.get('selected_psm'),
                        'confidence': metrics.get('confidence'),
                        'reason': metrics.get('reason', 'Vision-based selection'),
                        'cost_usd': metrics.get('cost_usd', 0.0)
                    }
                    # Get model from first page's metrics
                    if vision_model is None:
                        vision_model = metrics.get('model_used')

                logger.info(f"  Loaded {len(vision_selections)} vision selections from checkpoint")
            except Exception as e:
                logger.warning(f"  Failed to load vision selections: {e}")

        # Generate base selection file if it doesn't exist
        if not selection_file.exists():
            logger.info("  Generating deterministic PSM selections...")
            self._generate_psm_selection(storage, logger, total_pages)

        # If no vision selections, we're done
        if not vision_selections:
            return

        # Load existing selection file
        with open(selection_file) as f:
            selection_data = json.load(f)

        # Update with vision selections
        updated_count = 0
        for page_num, vision_sel in vision_selections.items():
            page_str = str(page_num)
            if page_str in selection_data.get('page_selections', {}):
                old_psm = selection_data['page_selections'][page_str]
                new_psm = vision_sel['selected_psm']

                selection_data['page_selections'][page_str] = new_psm

                if old_psm != new_psm:
                    updated_count += 1

        # Update metadata
        selection_data['selection_method'] = 'hybrid' if vision_selections else 'confidence'
        selection_data['vision_model'] = vision_model if vision_selections else None
        selection_data['vision_selections_count'] = len(vision_selections)
        selection_data['selections_changed'] = updated_count

        # Recalculate win counts
        psm_win_counts = {psm: 0 for psm in self.psm_modes}
        for psm_val in selection_data['page_selections'].values():
            if psm_val is not None:
                psm_win_counts[psm_val] = psm_win_counts.get(psm_val, 0) + 1
        selection_data['summary']['psm_win_counts'] = psm_win_counts

        # Save updated file
        selection_file.write_text(json.dumps(selection_data, indent=2))
        logger.info(f"  Updated psm_selection.json with {len(vision_selections)} vision selections ({updated_count} changed)")

    def _run_vision_selection(
        self,
        storage: BookStorage,
        checkpoint: CheckpointManager,
        logger: PipelineLogger,
        metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Run vision-based PSM selection for pages with major disagreements.

        Follows correction/label pattern:
        - ThreadPoolExecutor for I/O-bound LLM calls
        - LLMBatchClient with rate limiting
        - RichProgressBarHierarchical for live stats
        - Structured responses with validation

        Returns:
            Stats dict with pages_processed, total_cost_usd, total_time_seconds
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from PIL import Image
        import json
        import time
        import threading

        from infra.llm.batch_client import LLMBatchClient, LLMRequest, LLMResult
        from infra.utils.pdf import downsample_for_vision
        from infra.pipeline.rich_progress import RichProgressBar, RichProgressBarHierarchical
        from infra.config import Config
        from pipeline.ocr.vision_selection_prompts import SYSTEM_PROMPT, build_user_prompt
        from pipeline.ocr.vision_selection_schemas import VisionSelectionResponse, VisionSelectionMetrics

        logger.info("=== Phase 2: Vision-based PSM Selection ===")

        total_pages = metadata.get('total_pages', 0)

        # Run vision selection on ALL pages
        # Rationale: Agreement analysis measures text similarity, not structural correctness.
        # Two PSMs can have identical text but different block/paragraph structures.
        # Only visual inspection can determine which structure is correct.

        ocr_dir = storage.stage('ocr').output_dir

        # Build list of all pages for vision selection
        pages_needing_llm = []
        for page_num in range(1, total_pages + 1):
            # Check if all 3 PSM outputs exist for this page
            has_all_psms = all(
                (ocr_dir / f'psm{psm}' / f'page_{page_num:04d}.json').exists()
                for psm in self.psm_modes
            )

            if has_all_psms:
                pages_needing_llm.append({
                    'page_num': page_num,
                    # No agreement metrics needed - we removed them from prompt
                })

        if not pages_needing_llm:
            logger.info("No pages with complete PSM outputs found")
            return {'pages_processed': 0, 'total_cost_usd': 0.0, 'total_time_seconds': 0.0}

        logger.info(f"Running vision selection on {len(pages_needing_llm)} pages")

        # Get remaining pages from main checkpoint (pages without vision_psm set)
        page_nums_needing_llm = [p['page_num'] for p in pages_needing_llm]

        # Use checkpoint API to find pages without vision selection
        all_remaining = checkpoint.get_remaining_pages_for_substage(total_pages, 'vision_psm')
        remaining_pages = [p for p in all_remaining if p in page_nums_needing_llm]

        logger.info(f"Remaining pages from checkpoint: {len(remaining_pages)}/{len(page_nums_needing_llm)}")

        # Filter to only pages that both need LLM AND are not complete
        remaining_pages_set = set(remaining_pages)
        pages_to_process = [p for p in pages_needing_llm if p['page_num'] in remaining_pages_set]

        if not pages_to_process:
            logger.info("All vision selection pages already complete")
            # Get stats from main checkpoint
            status = checkpoint.get_status()
            # Count pages with vision_psm set
            pages_with_vision = sum(1 for metrics in status.get('page_metrics', {}).values()
                                   if 'vision_psm' in metrics)
            return {
                'pages_processed': pages_with_vision,
                'total_cost_usd': status.get('metadata', {}).get('total_cost_usd', 0.0),
                'total_time_seconds': 0.0
            }

        logger.info(f"Processing {len(pages_to_process)} pages with vision LLM ({Config.vision_model_primary})")

        # Initialize batch LLM client
        stage_log_dir = ocr_dir / 'psm_selection' / 'logs'
        stage_log_dir.mkdir(parents=True, exist_ok=True)

        batch_client = LLMBatchClient(
            max_workers=Config.max_workers,
            max_retries=3,
            retry_jitter=(1.0, 3.0),
            verbose=True,
            log_dir=stage_log_dir,
            log_timestamp=logger.log_file.stem.split('_', 1)[1] if hasattr(logger, 'log_file') else None
        )

        # Phase A: Parallel page loading
        logger.info(f"Loading {len(pages_to_process)} pages...")
        load_start_time = time.time()
        load_progress = RichProgressBar(
            total=len(pages_to_process),
            prefix="   ",
            width=40,
            unit="pages"
        )
        load_progress.update(0, suffix="loading...")

        requests = []
        page_data_map = {}
        completed_loads = 0
        load_lock = threading.Lock()

        def load_page_for_selection(page_result):
            """Load and prepare a single page for vision selection."""
            page_num = page_result['page_num']
            agreement_metrics = {
                'avg_similarity': page_result.get('avg_similarity', 0.0),
                'category': page_result.get('category', 'unknown'),
                'max_word_diff': page_result.get('max_word_diff', 0)
            }

            try:
                # Load all 3 PSM outputs
                psm_outputs = {}
                for psm in self.psm_modes:
                    psm_file = ocr_dir / f'psm{psm}' / f'page_{page_num:04d}.json'
                    if psm_file.exists():
                        with open(psm_file, 'r') as f:
                            psm_outputs[psm] = json.load(f)

                if len(psm_outputs) < len(self.psm_modes):
                    missing_psms = set(self.psm_modes) - set(psm_outputs.keys())
                    logger.warning(f"Page {page_num} missing PSM outputs: {missing_psms}, skipping")
                    return None

                # Load source image
                source_stage = storage.stage('source')
                page_file = source_stage.output_page(page_num, extension='png')

                if not page_file.exists():
                    logger.warning(f"Page {page_num} source image not found")
                    return None

                # Load and downsample image
                page_image = Image.open(page_file)
                page_image = downsample_for_vision(page_image)

                # Build prompt
                user_prompt = build_user_prompt(
                    page_num=page_num,
                    total_pages=total_pages,
                    book_metadata=metadata,
                    psm_outputs=psm_outputs,
                    agreement_metrics=agreement_metrics
                )

                # Create LLM request with structured response
                request = LLMRequest(
                    id=f"page_{page_num:04d}",
                    model=Config.vision_model_primary,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    images=[page_image],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "psm_selection",
                            "strict": True,
                            "schema": VisionSelectionResponse.model_json_schema()
                        }
                    },
                    metadata={
                        'page_num': page_num,
                        'agreement_metrics': agreement_metrics,
                        'psm_outputs': psm_outputs
                    }
                )

                return (page_num, agreement_metrics, request)

            except Exception as e:
                logger.error(f"Failed to load page {page_num}", error=str(e))
                return None

        # Load pages in parallel
        with ThreadPoolExecutor(max_workers=Config.max_workers) as executor:
            future_to_page = {
                executor.submit(load_page_for_selection, page_result): page_result['page_num']
                for page_result in pages_to_process
            }

            for future in as_completed(future_to_page):
                result = future.result()
                if result:
                    page_num, agreement_metrics, request = result
                    requests.append(request)
                    page_data_map[page_num] = {
                        'agreement_metrics': agreement_metrics,
                        'request': request
                    }

                with load_lock:
                    completed_loads += 1
                    load_progress.update(completed_loads, suffix=f"{len(requests)} loaded")

        load_elapsed = time.time() - load_start_time
        load_progress.finish(f"   ✓ {len(requests)} pages loaded in {load_elapsed:.1f}s")

        if len(requests) == 0:
            logger.info("No valid pages to process")
            return {'pages_processed': 0, 'total_cost_usd': 0.0, 'total_time_seconds': load_elapsed}

        # Phase B: Concurrent LLM processing
        logger.info(f"Selecting best PSM for {len(requests)} pages...")
        selection_start_time = time.time()
        progress = RichProgressBarHierarchical(
            total=len(requests),
            prefix="   ",
            width=40,
            unit="pages"
        )
        progress.update(0, suffix="starting...")

        failed_pages = []
        selections = {}  # Store selections for updating psm_selection.json

        # Create event handler
        on_event = progress.create_llm_event_handler(
            batch_client=batch_client,
            start_time=selection_start_time,
            model=Config.vision_model_primary,
            total_requests=len(requests),
            checkpoint=checkpoint
        )

        def on_result(result: LLMResult):
            """Handle LLM result - save selection to checkpoint."""
            try:
                page_num = result.request.metadata['page_num']
                agreement_metrics = result.request.metadata['agreement_metrics']

                if result.success:
                    try:
                        # Parse structured response
                        selection_data = result.parsed_json
                        if selection_data is None:
                            raise ValueError("parsed_json is None for successful result")

                        # Validate with schema
                        validated = VisionSelectionResponse(**selection_data)

                        # Calculate alternatives rejected
                        alternatives = [psm for psm in self.psm_modes if psm != validated.selected_psm]

                        # Build metrics
                        metrics = VisionSelectionMetrics(
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
                            # Vision selection specific
                            selected_psm=validated.selected_psm,
                            confidence=validated.confidence,
                            alternatives_rejected=alternatives,
                            agreement_similarity=agreement_metrics['avg_similarity'],
                            agreement_category=agreement_metrics['category']
                        )

                        # Save vision selection to checkpoint (atomic, preserves PSM flags)
                        checkpoint.mark_substage_completed(
                            page_num=page_num,
                            substage='vision_psm',
                            value=validated.selected_psm,
                            cost_usd=result.cost_usd
                        )

                        # Store for psm_selection.json update
                        selections[page_num] = {
                            'selected_psm': validated.selected_psm,
                            'confidence': validated.confidence,
                            'reason': validated.reason,
                            'cost_usd': result.cost_usd
                        }

                    except Exception as e:
                        logger.error(f"Failed to process page {page_num} result", error=str(e))
                        failed_pages.append(page_num)
                else:
                    logger.error(f"Page {page_num} LLM call failed", error=result.error)
                    failed_pages.append(page_num)

            except Exception as e:
                logger.error(f"Error handling result", error=str(e))

        # Process batch
        results = batch_client.process_batch(
            requests,
            on_event=on_event,
            on_result=on_result
        )

        # Finish progress
        selection_elapsed = time.time() - selection_start_time
        batch_stats = batch_client.get_batch_stats(total_requests=len(requests))
        progress.finish(f"   ✓ {batch_stats.completed}/{len(requests)} pages selected in {selection_elapsed:.1f}s")

        # Vision selections are saved to checkpoint - will be merged in after() hook
        logger.info(f"Vision selection saved {len(selections)} pages to checkpoint")

        # Get final stats
        status = vision_checkpoint.get_status()
        total_cost = status.get('metadata', {}).get('total_cost_usd', 0.0)
        completed = batch_stats.completed

        if failed_pages:
            logger.warning(f"{len(failed_pages)} pages failed: {sorted(failed_pages)[:10]}")

        logger.info(f"Vision selection complete: {completed} pages, ${total_cost:.4f}")

        return {
            'pages_processed': completed,
            'total_cost_usd': total_cost,
            'total_time_seconds': load_elapsed + selection_elapsed
        }
