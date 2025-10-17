"""
Stage 3: Merge & Enrich

Merges OCR, correction, and label data into unified page records with:
- Full text (corrected where available, OCR otherwise)
- Bounding boxes from OCR
- Classifications from labels
- Page numbers from labels
- Paragraph continuation tracking

Cost: $0 (deterministic merge, no LLM)
Performance: <30s for 400 pages
"""

import json
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple, Any

import importlib

from infra.checkpoint import CheckpointManager
from infra.logger import create_logger
from infra.book_storage import BookStorage

# Import OCR, Correction, and Label schemas using importlib (handles numeric module names)
ocr_schemas = importlib.import_module('pipeline.1_ocr.schemas')
OCRPageOutput = getattr(ocr_schemas, 'OCRPageOutput')

correction_schemas = importlib.import_module('pipeline.2_correction.schemas')
CorrectionOutput = getattr(correction_schemas, 'CorrectionPageOutput')

label_schemas = importlib.import_module('pipeline.3_label.schemas')
LabelOutput = getattr(label_schemas, 'LabelPageOutput')


class MergeProcessor:
    """Merges OCR, correction, and label data into unified page records."""

    def __init__(self, storage_root=None, max_workers=8, enable_checkpoints=True):
        """Initialize merge processor.

        Args:
            storage_root: Root directory for book storage (default: ~/Documents/book_scans)
            max_workers: Number of parallel workers (default: 8)
            enable_checkpoints: Enable checkpoint-based resume (default: True)
        """
        self.storage_root = Path(storage_root or Path.home() / "Documents" / "book_scans").expanduser()
        self.max_workers = max_workers
        self.enable_checkpoints = enable_checkpoints

        # Per-book state (initialized in process_book)
        self.logger = None
        self.checkpoint = None

    def process_book(self, scan_id: str, resume: bool = False) -> None:
        """Process all pages for a book.

        Args:
            scan_id: Book scan ID
            resume: Resume from checkpoint if True
        """
        # Initialize storage manager
        try:
            storage = BookStorage(scan_id=scan_id, storage_root=self.storage_root)
            storage.merge.validate_inputs()  # Validates OCR, correction, and label outputs exist
        except FileNotFoundError as e:
            print(f"❌ {e}")
            return

        # Load metadata
        metadata = storage.load_metadata()

        total_pages = metadata.get('total_pages_processed', 0)
        if total_pages == 0:
            raise ValueError(f"No pages found in metadata for {scan_id}")

        # Initialize logger
        logs_dir = storage.logs_dir
        logs_dir.mkdir(exist_ok=True)
        self.logger = create_logger(scan_id, "merge", log_dir=logs_dir)

        try:
            self.logger.start_stage(
                total_pages=total_pages,
                max_workers=self.max_workers
            )
            self.logger.info("Stage 3: Merge & Enrich - Three-way merge (OCR + Correction + Label, $0 cost)")

            # Initialize checkpoint (auto-ensures directories)
            if self.enable_checkpoints:
                self.checkpoint = storage.merge.checkpoint

                if not resume:
                    if not self.checkpoint.reset(confirm=True):
                        print("   Use --resume to continue from checkpoint.")
                        return

            # Get pages to process
            if self.checkpoint and resume:
                pages_to_process = self.checkpoint.get_remaining_pages(
                    total_pages=total_pages,
                    resume=True
                )
                if self.checkpoint.get_status()['status'] == 'completed':
                    self.logger.info("Stage already complete, skipping")
                    return
            else:
                pages_to_process = list(range(1, total_pages + 1))

            if not pages_to_process:
                self.logger.info("No pages to process")
                return

            self.logger.info(f"Processing {len(pages_to_process)} pages",
                           total=total_pages,
                           remaining=len(pages_to_process))

            # Prepare tasks
            tasks = [
                {
                    'page_num': page_num,
                    'storage': storage
                }
                for page_num in pages_to_process
            ]

            # Track domain-specific stats (not in checkpoint)
            stats_lock = threading.Lock()
            total_corrections_used = 0
            pages_with_continuation = 0
            progress_lock = threading.Lock()

            # Process pages in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(self._process_single_page, task): task for task in tasks}

                for future in as_completed(futures):
                    task = futures[future]
                    page_num = task['page_num']

                    try:
                        success, corrections_used, has_continuation = future.result()

                        # Accumulate domain-specific stats
                        if success:
                            with stats_lock:
                                total_corrections_used += corrections_used
                                if has_continuation:
                                    pages_with_continuation += 1

                        # Log progress (get counts from checkpoint)
                        with progress_lock:
                            if self.checkpoint:
                                status = self.checkpoint.get_status()
                                completed = len(status.get('completed_pages', []))
                                failed = len(pages_to_process) - completed
                            else:
                                # No checkpoint mode - estimate from completed futures
                                completed = sum(1 for f in futures if f.done() and f.result()[0])
                                failed = sum(1 for f in futures if f.done() and not f.result()[0])

                            progress_count = completed + failed

                            self.logger.progress(
                                "Merging pages",
                                current=progress_count,
                                total=len(tasks),
                                completed=completed,
                                errors=failed
                            )

                    except Exception as e:
                        self.logger.error(f"Page processing failed", page=page_num, error=str(e))

            # Get final stats from checkpoint (single source of truth)
            if self.checkpoint:
                status = self.checkpoint.get_status()
                pages_processed = len(status.get('completed_pages', []))
                failed_pages = total_pages - pages_processed

                # Mark stage complete with domain stats in metadata
                self.checkpoint.mark_stage_complete(metadata={
                    "total_pages_processed": pages_processed,
                    "total_corrections_used": total_corrections_used,
                    "pages_with_continuation": pages_with_continuation,
                    "failed_pages": failed_pages,
                    "total_cost_usd": 0.0  # Deterministic stage
                })
            else:
                # No checkpoint - count from tasks
                pages_processed = len(tasks)
                failed_pages = 0

            # Log completion
            self.logger.info(
                "Merge stage complete",
                pages_processed=pages_processed,
                corrections_used=total_corrections_used,
                continuation_pages=pages_with_continuation,
                failed=failed_pages
            )

        except Exception as e:
            self.logger.error(f"Merge stage failed", error=str(e))
            if self.checkpoint:
                self.checkpoint.mark_stage_failed(error=str(e))
            raise

        finally:
            if self.logger:
                self.logger.close()

    def _process_single_page(self, task: Dict) -> Tuple[bool, int, bool]:
        """Process single page (parallel worker).

        Args:
            task: Task dict with page_num and storage

        Returns:
            (success, corrections_used, has_continuation)
        """
        page_num = task['page_num']
        storage = task['storage']

        try:
            # Load OCR data
            ocr_file = storage.merge.ocr_page(page_num)
            if not ocr_file.exists():
                self.logger.error(f"OCR file not found", page=page_num, file=str(ocr_file))
                return False, 0, False

            with open(ocr_file, 'r') as f:
                ocr_data = json.load(f)
            ocr_page = OCRPageOutput(**ocr_data)

            # Load correction data
            correction_file = storage.merge.correction_page(page_num)
            if not correction_file.exists():
                self.logger.error(f"Correction file not found", page=page_num, file=str(correction_file))
                return False, 0, False

            with open(correction_file, 'r') as f:
                correction_data = json.load(f)
            correction_page = CorrectionOutput(**correction_data)

            # Load label data
            label_file = storage.merge.label_page(page_num)
            if not label_file.exists():
                self.logger.error(f"Label file not found", page=page_num, file=str(label_file))
                return False, 0, False

            with open(label_file, 'r') as f:
                label_data = json.load(f)
            label_page = LabelOutput(**label_data)

            # Merge page data (three-way merge)
            merged_page, corrections_used, has_continuation = self._merge_page_data(ocr_page, correction_page, label_page)

            # Save output (handles atomic write + checkpoint atomically)
            storage.merge.save_page(
                page_num=page_num,
                data=merged_page,
                cost_usd=0.0
            )

            return True, corrections_used, has_continuation

        except Exception as e:
            if self.logger:
                self.logger.error(f"Page merge failed", page=page_num, error=str(e))
            return False, 0, False

    def _merge_page_data(self, ocr_page: OCRPageOutput, correction_page: CorrectionOutput, label_page: LabelOutput) -> Tuple[Dict, int, bool]:
        """Merge OCR, correction, and label data for a single page (three-way merge).

        Args:
            ocr_page: OCR page output (original text, bboxes)
            correction_page: Correction page output (corrected text, sparse)
            label_page: Label page output (classifications, page numbers)

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
                self.logger.warning(
                    f"No correction block found for OCR block",
                    page=ocr_page.page_number,
                    block_num=ocr_block.block_num
                )
                continue

            if not label_block:
                self.logger.warning(
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

                # Find matching label paragraph (for confidence)
                label_para = next(
                    (lp for lp in label_block.paragraphs if lp.par_num == ocr_para.par_num),
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
                    "bbox": ocr_para.bbox.to_list(),
                    "original_confidence": ocr_para.avg_confidence,
                    "correction_applied": correction_applied,
                    "correction_confidence": corr_para.confidence if corr_para else 1.0,
                    "correction_notes": corr_para.notes if corr_para and corr_para.notes else None
                })

            # Use classification from label_block
            merged_blocks.append({
                "block_num": ocr_block.block_num,
                "classification": label_block.classification.value if label_block.classification else "OTHER",
                "classification_confidence": label_block.classification_confidence,
                "bbox": ocr_block.bbox.to_list(),
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
        """Detect if page text continues to/from other pages.

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

    def clean_stage(self, scan_id: str, confirm: bool = False) -> bool:
        """Clean merge outputs and checkpoint for a book.

        Args:
            scan_id: Book scan ID
            confirm: Must be True to actually delete files

        Returns:
            True if cleaned, False if not confirmed
        """
        # Use BookStorage clean_stage method
        storage = BookStorage(scan_id=scan_id, storage_root=self.storage_root)
        return storage.merge.clean_stage(confirm=confirm)
