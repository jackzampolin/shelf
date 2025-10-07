#!/usr/bin/env python3
"""
Batch Assembler - Phase 2, Step 1

Merges extraction batches into complete book text with:
- Reconciled overlap handling
- Bottom-up chapter discovery
- Provenance tracking (text → pages)
"""

import json
from pathlib import Path
from typing import List, Dict, Tuple
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class BatchAssembler:
    """Assembles extraction batches into complete book text."""

    def __init__(self, book_dir: Path, logger=None):
        self.book_dir = book_dir
        self.extraction_dir = book_dir / "structured" / "extraction"
        self.logger = logger

    def assemble(self) -> Dict:
        """
        Assemble all batches into complete book text with metadata.

        Returns:
            Dict with:
                - full_text: Complete merged text
                - paragraphs: List of paragraph dicts with provenance
                - chapter_markers: Aggregated chapter evidence
                - footnotes: Aggregated footnotes
                - page_coverage: Set of covered pages
                - word_count: Total words
                - statistics: Assembly stats
        """
        print("\n" + "="*70)
        print("🔧 Phase 2.1: Batch Assembly")
        print("="*70)

        # Load metadata
        metadata = self._load_metadata()
        total_batches = metadata.get('statistics', {}).get('processed_batches', 0)

        if total_batches == 0:
            raise Exception("No processed batches found in extraction metadata")

        print(f"\n📊 Loading {total_batches} batches from {self.extraction_dir.name}/")

        # Load all batches
        batches = self._load_batches(total_batches)
        print(f"  ✓ Loaded {len(batches)} batches")

        # Merge batches with overlap reconciliation
        merged_text, paragraphs, page_coverage = self._merge_batches(batches)
        print(f"  ✓ Merged {len(batches)} batches → {len(merged_text.split())} words")

        # Aggregate chapter markers from all batches
        chapter_markers = self._aggregate_chapter_markers(batches)
        if chapter_markers:
            print(f"  ✓ Found {len(chapter_markers)} chapter markers")
        else:
            print(f"  ℹ️  No chapter markers found (may be in front/back matter)")

        # Aggregate footnotes
        footnotes = self._aggregate_footnotes(batches)
        if footnotes:
            print(f"  ✓ Found {len(footnotes)} footnotes")

        # Calculate statistics
        word_count = len(merged_text.split())
        statistics = {
            'total_batches': len(batches),
            'total_paragraphs': len(paragraphs),
            'page_coverage': sorted(list(page_coverage)),
            'pages_covered': len(page_coverage),
            'word_count': word_count,
            'chapter_markers_found': len(chapter_markers),
            'footnotes_found': len(footnotes)
        }

        print(f"\n📈 Assembly Statistics:")
        print(f"  • Pages covered: {statistics['pages_covered']}")
        print(f"  • Total words: {statistics['word_count']:,}")
        print(f"  • Paragraphs: {statistics['total_paragraphs']}")
        print(f"  • Avg words/page: {word_count / statistics['pages_covered']:.0f}")

        return {
            'full_text': merged_text,
            'paragraphs': paragraphs,
            'chapter_markers': chapter_markers,
            'footnotes': footnotes,
            'page_coverage': page_coverage,
            'word_count': word_count,
            'statistics': statistics
        }

    def _load_metadata(self) -> Dict:
        """Load extraction metadata."""
        metadata_path = self.extraction_dir / "metadata.json"

        if not metadata_path.exists():
            raise FileNotFoundError(
                f"Extraction metadata not found: {metadata_path}\n"
                "Run extraction phase first!"
            )

        with open(metadata_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _load_batches(self, total_batches: int) -> List[Dict]:
        """Load all batch files in order."""
        batches = []

        for batch_id in range(total_batches):
            batch_file = self.extraction_dir / f"batch_{batch_id:03d}.json"

            if not batch_file.exists():
                print(f"  ⚠️  Batch {batch_id} not found, skipping")
                continue

            with open(batch_file, 'r', encoding='utf-8') as f:
                batch_data = json.load(f)

            # Only include successful batches
            if batch_data.get('status') == 'success':
                batches.append(batch_data)
            else:
                print(f"  ⚠️  Batch {batch_id} failed, skipping")

        return batches

    def _merge_batches(self, batches: List[Dict]) -> Tuple[str, List[Dict], set]:
        """
        Merge batches using reconciled overlaps.

        Returns:
            Tuple of (merged_text, paragraphs_with_provenance, page_coverage)
        """
        if not batches:
            return "", [], set()

        merged_parts = []
        all_paragraphs = []
        page_coverage = set()

        for i, batch in enumerate(batches):
            batch_result = batch.get('result', {})
            batch_metadata = batch.get('batch_metadata', {})
            reconciliation = batch.get('reconciliation', {})

            # Extract batch content
            batch_pages = batch_result.get('scan_pages', [])
            batch_paragraphs = batch_result.get('paragraphs', [])

            # Track page coverage
            page_coverage.update(batch_pages)

            if i == 0:
                # First batch: include everything
                merged_parts.append(batch_result.get('clean_text', ''))
                all_paragraphs.extend(batch_paragraphs)
            else:
                # Subsequent batches: handle overlap
                overlap_pages = batch_metadata.get('overlap_with_prev', [])

                if overlap_pages and reconciliation.get('status') in ['consensus', 'llm_arbitrated']:
                    # Use reconciled overlap text
                    overlap_text = reconciliation.get('overlap_text', '')

                    # Get non-overlap content from current batch
                    non_overlap_paragraphs = [
                        p for p in batch_paragraphs
                        if p.get('scan_page') not in overlap_pages
                    ]

                    # Add reconciled overlap (only if not already in merged_parts)
                    # Since we're using stride=2, overlap should already be handled
                    # We mainly add the NEW content after the overlap

                    # Build text from non-overlap paragraphs
                    non_overlap_text = "\n\n".join(p.get('text', '') for p in non_overlap_paragraphs)

                    if non_overlap_text:
                        merged_parts.append(non_overlap_text)
                        all_paragraphs.extend(non_overlap_paragraphs)
                else:
                    # No overlap or reconciliation - just append everything
                    merged_parts.append(batch_result.get('clean_text', ''))
                    all_paragraphs.extend(batch_paragraphs)

        # Combine all parts
        merged_text = "\n\n".join(merged_parts)

        return merged_text, all_paragraphs, page_coverage

    def _aggregate_chapter_markers(self, batches: List[Dict]) -> List[Dict]:
        """
        Aggregate chapter markers from all batches.

        Builds bottom-up chapter discovery by collecting evidence
        from each batch and deduplicating.
        """
        markers_by_chapter = {}  # chapter_num -> marker info

        for batch in batches:
            batch_result = batch.get('result', {})
            batch_markers = batch_result.get('chapter_markers', [])

            for marker in batch_markers:
                chapter_num = marker.get('chapter')
                scan_page = marker.get('scan_page')

                if chapter_num is None or scan_page is None:
                    continue

                # Track first occurrence of each chapter
                if chapter_num not in markers_by_chapter:
                    markers_by_chapter[chapter_num] = {
                        'chapter': chapter_num,
                        'scan_page': scan_page,
                        'title': marker.get('title', f'Chapter {chapter_num}')
                    }
                else:
                    # Keep earliest page number for chapter start
                    if scan_page < markers_by_chapter[chapter_num]['scan_page']:
                        markers_by_chapter[chapter_num]['scan_page'] = scan_page

        # Sort by chapter number
        chapter_markers = sorted(markers_by_chapter.values(), key=lambda x: x['chapter'])

        return chapter_markers

    def _aggregate_footnotes(self, batches: List[Dict]) -> List[Dict]:
        """
        Aggregate footnotes from all batches.

        Deduplicates by (note_id, scan_page) to handle overlaps.
        """
        footnotes_dict = {}  # (note_id, scan_page) -> footnote

        for batch in batches:
            batch_result = batch.get('result', {})
            batch_footnotes = batch_result.get('footnotes', [])

            for footnote in batch_footnotes:
                note_id = footnote.get('number', footnote.get('note_id'))
                scan_page = footnote.get('scan_page')

                if note_id is None or scan_page is None:
                    continue

                # Use tuple as key for deduplication
                key = (note_id, scan_page)

                if key not in footnotes_dict:
                    footnotes_dict[key] = footnote

        # Sort by scan_page, then note_id
        footnotes = sorted(footnotes_dict.values(),
                          key=lambda x: (x.get('scan_page'), x.get('number', '')))

        return footnotes

    def build_document_map(self, assembly_result: Dict, book_metadata: Dict = None) -> Dict:
        """
        Build document map from assembly results.

        Uses chapter markers to construct chapter boundaries (bottom-up).

        Args:
            assembly_result: Result from assemble()
            book_metadata: Optional book metadata (title, author, etc.)

        Returns:
            Document map dict suitable for output generation
        """
        chapter_markers = assembly_result['chapter_markers']
        page_coverage = sorted(list(assembly_result['page_coverage']))

        # Build chapters with page ranges
        chapters = []

        if chapter_markers:
            for i, marker in enumerate(chapter_markers):
                chapter_num = marker['chapter']
                start_page = marker['scan_page']

                # End page is start of next chapter, or last page
                if i + 1 < len(chapter_markers):
                    end_page = chapter_markers[i + 1]['scan_page'] - 1
                else:
                    end_page = page_coverage[-1]

                chapters.append({
                    'number': chapter_num,
                    'title': marker.get('title', f'Chapter {chapter_num}'),
                    'start_page': start_page,
                    'end_page': end_page
                })

        # Build document map
        document_map = {
            'book': book_metadata or {},
            'body': {
                'chapters': chapters
            },
            'page_range': {
                'first': page_coverage[0] if page_coverage else None,
                'last': page_coverage[-1] if page_coverage else None,
                'total': len(page_coverage)
            },
            'statistics': assembly_result['statistics']
        }

        return document_map


def main():
    """Test assembly on Roosevelt sample."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python assembler.py <book_dir>")
        sys.exit(1)

    book_dir = Path(sys.argv[1])

    if not book_dir.exists():
        print(f"Error: Book directory not found: {book_dir}")
        sys.exit(1)

    # Run assembly
    assembler = BatchAssembler(book_dir)
    result = assembler.assemble()

    # Build document map
    document_map = assembler.build_document_map(result)

    # Print results
    print("\n" + "="*70)
    print("✅ Assembly Complete")
    print("="*70)
    print(f"\nFull text: {len(result['full_text'])} characters")
    print(f"Word count: {result['word_count']:,}")
    print(f"Chapters: {len(document_map['body']['chapters'])}")
    print(f"Footnotes: {len(result['footnotes'])}")

    # Save for inspection
    output_file = book_dir / "structured" / "assembly_test.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'statistics': result['statistics'],
            'document_map': document_map,
            'sample_text': result['full_text'][:1000]
        }, f, indent=2)

    print(f"\n💾 Saved test results to: {output_file.name}")


if __name__ == "__main__":
    main()
