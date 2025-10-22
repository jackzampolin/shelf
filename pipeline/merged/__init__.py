"""
Merge Stage - Combines OCR, Correction, and Label data.

Merges three data sources into unified page records:
- OCR: Original text and spatial layout (bounding boxes)
- Correction: Corrected text where errors were found
- Label: Block classifications and printed page numbers

Cost: $0 (deterministic merge, no LLM)
Performance: <30s for 400 pages
"""

import json
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Any

from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

# Import from local modules
from pipeline.merged.schemas import MergedPageOutput
from pipeline.ocr.schemas import OCRPageOutput
from pipeline.correction.schemas import CorrectionPageOutput
from pipeline.label.schemas import LabelPageOutput


class MergeStage(BaseStage):
    """
    Merge Stage - Three-way merge of OCR, Correction, and Label data.

    Reads: ocr/*.json + corrected/*.json + labels/*.json
    Writes: merged/*.json (unified page records)
    """

    name = "merged"  # Output directory name
    dependencies = ["ocr", "corrected", "labels"]  # Requires all three stages

    def __init__(self, max_workers: int = 8):
        """
        Initialize Merge stage.

        Args:
            max_workers: Number of parallel workers (default: 8)
        """
        self.max_workers = max_workers
        self.progress_lock = threading.Lock()
        self.stats_lock = threading.Lock()

    def before(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger):
        """Validate OCR, correction, and label outputs all exist and match 1-1."""
        # Get OCR outputs
        ocr_stage = storage.stage('ocr')
        ocr_pages = ocr_stage.list_output_pages(extension='json')

        if not ocr_pages:
            raise FileNotFoundError(
                f"No OCR outputs found in {ocr_stage.output_dir}. "
                f"Run OCR stage first."
            )

        # Get correction outputs
        correction_stage = storage.stage('corrected')
        correction_pages = correction_stage.list_output_pages(extension='json')

        if not correction_pages:
            raise FileNotFoundError(
                f"No correction outputs found in {correction_stage.output_dir}. "
                f"Run correction stage first."
            )

        # Get label outputs
        label_stage = storage.stage('labels')
        label_pages = label_stage.list_output_pages(extension='json')

        if not label_pages:
            raise FileNotFoundError(
                f"No label outputs found in {label_stage.output_dir}. "
                f"Run label stage first."
            )

        # Verify 1-1-1 correspondence
        ocr_nums = set(int(p.stem.split('_')[1]) for p in ocr_pages)
        correction_nums = set(int(p.stem.split('_')[1]) for p in correction_pages)
        label_nums = set(int(p.stem.split('_')[1]) for p in label_pages)

        if not (ocr_nums == correction_nums == label_nums):
            error_parts = []
            if ocr_nums != correction_nums:
                missing = ocr_nums.symmetric_difference(correction_nums)
                error_parts.append(f"OCR/Correction mismatch on pages: {sorted(list(missing))[:10]}")
            if ocr_nums != label_nums:
                missing = ocr_nums.symmetric_difference(label_nums)
                error_parts.append(f"OCR/Label mismatch on pages: {sorted(list(missing))[:10]}")

            raise FileNotFoundError(
                f"OCR, correction, and label outputs don't match 1-1-1. {' '.join(error_parts)}"
            )

        logger.info(
            f"Validated {len(ocr_pages)} pages ready for merge",
            max_workers=self.max_workers
        )

    def run(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger) -> Dict[str, Any]:
        """Merge OCR, correction, and label data for all pages."""
        # Get total pages from metadata
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        if total_pages == 0:
            raise ValueError("total_pages not set in metadata")

        logger.start_stage(total_pages=total_pages, max_workers=self.max_workers)
        logger.info(f"Merge Stage - Three-way merge (OCR + Correction + Label, $0 cost)")

        # Get pages to process
        pages = checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)

        if not pages:
            logger.info("No pages to process (all complete)")
            return checkpoint.get_status().get('metadata', {})

        logger.info(f"Processing {len(pages)} pages with {self.max_workers} workers")

        # Track stats
        completed = 0
        failed = 0
        total_corrections_used = 0
        pages_with_continuation = 0

        # Progress bar
        progress = RichProgressBar(
            total=len(pages),
            prefix="   ",
            width=40,
            unit="pages"
        )

        # Process pages in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_page = {
                executor.submit(
                    self._process_page,
                    page_num,
                    storage,
                    logger
                ): page_num
                for page_num in pages
            }

            for future in as_completed(future_to_page):
                page_num = future_to_page[future]

                try:
                    success, corrections_used, has_continuation, merged_data = future.result()

                    if success:
                        # Save merged output
                        storage.stage(self.name).save_page(
                            page_num=page_num,
                            data=merged_data,
                            schema=MergedPageOutput
                        )

                        # Mark complete in checkpoint
                        checkpoint.mark_completed(page_num, cost_usd=0.0)

                        with self.stats_lock:
                            completed += 1
                            total_corrections_used += corrections_used
                            if has_continuation:
                                pages_with_continuation += 1
                    else:
                        logger.error(f"Page {page_num} merge failed")
                        failed += 1

                except Exception as e:
                    logger.error(f"Page {page_num} exception", error=str(e))
                    failed += 1

                # Update progress
                with self.progress_lock:
                    current = completed + failed
                    suffix = f"{completed} ok" + (f", {failed} failed" if failed > 0 else "")
                    progress.update(current, suffix=suffix)

        # Finish progress
        progress.finish(f"   ✓ Merged {completed}/{len(pages)} pages")

        if failed > 0:
            logger.warning(f"{failed} pages failed")

        # Return stats
        return {
            'pages_processed': completed,
            'pages_failed': failed,
            'total_cost_usd': 0.0,
            'total_corrections_used': total_corrections_used,
            'pages_with_continuation': pages_with_continuation
        }

    def after(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger, stats: Dict[str, Any]):
        """Log merge statistics."""
        corrections_used = stats.get('total_corrections_used', 0)
        continuation_pages = stats.get('pages_with_continuation', 0)
        total_pages = stats.get('pages_processed', 0)

        logger.info(
            "Merge complete",
            corrections_used=corrections_used,
            continuation_pages=continuation_pages
        )

        if total_pages > 0:
            correction_rate = (corrections_used / total_pages) * 100 if total_pages > 0 else 0
            continuation_rate = (continuation_pages / total_pages) * 100 if total_pages > 0 else 0
            logger.info(
                f"Correction rate: {correction_rate:.1f}% of pages had corrections",
                continuation_rate=f"{continuation_rate:.1f}% of pages have paragraph continuation"
            )

    def _process_page(
        self,
        page_num: int,
        storage: BookStorage,
        logger: PipelineLogger
    ) -> Tuple[bool, int, bool, Dict[str, Any]]:
        """
        Process single page (parallel worker).

        Args:
            page_num: Page number to process
            storage: BookStorage instance
            logger: Logger instance

        Returns:
            (success, corrections_used, has_continuation, merged_data)
        """
        try:
            # Load OCR data
            ocr_file = storage.stage('ocr').output_page(page_num, extension='json')
            if not ocr_file.exists():
                logger.error(f"OCR file not found", page=page_num)
                return False, 0, False, {}

            with open(ocr_file, 'r') as f:
                ocr_data = json.load(f)
            ocr_page = OCRPageOutput(**ocr_data)

            # Load correction data
            correction_file = storage.stage('corrected').output_page(page_num, extension='json')
            if not correction_file.exists():
                logger.error(f"Correction file not found", page=page_num)
                return False, 0, False, {}

            with open(correction_file, 'r') as f:
                correction_data = json.load(f)
            correction_page = CorrectionPageOutput(**correction_data)

            # Load label data
            label_file = storage.stage('labels').output_page(page_num, extension='json')
            if not label_file.exists():
                logger.error(f"Label file not found", page=page_num)
                return False, 0, False, {}

            with open(label_file, 'r') as f:
                label_data = json.load(f)
            label_page = LabelPageOutput(**label_data)

            # Merge page data (three-way merge)
            merged_page, corrections_used, has_continuation = self._merge_page_data(
                ocr_page,
                correction_page,
                label_page,
                logger
            )

            return True, corrections_used, has_continuation, merged_page

        except Exception as e:
            logger.error(f"Page merge failed", page=page_num, error=str(e))
            return False, 0, False, {}

    def _merge_page_data(
        self,
        ocr_page: OCRPageOutput,
        correction_page: CorrectionPageOutput,
        label_page: LabelPageOutput,
        logger: PipelineLogger
    ) -> Tuple[Dict, int, bool]:
        """
        Merge OCR, correction, and label data for a single page.

        Args:
            ocr_page: OCR page output (original text, bboxes)
            correction_page: Correction page output (corrected text, sparse)
            label_page: Label page output (classifications, page numbers)
            logger: Logger instance

        Returns:
            (merged_page_dict, corrections_used_count, has_continuation)
        """
        merged_blocks = []
        corrections_used = 0

        for ocr_block in ocr_page.blocks:
            # Find matching correction block
            corr_block = next(
                (cb for cb in correction_page.blocks if cb.block_num == ocr_block.block_num),
                None
            )

            # Find matching label block (has classifications)
            label_block = next(
                (lb for lb in label_page.blocks if lb.block_num == ocr_block.block_num),
                None
            )

            if not corr_block:
                logger.warning(
                    f"No correction block found for OCR block",
                    page=ocr_page.page_number,
                    block_num=ocr_block.block_num
                )
                continue

            if not label_block:
                logger.warning(
                    f"No label block found for OCR block",
                    page=ocr_page.page_number,
                    block_num=ocr_block.block_num
                )
                continue

            merged_paragraphs = []
            for ocr_para in ocr_block.paragraphs:
                # Find matching correction paragraph
                corr_para = next(
                    (cp for cp in corr_block.paragraphs if cp.par_num == ocr_para.par_num),
                    None
                )

                # Determine final text and whether correction was applied
                if corr_para and corr_para.text is not None:
                    # Use corrected text
                    final_text = corr_para.text
                    correction_applied = True
                    corrections_used += 1
                else:
                    # Use original OCR text
                    final_text = ocr_para.text
                    correction_applied = False

                merged_paragraphs.append({
                    "par_num": ocr_para.par_num,
                    "text": final_text,
                    "bbox": ocr_para.bbox.to_list() if hasattr(ocr_para.bbox, 'to_list') else list(ocr_para.bbox),
                    "original_confidence": ocr_para.avg_confidence,
                    "correction_applied": correction_applied,
                    "correction_confidence": corr_para.confidence if corr_para else 1.0,
                    "correction_notes": corr_para.notes if corr_para and corr_para.notes else None
                })

            # Use classification from label_block
            merged_blocks.append({
                "block_num": ocr_block.block_num,
                "classification": label_block.classification.value if hasattr(label_block.classification, 'value') else str(label_block.classification),
                "classification_confidence": label_block.classification_confidence,
                "bbox": ocr_block.bbox.to_list() if hasattr(ocr_block.bbox, 'to_list') else list(ocr_block.bbox),
                "paragraphs": merged_paragraphs
            })

        # Detect continuation
        continuation = self._detect_continuation(merged_blocks)
        has_continuation = continuation['continues_from_previous'] or continuation['continues_to_next']

        merged_page = {
            "page_number": ocr_page.page_number,
            "page_dimensions": {
                "width": ocr_page.page_dimensions.width,
                "height": ocr_page.page_dimensions.height
            },
            # Page number extraction (from label stage)
            "printed_page_number": label_page.printed_page_number,
            "numbering_style": label_page.numbering_style,
            "page_number_location": label_page.page_number_location,
            "page_number_confidence": label_page.page_number_confidence,
            "blocks": merged_blocks,
            "continuation": continuation,
            "metadata": {
                "ocr_timestamp": ocr_page.ocr_timestamp,
                "correction_timestamp": correction_page.timestamp,
                "correction_model": correction_page.model_used,
                "label_timestamp": label_page.timestamp,
                "label_model": label_page.model_used,
                "merge_timestamp": datetime.now().isoformat(),
                "total_blocks": len(merged_blocks),
                "total_corrections_applied": corrections_used
            }
        }

        return merged_page, corrections_used, has_continuation

    def _detect_continuation(self, merged_blocks: List[Dict]) -> Dict[str, bool]:
        """
        Detect if page text continues to/from other pages.

        Args:
            merged_blocks: List of merged blocks with paragraphs

        Returns:
            Dict with continues_from_previous and continues_to_next flags
        """
        if not merged_blocks:
            return {
                "continues_from_previous": False,
                "continues_to_next": False
            }

        # Check last paragraph of last block for continuation to next page
        last_block = merged_blocks[-1]
        if last_block["paragraphs"]:
            last_para = last_block["paragraphs"][-1]
            last_text = last_para["text"].strip()

            # Page continues to next if:
            # 1. Doesn't end with terminal punctuation
            # 2. Ends with hyphen (mid-word hyphenation)
            terminal_punctuation = ('.', '!', '?', '"', '"', ':', ';')
            continues_to_next = (
                not last_text.endswith(terminal_punctuation) or
                last_text.endswith('-')
            )
        else:
            continues_to_next = False

        # Check first paragraph of first non-header block for continuation from previous page
        body_blocks = [
            b for b in merged_blocks
            if b["classification"] not in ["HEADER", "PAGE_NUMBER", "FOOTER"]
        ]

        if body_blocks and body_blocks[0]["paragraphs"]:
            first_para = body_blocks[0]["paragraphs"][0]
            first_text = first_para["text"].strip()

            # Page continues from previous if:
            # 1. Starts with lowercase letter (likely continuation)
            # 2. Has text to check
            continues_from_previous = (
                len(first_text) > 0 and first_text[0].islower()
            )
        else:
            continues_from_previous = False

        return {
            "continues_from_previous": continues_from_previous,
            "continues_to_next": continues_to_next
        }
