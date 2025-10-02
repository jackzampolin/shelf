#!/usr/bin/env python3
"""
Multi-Phase Book Structure Analysis

Main orchestrator for the book structuring pipeline.
Coordinates all phases and generates three output formats.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline.structure.loader import PageLoader
from pipeline.structure.detector import StructureDetector
from pipeline.structure.extractor import ContentExtractor
from pipeline.structure.generator import OutputGenerator
from logger import create_logger


class BookStructurer:
    """
    Main orchestrator for multi-phase book structuring.

    Coordinates all phases:
    1. Load pages
    2. Detect document structure (Claude)
    3. Extract page numbers (GPT-4o-mini, parallel)
    4. Extract footnotes (GPT-4o-mini)
    5. Parse bibliography (GPT-4o-mini)
    6. Generate three outputs (Python)
    """

    def __init__(self, book_slug: str, storage_root: Path = None, model: str = None):
        self.book_slug = book_slug
        self.storage_root = storage_root or (Path.home() / "Documents" / "book_scans")
        self.book_dir = self.storage_root / book_slug
        self.model = model  # Store model for use by sub-modules

        # Initialize logger
        logs_dir = self.book_dir / "logs"
        logs_dir.mkdir(exist_ok=True, parents=True)
        self.logger = create_logger(book_slug, "structure", log_dir=logs_dir)

        # Initialize phase handlers
        self.loader = PageLoader(self.book_dir)
        self.detector = StructureDetector(model=model)
        self.extractor = ContentExtractor()
        self.generator = OutputGenerator(self.book_dir)

        # Pass logger to sub-modules
        self.detector.logger = self.logger
        self.extractor.logger = self.logger
        self.generator.logger = self.logger

        # Shared data
        self.pages = []
        self.document_map = {}
        self.page_mapping = []
        self.footnotes = []
        self.bibliography = []

        # Stats tracking
        self.stats = {
            "pages_loaded": 0,
            "chapters_detected": 0,
            "front_matter_sections": 0,
            "back_matter_sections": 0,
            "page_numbers_extracted": 0,
            "footnotes_extracted": 0,
            "bibliography_entries": 0,
            "total_cost_usd": 0.0,
            "phase_costs": {},
            "input_tokens": 0,
            "output_tokens": 0
        }

    def process_book(self):
        """Run complete multi-phase structuring pipeline."""
        self.logger.start_stage(book=self.book_slug, version="v2.0")

        print("="*70)
        print("📚 Multi-Phase Book Structuring Pipeline v2.0")
        print(f"   Book: {self.book_slug}")
        print("="*70)

        # Phase 0: Load pages
        self.logger.info("Phase 0: Loading pages", phase=0, phase_name="load")
        self.pages = self.loader.load_pages()
        self.stats['pages_loaded'] = len(self.pages)
        self.logger.info(f"Loaded {len(self.pages)} pages", phase=0, pages_loaded=len(self.pages))

        # Phase 1-2: Document structure detection (Claude Sonnet 4.5)
        self.logger.info("Phase 1-2: Detecting document structure", phase=1, phase_name="structure")
        result = self.detector.detect_structure(self.pages)
        self.document_map = result['document_map']
        self.stats['chapters_detected'] = len(result['chapters'])
        self.stats['front_matter_sections'] = len(result['front_matter_sections'])
        self.stats['back_matter_sections'] = len(result['back_matter_sections'])
        self.stats['phase_costs']['phase_1_2_structure'] = result['cost']
        self.stats['input_tokens'] += result['usage'].get('prompt_tokens', 0)
        self.stats['output_tokens'] += result['usage'].get('completion_tokens', 0)
        self.stats['total_cost_usd'] += result['cost']
        self.logger.info(
            "Phase 1-2 complete",
            phase=1,
            chapters=len(result['chapters']),
            front_matter=len(result['front_matter_sections']),
            back_matter=len(result['back_matter_sections']),
            cost_usd=result['cost']
        )

        # Phase 3: Page number extraction (GPT-4o-mini, parallel)
        self.logger.info("Phase 3: Extracting page numbers", phase=3, phase_name="page_numbers")
        result = self.extractor.extract_page_numbers(
            self.pages,
            self.document_map
        )
        self.page_mapping = result['page_mapping']
        self.stats['page_numbers_extracted'] = result['count']
        self.stats['phase_costs']['phase_3_page_numbers'] = result['cost']
        self.stats['total_cost_usd'] += result['cost']
        self.logger.info("Phase 3 complete", phase=3, page_numbers_extracted=result['count'], cost_usd=result['cost'])

        # Phase 6: Footnote extraction (GPT-4o-mini)
        self.logger.info("Phase 6: Extracting footnotes", phase=6, phase_name="footnotes")
        result = self.extractor.extract_footnotes(
            self.pages,
            self.document_map
        )
        self.footnotes = result['footnotes']
        self.stats['footnotes_extracted'] = len(self.footnotes)
        self.stats['phase_costs']['phase_6_footnotes'] = result['cost']
        self.stats['total_cost_usd'] += result['cost']
        self.logger.info("Phase 6 complete", phase=6, footnotes_extracted=len(self.footnotes), cost_usd=result['cost'])

        # Phase 7: Bibliography parsing (GPT-4o-mini)
        self.logger.info("Phase 7: Parsing bibliography", phase=7, phase_name="bibliography")
        result = self.extractor.parse_bibliography(
            self.pages,
            self.document_map
        )
        self.bibliography = result['bibliography']
        self.stats['bibliography_entries'] = len(self.bibliography)
        self.stats['phase_costs']['phase_7_bibliography'] = result['cost']
        self.stats['total_cost_usd'] += result['cost']
        self.logger.info("Phase 7 complete", phase=7, bibliography_entries=len(self.bibliography), cost_usd=result['cost'])

        # Phase 8: Generate outputs
        self.logger.info("Phase 8: Generating outputs", phase=8, phase_name="output_generation")
        self.generator.generate_all_outputs(
            pages=self.pages,
            document_map=self.document_map,
            page_mapping=self.page_mapping,
            footnotes=self.footnotes,
            bibliography=self.bibliography,
            stats=self.stats
        )

        # Print summary
        self._print_summary()

        # Log completion
        self.logger.info(
            "Multi-phase book structuring complete",
            **self.stats
        )

    def _print_summary(self):
        """Print processing summary."""
        print("\n" + "="*70)
        print("✅ Multi-Phase Book Structuring Complete")
        print("="*70)
        print(f"\n📊 Summary:")
        print(f"   Pages loaded: {self.stats['pages_loaded']}")
        print(f"   Chapters detected: {self.stats['chapters_detected']}")
        print(f"   Front matter sections: {self.stats['front_matter_sections']}")
        print(f"   Back matter sections: {self.stats['back_matter_sections']}")
        print(f"   Page numbers extracted: {self.stats['page_numbers_extracted']}")
        print(f"   Footnotes extracted: {self.stats['footnotes_extracted']}")
        print(f"   Bibliography entries: {self.stats['bibliography_entries']}")
        print(f"\n💰 Costs by phase:")
        for phase, cost in self.stats.get('phase_costs', {}).items():
            print(f"   {phase}: ${cost:.4f}")
        print(f"   Total: ${self.stats['total_cost_usd']:.4f}")
        print(f"\n📁 Output: {self.book_dir}/structured/")
        print(f"   - reading/ (TTS-optimized)")
        print(f"   - data/ (RAG/analysis)")
        print(f"   - archive/ (complete markdown)")
        print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.structure <scan-id>")
        print("Example: python -m pipeline.structure modest-lovelace")
        sys.exit(1)

    book_slug = sys.argv[1]

    structurer = BookStructurer(book_slug)
    structurer.process_book()


if __name__ == "__main__":
    main()
