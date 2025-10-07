#!/usr/bin/env python3
"""
Extractor Orchestrator - Phase 1 of Structure Stage

Coordinates sliding window extraction using the 3-agent pattern:
1. Create overlapping batches (3 pages, 1 overlap)
2. Process batches in parallel (30 workers)
3. Extract → Verify (full LLM) → Reconcile for each batch
4. Aggregate results with overlap reconciliation

Expected performance (636-page book):
- Batches: ~318 (window_size=3, overlap=1, stride=2)
- Runtime: ~5-7 minutes
- Cost: ~$3.18 (~$0.01 per 3-page batch)

Note: 3-page batches provide better reliability (shorter JSON responses)
and enable full-text verification within LLM context limits.
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from logger import create_logger
from utils.parallel import ParallelProcessor
from pipeline.structure.agents import (
    extract_batch,
    verify_extraction,
    reconcile_overlaps
)


class ExtractionOrchestrator:
    """
    Orchestrates sliding window extraction with 3-agent verification.

    Main workflow:
    1. Create batches with overlap
    2. Process batches in parallel
    3. Each batch: extract → verify → track
    4. Reconcile overlaps between consecutive batches
    """

    def __init__(
        self,
        scan_id: str,
        storage_root: Optional[Path] = None,
        window_size: int = 10,
        overlap: int = 3,
        max_workers: int = 30,
        logger=None
    ):
        """
        Initialize extractor orchestrator.

        Args:
            scan_id: Book scan ID
            storage_root: Root directory for book storage
            window_size: Pages per batch (default: 10)
            overlap: Pages of overlap between batches (default: 3)
            max_workers: Parallel workers (default: 30)
            logger: Optional logger instance
        """
        self.scan_id = scan_id
        self.storage_root = Path(storage_root or Path.home() / "Documents" / "book_scans")
        self.book_dir = self.storage_root / scan_id
        self.corrected_dir = self.book_dir / "corrected"
        self.logs_dir = self.book_dir / "logs"

        # Sliding window parameters
        self.window_size = window_size
        self.overlap = overlap
        self.stride = window_size - overlap  # Pages to advance per batch
        self.max_workers = max_workers

        # Create directories
        self.logs_dir.mkdir(exist_ok=True)

        # Logger
        self.logger = logger or create_logger(scan_id, "extraction", log_dir=self.logs_dir)

        # Statistics
        self.stats = {
            'total_batches': 0,
            'processed_batches': 0,
            'failed_batches': 0,
            'total_pages': 0,
            'total_word_count': 0,
            'total_cost': 0.0,
            'verification_issues': 0,
            'reconciliation_disagreements': 0
        }

    def load_pages(self, start_page: int, end_page: int) -> List[Dict]:
        """
        Load corrected pages from disk.

        Args:
            start_page: First page to load
            end_page: Last page to load (inclusive)

        Returns:
            List of page dicts
        """
        pages = []

        for page_num in range(start_page, end_page + 1):
            page_file = self.corrected_dir / f"page_{page_num:04d}.json"

            if not page_file.exists():
                self.logger.warning(f"Page file not found: {page_file}", page=page_num)
                continue

            with open(page_file, 'r', encoding='utf-8') as f:
                page_data = json.load(f)

            pages.append(page_data)

        return pages

    def create_batches(self, total_pages: int, start_page: int = 1, end_page: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Create overlapping batches using sliding window.

        Args:
            total_pages: Total pages in book
            start_page: First page to process
            end_page: Last page to process (None = all pages)

        Returns:
            List of batch metadata dicts with:
            - batch_id: Sequential batch number
            - start_page: First page in batch
            - end_page: Last page in batch
            - overlap_with_prev: Pages that overlap with previous batch
        """
        if end_page is None:
            end_page = total_pages

        batches = []
        batch_id = 0
        current_page = start_page
        prev_batch_end = None

        while current_page <= end_page:
            batch_start = current_page
            batch_end = min(current_page + self.window_size - 1, end_page)

            # Determine overlap with previous batch
            overlap_pages = []
            if prev_batch_end is not None:
                # Overlap is the last N pages of previous batch = first N pages of current batch
                overlap_start = max(batch_start, prev_batch_end - self.overlap + 1)
                overlap_end = min(prev_batch_end, batch_end)
                overlap_pages = list(range(overlap_start, overlap_end + 1))

            batches.append({
                'batch_id': batch_id,
                'start_page': batch_start,
                'end_page': batch_end,
                'overlap_with_prev': overlap_pages,
                'page_count': batch_end - batch_start + 1
            })

            batch_id += 1
            prev_batch_end = batch_end
            current_page += self.stride

            # Stop if we've covered the last page
            if batch_end >= end_page:
                break

        return batches

    def process_batch(self, batch_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single batch: extract → verify.

        This is the worker function for parallel processing.

        Args:
            batch_metadata: Batch metadata from create_batches

        Returns:
            Dict with:
            - result: extraction result from extract_agent
            - verification: verification result from verify_agent
            - cost: total cost for this batch
            - batch_metadata: original metadata
        """
        batch_id = batch_metadata['batch_id']
        start_page = batch_metadata['start_page']
        end_page = batch_metadata['end_page']

        try:
            # Load pages for this batch
            pages = self.load_pages(start_page, end_page)

            if not pages:
                raise ValueError(f"No pages loaded for batch {batch_id}")

            # Step 1: Extract clean text
            extraction_result = extract_batch(pages)

            # Step 2: Verify extraction quality
            # Use full LLM verification (compares complete original vs extracted text)
            verification_result = verify_extraction(pages, extraction_result)

            # Calculate cost estimate
            # - extract_batch: ~$0.003-0.005 per 3-page batch (gpt-4o-mini)
            # - verify_extraction: ~$0.003-0.005 per 3-page batch (gpt-4o-mini)
            # Total: ~$0.01 per batch
            cost_estimate = 0.01

            return {
                'batch_id': batch_id,
                'result': extraction_result,
                'verification': verification_result,
                'cost': cost_estimate,
                'status': 'success',
                'batch_metadata': batch_metadata
            }

        except Exception as e:
            self.logger.error(
                f"Batch {batch_id} failed",
                batch_id=batch_id,
                start_page=start_page,
                end_page=end_page,
                error=str(e)
            )

            return {
                'batch_id': batch_id,
                'status': 'failed',
                'error': str(e),
                'cost': 0.0,
                'batch_metadata': batch_metadata
            }

    def reconcile_consecutive_batches(
        self,
        batch_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Reconcile overlaps between consecutive batches.

        Args:
            batch_results: List of batch results sorted by batch_id

        Returns:
            Same list with reconciliation info added
        """
        if len(batch_results) <= 1:
            return batch_results

        for i in range(1, len(batch_results)):
            curr_batch = batch_results[i]
            prev_batch = batch_results[i - 1]

            # Skip if either batch failed
            if curr_batch.get('status') != 'success' or prev_batch.get('status') != 'success':
                continue

            # Get overlap pages
            overlap_pages = curr_batch['batch_metadata'].get('overlap_with_prev', [])

            if not overlap_pages:
                continue

            # Reconcile
            reconciliation = reconcile_overlaps(
                prev_batch['result'],
                curr_batch['result'],
                overlap_pages
            )

            # Store reconciliation info
            curr_batch['reconciliation'] = reconciliation

            # Track disagreements
            if reconciliation.get('status') == 'disagreement':
                self.stats['reconciliation_disagreements'] += 1
                self.logger.warning(
                    f"Batch {curr_batch['batch_id']} overlap disagreement",
                    batch_id=curr_batch['batch_id'],
                    overlap_pages=overlap_pages,
                    similarity=reconciliation.get('similarity'),
                    resolution=reconciliation.get('resolution_method')
                )

        return batch_results

    def extract_sliding_window(
        self,
        start_page: int = 1,
        end_page: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Main entry point: Extract clean text using sliding window + 3-agent pattern.

        Args:
            start_page: First page to process
            end_page: Last page to process (None = all pages)

        Returns:
            List of batch results with reconciled overlaps
        """
        # Determine total pages
        page_files = sorted(self.corrected_dir.glob("page_*.json"))
        total_pages = len(page_files)

        if total_pages == 0:
            raise ValueError(f"No corrected pages found in {self.corrected_dir}")

        if end_page is None:
            end_page = total_pages

        # Create batches
        batches = self.create_batches(total_pages, start_page, end_page)
        self.stats['total_batches'] = len(batches)
        self.stats['total_pages'] = end_page - start_page + 1

        self.logger.info(
            f"Starting extraction: {len(batches)} batches, {self.stats['total_pages']} pages",
            total_batches=len(batches),
            total_pages=self.stats['total_pages'],
            window_size=self.window_size,
            overlap=self.overlap,
            stride=self.stride,
            workers=self.max_workers
        )

        # Process batches in parallel
        processor = ParallelProcessor(
            max_workers=self.max_workers,
            rate_limit=None,  # No rate limit needed (agents handle it internally)
            logger=self.logger,
            description="Processing batches"
        )

        batch_results = processor.process(
            items=batches,
            worker_func=self.process_batch,
            progress_interval=5  # Log every 5 batches
        )

        # Sort results by batch_id to ensure correct order
        batch_results.sort(key=lambda x: x.get('batch_id', 0))

        # Update statistics
        for result in batch_results:
            if result.get('status') == 'success':
                self.stats['processed_batches'] += 1
                self.stats['total_cost'] += result.get('cost', 0.0)

                extraction = result.get('result', {})
                self.stats['total_word_count'] += extraction.get('word_count', 0)

                verification = result.get('verification', {})
                if not verification.get('word_count_ok', True):
                    self.stats['verification_issues'] += 1
            else:
                self.stats['failed_batches'] += 1

        # Reconcile overlaps between consecutive batches
        batch_results = self.reconcile_consecutive_batches(batch_results)

        # Log summary
        self.logger.info(
            "Extraction complete",
            total_batches=self.stats['total_batches'],
            processed_batches=self.stats['processed_batches'],
            failed_batches=self.stats['failed_batches'],
            total_pages=self.stats['total_pages'],
            total_word_count=self.stats['total_word_count'],
            verification_issues=self.stats['verification_issues'],
            reconciliation_disagreements=self.stats['reconciliation_disagreements'],
            total_cost=self.stats['total_cost']
        )

        print(f"\n{'='*60}")
        print("📊 Extraction Complete")
        print(f"{'='*60}")
        print(f"Batches: {self.stats['processed_batches']}/{self.stats['total_batches']} succeeded")
        print(f"Pages processed: {self.stats['total_pages']}")
        print(f"Total words extracted: {self.stats['total_word_count']:,}")
        print(f"Verification issues: {self.stats['verification_issues']}")
        print(f"Overlap disagreements: {self.stats['reconciliation_disagreements']}")
        print(f"Total cost: ${self.stats['total_cost']:.2f}")
        print(f"{'='*60}\n")

        return batch_results


def main():
    """CLI entry point for testing."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Extract clean text from corrected pages using sliding window',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process full book
  python pipeline/structure/extractor.py roosevelt-autobiography

  # Process page range (for testing)
  python pipeline/structure/extractor.py roosevelt-autobiography --start 75 --end 90

  # Adjust batch size
  python pipeline/structure/extractor.py roosevelt-autobiography --window 10 --overlap 3

Default configuration:
  - Window size: 10 pages
  - Overlap: 3 pages
  - Stride: 7 pages
  - Workers: 30

Expected cost: ~$0.80 for 636-page book
Expected time: 2-3 minutes
        """
    )

    parser.add_argument('scan_id', help='Scan ID (e.g., roosevelt-autobiography)')
    parser.add_argument('--start', type=int, default=1, help='Start page (default: 1)')
    parser.add_argument('--end', type=int, default=None, help='End page (default: all)')
    parser.add_argument('--window', type=int, default=10, help='Window size (default: 10)')
    parser.add_argument('--overlap', type=int, default=3, help='Overlap pages (default: 3)')
    parser.add_argument('--workers', type=int, default=30, help='Max workers (default: 30)')
    parser.add_argument('--output', type=Path, help='Save results to JSON file')

    args = parser.parse_args()

    print(f"📊 Configuration:")
    print(f"   Scan ID: {args.scan_id}")
    print(f"   Page range: {args.start}-{args.end or 'end'}")
    print(f"   Window: {args.window} pages, overlap: {args.overlap}")
    print(f"   Workers: {args.workers}")
    print()

    # Run extraction
    orchestrator = ExtractionOrchestrator(
        scan_id=args.scan_id,
        window_size=args.window,
        overlap=args.overlap,
        max_workers=args.workers
    )

    results = orchestrator.extract_sliding_window(
        start_page=args.start,
        end_page=args.end
    )

    # Save results if requested
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        print(f"✓ Results saved to {args.output}")


if __name__ == "__main__":
    main()
