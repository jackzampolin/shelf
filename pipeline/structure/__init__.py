"""
Structure Stage - 2-Phase Architecture

Phase 1: Sliding window extraction (extractor.py)
Phase 2: Assembly & chunking (assembler.py + chunker.py + output_generator.py)
"""

from pathlib import Path
from typing import Dict, Optional
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from .extractor import ExtractionOrchestrator
from .assembler import BatchAssembler
from .chunker import SemanticChunker
from .output_generator import OutputGenerator


class BookStructurer:
    """
    Main orchestrator for structure stage.

    Runs 2-phase pipeline:
    1. Extraction (if not already done)
    2. Assembly + chunking + output generation
    """

    def __init__(self, scan_id: str, storage_root: Path = None, logger=None, enable_checkpoints: bool = True, model: str = None):
        self.scan_id = scan_id
        self.logger = logger
        self.enable_checkpoints = enable_checkpoints
        self.model = model  # Store for potential future use (currently agents are hardcoded)

        # Determine book directory
        if storage_root:
            self.book_dir = storage_root / scan_id
        else:
            self.book_dir = Path.home() / "Documents" / "book_scans" / scan_id

        if not self.book_dir.exists():
            error_msg = f"Book directory not found: {self.book_dir}"
            # Note: checkpoint not yet initialized, so can't mark failed here
            raise FileNotFoundError(error_msg)

        self.extraction_dir = self.book_dir / "structured" / "extraction"

        # Initialize checkpoint manager
        if self.enable_checkpoints:
            from checkpoint import CheckpointManager
            storage_root_path = storage_root or Path.home() / "Documents" / "book_scans"
            self.checkpoint = CheckpointManager(
                scan_id=scan_id,
                stage="structure",
                storage_root=storage_root_path,
                output_dir="structured"
            )
        else:
            self.checkpoint = None

    def process_book(self,
                    start_page: Optional[int] = None,
                    end_page: Optional[int] = None,
                    skip_extraction: bool = False) -> Dict:
        """
        Run full structure pipeline.

        Args:
            start_page: Optional start page (for testing)
            end_page: Optional end page (for testing)
            skip_extraction: Skip Phase 1 if extraction already exists

        Returns:
            Dict with statistics and costs
        """
        try:
            print("\n" + "="*70)
            print(f"📚 Structure Stage: {self.scan_id}")
            print("="*70)

            total_cost = 0.0
            statistics = {}

            # Phase 1: Extraction (if needed)
            if not skip_extraction or not self._extraction_exists():
                print("\n🔍 Running Phase 1: Extraction...")

                extractor = ExtractionOrchestrator(
                    book_dir=self.book_dir,
                    logger=self.logger
                )

                extraction_result = extractor.extract(
                    start_page=start_page,
                    end_page=end_page
                )

                total_cost += extraction_result.get('total_cost', 0.0)
                statistics['extraction'] = extraction_result.get('statistics', {})

                print(f"\n✅ Phase 1 complete: ${extraction_result.get('total_cost', 0.0):.4f}")
            else:
                print("\n✓ Phase 1: Extraction already complete (skipping)")

            # Phase 2: Assembly
            print("\n🔧 Running Phase 2: Assembly & Chunking...")

            # Step 1: Assemble batches
            assembler = BatchAssembler(
                book_dir=self.book_dir,
                logger=self.logger
            )
            assembly_result = assembler.assemble()
            statistics['assembly'] = assembly_result['statistics']

            # Build document map
            book_metadata = self._load_book_metadata()
            document_map = assembler.build_document_map(assembly_result, book_metadata)

            # Step 2: Create semantic chunks
            chunker = SemanticChunker(logger=self.logger)
            chunking_result = chunker.chunk_text(
                full_text=assembly_result['full_text'],
                paragraphs=assembly_result['paragraphs'],
                document_map=document_map
            )

            total_cost += chunking_result.get('cost', 0.0)
            statistics['chunking'] = chunking_result.get('statistics', {})

            # Step 3: Generate outputs
            generator = OutputGenerator(
                book_dir=self.book_dir,
                logger=self.logger
            )

            stats = {
                'total_cost': total_cost,
                'extraction_cost': statistics.get('extraction', {}).get('total_cost', 0.0),
                'chunking_cost': chunking_result.get('cost', 0.0)
            }

            generator.generate_all_outputs(
                assembly_result=assembly_result,
                chunking_result=chunking_result,
                document_map=document_map,
                book_metadata=book_metadata,
                stats=stats
            )

            # Mark stage complete in checkpoint (saves pending pages + sets status)
            if self.checkpoint:
                self.checkpoint.mark_stage_complete(metadata={
                    'total_cost_usd': total_cost,
                    'chunks_created': len(chunking_result.get('chunks', [])),
                    'pages_processed': assembly_result.get('statistics', {}).get('pages_covered', 0),
                    'extraction_cost_usd': statistics.get('extraction', {}).get('total_cost', 0.0),
                    'chunking_cost_usd': chunking_result.get('cost', 0.0),
                    'total_words': assembly_result.get('word_count', 0)
                })

            print(f"\n" + "="*70)
            print(f"✅ Structure Stage Complete")
            print("="*70)
            print(f"  Total cost: ${total_cost:.4f}")
            print(f"  Chunks created: {len(chunking_result.get('chunks', []))}")
            print(f"  Pages processed: {assembly_result.get('statistics', {}).get('pages_covered', 0)}")
            print(f"  Total words: {assembly_result.get('word_count', 0):,}")

            return {
                'total_cost': total_cost,
                'statistics': statistics,
                'chunks_created': len(chunking_result.get('chunks', []))
            }

        except Exception as e:
            # Mark stage as failed in checkpoint
            if self.checkpoint:
                self.checkpoint.mark_stage_failed(error=str(e))

            # Log and re-raise
            if self.logger:
                self.logger.log_event('error', f"Structure stage failed: {e}")

            print(f"\n❌ Structure stage failed: {e}")
            raise

    def _extraction_exists(self) -> bool:
        """Check if extraction results already exist."""
        if not self.extraction_dir.exists():
            return False

        metadata_file = self.extraction_dir / "metadata.json"
        return metadata_file.exists()

    def _load_book_metadata(self) -> Dict:
        """Load book metadata from library using LibraryIndex."""
        try:
            # Import here to avoid circular dependency
            from tools.library import LibraryIndex

            library = LibraryIndex(storage_root=self.book_dir.parent)
            scan_info = library.get_scan_info(self.scan_id)

            if scan_info:
                return {
                    'title': scan_info.get('title'),
                    'author': scan_info.get('author'),
                    'publisher': scan_info.get('publisher'),
                    'year': scan_info.get('year')
                }
        except Exception as e:
            if self.logger:
                self.logger.log_event('warning', f"Could not load book metadata: {e}")

        # Fallback to empty metadata
        return {}


# Export agents for use in tests
from .agents import (
    extract_batch,
    verify_extraction,
    reconcile_overlaps
)

__all__ = [
    'BookStructurer',
    'extract_batch',
    'verify_extraction',
    'reconcile_overlaps'
]
