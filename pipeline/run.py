#!/usr/bin/env python3
"""
Unified Book Processing Pipeline Runner

Orchestrates all stages: OCR → Correct → Fix → Structure

Usage:
    python pipeline/run.py <book-slug> [options]

Examples:
    # Full pipeline from scratch
    python pipeline/run.py The-Accidental-President

    # Resume from correction stage
    python pipeline/run.py The-Accidental-President --start-from correct

    # Run only correction with custom settings
    python pipeline/run.py The-Accidental-President --stages correct --workers 50

    # Full pipeline with GPT-4o-mini correction and Sonnet 4 structure
    python pipeline/run.py The-Accidental-President \\
        --correct-model openai/gpt-4o-mini \\
        --structure-model anthropic/claude-sonnet-4.5
"""

import sys
import argparse
import json
from pathlib import Path
from datetime import datetime
import time
import subprocess

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class PipelineLogger:
    """Comprehensive logging for pipeline stages."""

    def __init__(self, book_slug: str, log_dir: Path):
        self.book_slug = book_slug
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"pipeline_{timestamp}.log"

        self.stats = {
            "book_slug": book_slug,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "total_duration_seconds": 0,
            "stages": {}
        }

    def log(self, message: str, level="INFO"):
        """Log to both console and file."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level}] {message}"
        print(formatted)

        with open(self.log_file, 'a') as f:
            f.write(formatted + "\n")

    def stage_start(self, stage_name: str):
        """Mark stage start."""
        self.log(f"{'='*70}")
        self.log(f"Stage: {stage_name}")
        self.log(f"{'='*70}")

        self.stats['stages'][stage_name] = {
            "status": "running",
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "duration_seconds": 0,
            "error": None
        }

    def stage_end(self, stage_name: str, success: bool = True, error: str = None):
        """Mark stage end."""
        stage = self.stats['stages'][stage_name]
        stage['end_time'] = datetime.now().isoformat()
        stage['status'] = 'success' if success else 'failed'
        stage['error'] = error

        start = datetime.fromisoformat(stage['start_time'])
        end = datetime.fromisoformat(stage['end_time'])
        stage['duration_seconds'] = (end - start).total_seconds()

        icon = "✅" if success else "❌"
        self.log(f"{icon} Stage '{stage_name}' {stage['status']} in {stage['duration_seconds']:.1f}s")
        self.log("")

    def pipeline_end(self):
        """Mark pipeline end and save report."""
        self.stats['end_time'] = datetime.now().isoformat()
        start = datetime.fromisoformat(self.stats['start_time'])
        end = datetime.fromisoformat(self.stats['end_time'])
        self.stats['total_duration_seconds'] = (end - start).total_seconds()

        # Save JSON report
        report_file = self.log_dir / f"pipeline_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(self.stats, f, indent=2)

        self.log(f"📊 Pipeline report saved: {report_file}")

    def print_summary(self):
        """Print comprehensive summary."""
        self.log("")
        self.log("="*70)
        self.log("📊 PIPELINE SUMMARY")
        self.log("="*70)
        self.log(f"Book: {self.book_slug}")
        self.log(f"Total Duration: {self.stats['total_duration_seconds']:.1f}s ({self.stats['total_duration_seconds']/60:.1f}m)")
        self.log("")
        self.log("Stages:")

        for stage_name, stage_data in self.stats['stages'].items():
            status_icon = "✅" if stage_data['status'] == 'success' else "❌"
            duration = stage_data['duration_seconds']
            self.log(f"  {status_icon} {stage_name}: {duration:.1f}s")
            if stage_data.get('error'):
                self.log(f"      Error: {stage_data['error']}")

        self.log("")
        self.log(f"Log file: {self.log_file}")
        self.log("="*70)


class BookPipeline:
    """Unified book processing pipeline."""

    def __init__(self, book_slug: str, storage_root: Path = None):
        self.book_slug = book_slug
        self.storage_root = storage_root or Path.home() / "Documents" / "book_scans"
        self.book_dir = self.storage_root / book_slug
        self.logs_dir = self.book_dir / "logs"

        self.logger = PipelineLogger(book_slug, self.logs_dir)

        # Verify book exists
        if not self.book_dir.exists():
            raise ValueError(f"Book directory not found: {self.book_dir}")

        metadata_file = self.book_dir / "metadata.json"
        if not metadata_file.exists():
            raise ValueError(f"Metadata not found: {metadata_file}")

        with open(metadata_file) as f:
            self.metadata = json.load(f)

    def run_stage_ocr(self, max_workers: int = 8):
        """Stage 1: OCR extraction."""
        self.logger.stage_start("ocr")

        # Check if already complete
        ocr_dir = self.book_dir / "ocr"
        if ocr_dir.exists() and len(list(ocr_dir.glob("page_*.json"))) > 0:
            existing_pages = len(list(ocr_dir.glob("page_*.json")))
            expected_pages = self.metadata.get('total_pages', 0)

            if existing_pages >= expected_pages * 0.95:  # Allow 5% missing for front/back matter
                self.logger.log(f"OCR already complete ({existing_pages} pages), skipping...")
                self.logger.stage_end("ocr", success=True)
                return True

        try:
            # Import and run OCR
            from pipeline.ocr import BookOCRProcessor

            processor = BookOCRProcessor(storage_root=str(self.storage_root), max_workers=max_workers)
            processor.process_book(self.book_slug)

            # Track OCR completion (free, no cost)
            from utils import update_book_metadata
            update_book_metadata(self.book_dir, 'ocr', {
                'model': 'tesseract',
                'pages_processed': processor.total_pages if hasattr(processor, 'total_pages') else 0,
                'cost_usd': 0.0  # OCR is free
            })

            self.logger.stage_end("ocr", success=True)
            return True

        except Exception as e:
            self.logger.log(f"OCR stage failed: {e}", level="ERROR")
            self.logger.stage_end("ocr", success=False, error=str(e))
            return False

    def run_stage_correct(self, model: str = "openai/gpt-4o-mini",
                          max_workers: int = 30, rate_limit: int = 150):
        """Stage 2: LLM correction."""
        self.logger.stage_start("correct")

        try:
            # Import and run correction
            from pipeline.correct import StructuredPageCorrector

            processor = StructuredPageCorrector(
                self.book_slug,
                storage_root=str(self.storage_root),
                model=model,
                max_workers=max_workers,
                calls_per_minute=rate_limit
            )
            processor.process_pages()

            # Log cost from correction stats
            if hasattr(processor, 'stats'):
                cost = processor.stats.get('total_cost_usd', 0)
                self.logger.log(f"Correction cost: ${cost:.4f}")

                # Persist to metadata
                from utils import update_book_metadata
                update_book_metadata(self.book_dir, 'correct', {
                    'model': correct_model,
                    'pages_processed': processor.stats.get('pages_processed', 0),
                    'total_errors_found': processor.stats.get('total_errors', 0),
                    'cost_usd': cost
                })

            self.logger.stage_end("correct", success=True)
            return True

        except Exception as e:
            self.logger.log(f"Correction stage failed: {e}", level="ERROR")
            self.logger.stage_end("correct", success=False, error=str(e))
            return False

    def run_stage_fix(self):
        """Stage 3: Agent 4 targeted fixes."""
        self.logger.stage_start("fix")

        # Check if there are pages to fix
        needs_review_dir = self.book_dir / "needs_review"
        if not needs_review_dir.exists() or not list(needs_review_dir.glob("page_*.json")):
            self.logger.log("No pages need review, skipping fix stage...")
            self.logger.stage_end("fix", success=True)
            return True

        try:
            # Import and run fix
            from pipeline.fix import Agent4TargetedFix

            agent4 = Agent4TargetedFix(self.book_slug)
            agent4.process_all_flagged()

            # Log cost from agent4 stats
            if hasattr(agent4, 'stats'):
                cost = agent4.stats.get('total_cost_usd', 0)
                self.logger.log(f"Fix cost: ${cost:.4f}")

                # Persist to metadata
                from utils import update_book_metadata
                update_book_metadata(self.book_dir, 'fix', {
                    'model': agent4.model,
                    'pages_fixed': agent4.stats.get('pages_fixed', 0),
                    'cost_usd': cost
                })

            self.logger.stage_end("fix", success=True)
            return True

        except Exception as e:
            self.logger.log(f"Fix stage failed: {e}", level="ERROR")
            self.logger.stage_end("fix", success=False, error=str(e))
            return False

    def run_stage_structure(self, model: str = "anthropic/claude-sonnet-4.5"):
        """Stage 4: Semantic structuring."""
        self.logger.stage_start("structure")

        try:
            # Import and run structure
            from pipeline.structure import DeepBookStructurer

            structurer = DeepBookStructurer(self.book_slug, model=model)
            structurer.process_book()

            # Log cost from structurer stats
            if hasattr(structurer, 'stats'):
                cost = structurer.stats.get('total_cost_usd', 0)
                self.logger.log(f"Structure cost: ${cost:.4f}")

                # Persist to metadata
                from utils import update_book_metadata
                update_book_metadata(self.book_dir, 'structure', {
                    'model': model,
                    'chapters_detected': structurer.stats.get('chapters_detected', 0),
                    'chunks_created': structurer.stats.get('chunks_created', 0),
                    'paragraphs_created': structurer.stats.get('paragraphs_created', 0),
                    'cost_usd': cost
                })

            self.logger.stage_end("structure", success=True)
            return True

        except Exception as e:
            self.logger.log(f"Structure stage failed: {e}", level="ERROR")
            self.logger.stage_end("structure", success=False, error=str(e))
            return False

    def run(self, stages: list = None, start_from: str = None,
            ocr_workers: int = 8,
            correct_model: str = "openai/gpt-4o-mini",
            correct_workers: int = 30,
            correct_rate_limit: int = 150,
            structure_model: str = "anthropic/claude-sonnet-4.5"):
        """Run the complete pipeline or selected stages."""

        available_stages = ['ocr', 'correct', 'fix', 'structure']

        # Determine which stages to run
        if stages:
            run_stages = [s for s in stages if s in available_stages]
        elif start_from:
            start_idx = available_stages.index(start_from)
            run_stages = available_stages[start_idx:]
        else:
            run_stages = available_stages

        self.logger.log("="*70)
        self.logger.log("📚 Book Processing Pipeline")
        self.logger.log("="*70)
        self.logger.log(f"Book: {self.book_slug}")
        self.logger.log(f"Stages: {', '.join(run_stages)}")
        self.logger.log(f"Correction Model: {correct_model}")
        self.logger.log(f"Structure Model: {structure_model}")
        self.logger.log("")

        # Run each stage
        success = True
        for stage in run_stages:
            if stage == 'ocr':
                success = self.run_stage_ocr(max_workers=ocr_workers)
            elif stage == 'correct':
                success = self.run_stage_correct(
                    model=correct_model,
                    max_workers=correct_workers,
                    rate_limit=correct_rate_limit
                )
            elif stage == 'fix':
                success = self.run_stage_fix()
            elif stage == 'structure':
                success = self.run_stage_structure(model=structure_model)

            if not success:
                self.logger.log(f"Pipeline stopped due to {stage} failure", level="ERROR")
                break

        # Sync costs to library.json if successful
        if success:
            try:
                from tools.library import LibraryIndex
                library = LibraryIndex()
                library.sync_scan_from_metadata(self.book_slug)
                self.logger.log("✅ Synced costs and metadata to library.json")
            except Exception as e:
                self.logger.log(f"Warning: Could not sync to library: {e}", level="WARNING")

        # Finalize
        self.logger.pipeline_end()
        self.logger.print_summary()

        return success


def main():
    parser = argparse.ArgumentParser(
        description='Unified book processing pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline from scratch
  python pipeline/run.py The-Accidental-President

  # Resume from correction stage (skip OCR)
  python pipeline/run.py The-Accidental-President --start-from correct

  # Run only specific stages
  python pipeline/run.py The-Accidental-President --stages correct fix

  # Custom models and settings
  python pipeline/run.py The-Accidental-President \\
      --correct-model openai/gpt-4o-mini \\
      --correct-workers 50 \\
      --structure-model anthropic/claude-sonnet-4.5

Stage descriptions:
  ocr      - Extract text from PDFs (Tesseract, ~10 min for 447 pages)
  correct  - 3-agent LLM correction (GPT-4o-mini, ~$0.32, 2-3 hours)
  fix      - Agent 4 targeted fixes (Claude Sonnet, ~$0.01/page flagged)
  structure- Deep semantic structuring (Claude Sonnet 4, ~$6, 10-20 min)
        """
    )

    parser.add_argument('book_slug', help='Book slug (e.g., The-Accidental-President)')

    # Stage control
    parser.add_argument('--stages', nargs='+', choices=['ocr', 'correct', 'fix', 'structure'],
                        help='Run only specific stages')
    parser.add_argument('--start-from', choices=['ocr', 'correct', 'fix', 'structure'],
                        help='Start from this stage (run all subsequent stages)')

    # OCR settings
    parser.add_argument('--ocr-workers', type=int, default=8,
                        help='OCR parallel workers (default: 8)')

    # Correction settings
    parser.add_argument('--correct-model', default='openai/gpt-4o-mini',
                        help='Correction model (default: openai/gpt-4o-mini)')
    parser.add_argument('--correct-workers', type=int, default=30,
                        help='Correction parallel workers (default: 30)')
    parser.add_argument('--correct-rate-limit', type=int, default=150,
                        help='Correction API calls/min (default: 150)')

    # Structure settings
    parser.add_argument('--structure-model', default='anthropic/claude-sonnet-4.5',
                        help='Structure model (default: anthropic/claude-sonnet-4.5)')

    args = parser.parse_args()

    # Create and run pipeline
    try:
        pipeline = BookPipeline(args.book_slug)
        success = pipeline.run(
            stages=args.stages,
            start_from=args.start_from,
            ocr_workers=args.ocr_workers,
            correct_model=args.correct_model,
            correct_workers=args.correct_workers,
            correct_rate_limit=args.correct_rate_limit,
            structure_model=args.structure_model
        )

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
