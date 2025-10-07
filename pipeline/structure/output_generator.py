#!/usr/bin/env python3
"""
Output Generator (v2) - Phase 2, Step 3

Generates three output formats from assembled and chunked data:
- reading/ : TTS-optimized text
- data/    : Structured JSON for RAG/analysis
- archive/ : Complete markdown for human reading
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict


class OutputGenerator:
    """Generate all three output formats from assembly + chunks."""

    def __init__(self, book_dir: Path, logger=None):
        self.book_dir = book_dir
        self.structured_dir = book_dir / "structured"
        self.logger = logger

        # Output directories
        self.reading_dir = self.structured_dir / "reading"
        self.data_dir = self.structured_dir / "data"
        self.archive_dir = self.structured_dir / "archive"

        # Data subdirectories
        self.chunks_dir = self.data_dir / "chunks"

        # Create all directories
        for d in [
            self.structured_dir, self.reading_dir, self.data_dir,
            self.archive_dir, self.chunks_dir
        ]:
            d.mkdir(exist_ok=True, parents=True)

    def generate_all_outputs(self,
                            assembly_result: Dict,
                            chunking_result: Dict,
                            document_map: Dict,
                            book_metadata: Dict = None,
                            stats: Dict = None):
        """
        Generate all three output formats.

        Args:
            assembly_result: Result from BatchAssembler.assemble()
            chunking_result: Result from SemanticChunker.chunk_text()
            document_map: Document structure map
            book_metadata: Book metadata (title, author, etc.)
            stats: Processing statistics
        """
        print("\n" + "="*70)
        print("📦 Phase 2.3: Output Generation")
        print("="*70)

        # Save chunks
        self._save_chunks(chunking_result['chunks'])

        # Save document map
        self._save_document_map(document_map, stats)

        # Generate reading output
        self._generate_reading_output(
            assembly_result['full_text'],
            document_map,
            book_metadata
        )

        # Generate archive output
        self._generate_archive_output(
            assembly_result['full_text'],
            document_map,
            book_metadata
        )

        # Save metadata
        self._save_metadata(document_map, chunking_result, stats)

        print(f"\n✅ All outputs generated")

    def _save_chunks(self, chunks: List[Dict]):
        """Save chunk files to data/chunks directory."""
        if not chunks:
            print(f"  ℹ️  No chunks to save")
            return

        for chunk in chunks:
            chunk_id = chunk['chunk_id']
            output_path = self.chunks_dir / f"{chunk_id}.json"

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(chunk, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Saved {len(chunks)} chunks")

    def _save_document_map(self, document_map: Dict, stats: Dict):
        """Save document_map.json to data directory."""
        output_path = self.data_dir / "document_map.json"

        document_map_copy = document_map.copy()

        # Add processing info
        if stats:
            document_map_copy['processing'] = {
                "date": datetime.now().isoformat(),
                "model": "openai/gpt-4o-mini",
                "cost_usd": stats.get('total_cost', 0.0),
                "schema_version": "3.0"
            }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(document_map_copy, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Saved document map")

    def _generate_reading_output(self,
                                full_text: str,
                                document_map: Dict,
                                book_metadata: Dict = None):
        """Generate reading text (TTS-optimized)."""
        reading_parts = []

        # Add header
        if book_metadata:
            title = book_metadata.get('title', 'Unknown Title')
            author = book_metadata.get('author', 'Unknown Author')
            reading_parts.append(title)
            reading_parts.append(f"by {author}")
            reading_parts.append("")

        chapters = document_map.get('body', {}).get('chapters', [])

        if chapters:
            # Split text by chapters
            # (For now, just use full text - would need chapter boundaries)
            reading_parts.append(full_text)
        else:
            # No chapters - just use full text
            reading_parts.append(full_text)

        # Save reading text
        reading_text = "\n\n".join(reading_parts)
        output_path = self.reading_dir / "full_book.txt"

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(reading_text)

        word_count = len(reading_text.split())
        print(f"  ✓ Generated reading output: {word_count:,} words")

        # Save metadata
        metadata = {
            "book": book_metadata or {},
            "word_count": word_count,
            "estimated_reading_time_hours": round(word_count / 12000, 1),
            "chapters": len(chapters)
        }

        metadata_path = self.reading_dir / "metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def _generate_archive_output(self,
                                full_text: str,
                                document_map: Dict,
                                book_metadata: Dict = None):
        """Generate complete archive markdown."""
        md_parts = []

        # Title
        if book_metadata:
            title = book_metadata.get('title', 'Unknown Title')
            author = book_metadata.get('author', 'Unknown Author')
            publisher = book_metadata.get('publisher')
            year = book_metadata.get('year')

            md_parts.append(f"# {title}")
            md_parts.append("")
            md_parts.append(f"**By {author}**")
            md_parts.append("")

            if publisher:
                md_parts.append(f"*{publisher}, {year or 'n.d.'}*")
                md_parts.append("")

            md_parts.append("---")
            md_parts.append("")

        # Body text
        chapters = document_map.get('body', {}).get('chapters', [])

        if chapters:
            # Would need to split text by chapter boundaries
            # For now, just add full text
            md_parts.append(full_text)
        else:
            md_parts.append(full_text)

        # Save archive
        archive_md = "\n\n".join(md_parts)
        output_path = self.archive_dir / "full_book.md"

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(archive_md)

        print(f"  ✓ Generated archive markdown")

    def _save_metadata(self,
                      document_map: Dict,
                      chunking_result: Dict,
                      stats: Dict):
        """Save processing metadata to structured/metadata.json."""
        chapters = document_map.get('body', {}).get('chapters', [])
        chunks = chunking_result.get('chunks', [])

        metadata = {
            "book_slug": self.book_dir.name,
            "book_info": document_map.get('book', {}),
            "processing_date": datetime.now().isoformat(),
            "schema_version": "3.0",
            "architecture": "2-phase sliding window",
            "statistics": {
                "total_pages": document_map.get('page_range', {}).get('total', 0),
                "total_chapters": len(chapters),
                "total_chunks": len(chunks),
                "total_words": sum(c.get('word_count', 0) for c in chunks),
                "total_cost": stats.get('total_cost', 0.0) if stats else 0.0
            },
            "chapters": [
                {
                    "number": ch['number'],
                    "title": ch['title'],
                    "pages": [ch['start_page'], ch['end_page']]
                }
                for ch in chapters
            ],
            "chunk_summary": {
                "total": len(chunks),
                "avg_size": chunking_result.get('statistics', {}).get('avg_chunk_size', 0),
                "min_size": chunking_result.get('statistics', {}).get('min_chunk_size', 0),
                "max_size": chunking_result.get('statistics', {}).get('max_chunk_size', 0)
            }
        }

        output_path = self.structured_dir / "metadata.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Saved processing metadata")


def main():
    """Test generator."""
    print("Use the full structure pipeline to test output generation")
    print("Example: python ar.py structure <scan-id>")


if __name__ == "__main__":
    main()
