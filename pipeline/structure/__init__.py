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

    def __init__(self, book_slug: str, storage_root: Path = None):
        self.book_slug = book_slug
        self.storage_root = storage_root or (Path.home() / "Documents" / "book_scans")
        self.book_dir = self.storage_root / book_slug

        # Initialize phase handlers
        self.loader = PageLoader(self.book_dir)
        self.detector = StructureDetector()
        self.extractor = ContentExtractor()
        self.generator = OutputGenerator(self.book_dir)

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
        print("="*70)
        print("📚 Multi-Phase Book Structuring Pipeline v2.0")
        print(f"   Book: {self.book_slug}")
        print("="*70)

        # Phase 0: Load pages
        self.pages = self.loader.load_pages()
        self.stats['pages_loaded'] = len(self.pages)

        # Phase 1-2: Document structure detection (Claude Sonnet 4.5)
        result = self.detector.detect_structure(self.pages)
        self.document_map = result['document_map']
        self.stats['chapters_detected'] = len(result['chapters'])
        self.stats['front_matter_sections'] = len(result['front_matter_sections'])
        self.stats['back_matter_sections'] = len(result['back_matter_sections'])
        self.stats['phase_costs']['phase_1_2_structure'] = result['cost']
        self.stats['input_tokens'] += result['usage'].get('prompt_tokens', 0)
        self.stats['output_tokens'] += result['usage'].get('completion_tokens', 0)
        self.stats['total_cost_usd'] += result['cost']

        # Phase 3: Page number extraction (GPT-4o-mini, parallel)
        result = self.extractor.extract_page_numbers(
            self.pages,
            self.document_map
        )
        self.page_mapping = result['page_mapping']
        self.stats['page_numbers_extracted'] = result['count']
        self.stats['phase_costs']['phase_3_page_numbers'] = result['cost']
        self.stats['total_cost_usd'] += result['cost']

        # Phase 6: Footnote extraction (GPT-4o-mini)
        result = self.extractor.extract_footnotes(
            self.pages,
            self.document_map
        )
        self.footnotes = result['footnotes']
        self.stats['footnotes_extracted'] = len(self.footnotes)
        self.stats['phase_costs']['phase_6_footnotes'] = result['cost']
        self.stats['total_cost_usd'] += result['cost']

        # Phase 7: Bibliography parsing (GPT-4o-mini)
        result = self.extractor.parse_bibliography(
            self.pages,
            self.document_map
        )
        self.bibliography = result['bibliography']
        self.stats['bibliography_entries'] = len(self.bibliography)
        self.stats['phase_costs']['phase_7_bibliography'] = result['cost']
        self.stats['total_cost_usd'] += result['cost']

        # Phase 8: Generate outputs
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
