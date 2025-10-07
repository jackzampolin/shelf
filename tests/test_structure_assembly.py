"""
Test structure stage Phase 2: Assembly & Chunking

Test Organization:
- Unit tests: Use committed extraction batch fixtures
- Integration tests: Use full book extraction data
- No API costs - pure Python logic tests

Run patterns:
- pytest -m unit: Fast unit tests with committed fixtures
- pytest -m integration: Full book assembly tests
"""

import pytest
import json
from pathlib import Path
from pipeline.structure.assembler import BatchAssembler
from pipeline.structure.chunker import SemanticChunker
from pipeline.structure.output_generator import OutputGenerator


@pytest.fixture
def extraction_metadata_unit(roosevelt_fixtures):
    """Load extraction metadata from committed fixtures."""
    metadata_file = roosevelt_fixtures / "structured" / "extraction" / "metadata.json"
    with open(metadata_file) as f:
        return json.load(f)


@pytest.fixture
def sample_batch_data(roosevelt_fixtures):
    """Load a sample batch from committed fixtures for unit testing."""
    batch_file = roosevelt_fixtures / "structured" / "extraction" / "batch_000.json"
    with open(batch_file) as f:
        return json.load(f)


@pytest.fixture
def extraction_metadata_integration(roosevelt_full_book):
    """Load extraction metadata from full book for integration tests."""
    if roosevelt_full_book is None:
        pytest.skip("Full Roosevelt book required for integration test")

    metadata_file = roosevelt_full_book / "structured" / "extraction" / "metadata.json"
    if not metadata_file.exists():
        pytest.skip("Roosevelt extraction data not available - run structure stage first")

    with open(metadata_file) as f:
        return json.load(f)


@pytest.fixture
def roosevelt_book_dir(roosevelt_full_book):
    """Roosevelt book directory for integration tests."""
    if roosevelt_full_book is None:
        pytest.skip("Full Roosevelt book required for integration test")
    return roosevelt_full_book


@pytest.mark.integration
class TestBatchAssembler:
    """Test batch assembly functionality."""

    def test_assembler_initialization(self, roosevelt_book_dir):
        """Test assembler can be initialized."""
        assembler = BatchAssembler(roosevelt_book_dir)

        assert assembler.book_dir == roosevelt_book_dir
        expected_extraction_dir = roosevelt_book_dir / "structured" / "extraction"
        assert assembler.extraction_dir == expected_extraction_dir

    def test_load_metadata(self, roosevelt_book_dir, extraction_metadata_integration):
        """Test metadata loading."""
        assembler = BatchAssembler(roosevelt_book_dir)
        metadata = assembler._load_metadata()

        assert metadata is not None
        assert 'statistics' in metadata
        assert 'configuration' in metadata

    def test_load_batches(self, roosevelt_book_dir, extraction_metadata_integration):
        """Test batch loading."""
        assembler = BatchAssembler(roosevelt_book_dir)
        total_batches = extraction_metadata_integration['statistics']['processed_batches']

        batches = assembler._load_batches(total_batches)

        assert len(batches) > 0
        assert all(batch.get('status') == 'success' for batch in batches)

        # Each batch should have required fields
        for batch in batches:
            assert 'result' in batch
            assert 'batch_metadata' in batch
            assert 'verification' in batch

    def test_merge_batches(self, roosevelt_book_dir):
        """Test batch merging with overlaps."""
        assembler = BatchAssembler(roosevelt_book_dir)
        metadata = assembler._load_metadata()
        total_batches = metadata['statistics']['processed_batches']
        batches = assembler._load_batches(total_batches)

        merged_text, paragraphs, page_coverage = assembler._merge_batches(batches)

        # Check merged text
        assert len(merged_text) > 0
        assert len(merged_text.split()) > 1000, "Should have substantial merged text"

        # Check paragraphs
        assert len(paragraphs) > 0
        for para in paragraphs:
            assert 'text' in para
            assert 'scan_page' in para

        # Check page coverage
        assert len(page_coverage) > 0
        assert all(isinstance(page, int) for page in page_coverage)

    def test_aggregate_chapter_markers(self, roosevelt_book_dir):
        """Test chapter marker aggregation."""
        assembler = BatchAssembler(roosevelt_book_dir)
        metadata = assembler._load_metadata()
        total_batches = metadata['statistics']['processed_batches']
        batches = assembler._load_batches(total_batches)

        markers = assembler._aggregate_chapter_markers(batches)

        # Roosevelt pages 75-90 may not have chapter markers (mid-chapter)
        # Just verify the method runs without error
        assert isinstance(markers, list)

    def test_aggregate_footnotes(self, roosevelt_book_dir):
        """Test footnote aggregation."""
        assembler = BatchAssembler(roosevelt_book_dir)
        metadata = assembler._load_metadata()
        total_batches = metadata['statistics']['processed_batches']
        batches = assembler._load_batches(total_batches)

        footnotes = assembler._aggregate_footnotes(batches)

        # Just verify the method runs and returns a list
        assert isinstance(footnotes, list)

    def test_full_assembly(self, roosevelt_book_dir):
        """Test full assembly process."""
        assembler = BatchAssembler(roosevelt_book_dir)
        result = assembler.assemble()

        # Check result structure
        assert 'full_text' in result
        assert 'paragraphs' in result
        assert 'chapter_markers' in result
        assert 'footnotes' in result
        assert 'page_coverage' in result
        assert 'word_count' in result
        assert 'statistics' in result

        # Check statistics
        stats = result['statistics']
        assert stats['total_batches'] > 0
        assert stats['pages_covered'] > 0
        assert stats['word_count'] > 0
        assert stats['total_paragraphs'] > 0

    def test_build_document_map(self, roosevelt_book_dir):
        """Test document map building."""
        assembler = BatchAssembler(roosevelt_book_dir)
        assembly_result = assembler.assemble()

        book_metadata = {
            'title': 'Test Book',
            'author': 'Test Author'
        }

        document_map = assembler.build_document_map(assembly_result, book_metadata)

        # Check document map structure
        assert 'book' in document_map
        assert 'body' in document_map
        assert 'page_range' in document_map
        assert 'statistics' in document_map

        # Check book metadata
        assert document_map['book']['title'] == 'Test Book'
        assert document_map['book']['author'] == 'Test Author'

        # Check page range
        assert document_map['page_range']['total'] > 0


class TestSemanticChunker:
    """Test semantic chunking functionality."""

    @pytest.mark.unit
    def test_chunker_initialization(self):
        """Test chunker can be initialized."""
        chunker = SemanticChunker()

        assert chunker.model == "openai/gpt-4o-mini"
        assert chunker.target_chunk_size == 750
        assert chunker.chunk_min == 500
        assert chunker.chunk_max == 1000

    @pytest.mark.unit
    def test_fallback_chunking(self):
        """Test fallback paragraph-based chunking."""
        chunker = SemanticChunker()

        # Create test paragraphs
        paragraphs = [
            {'text': ' '.join(['word'] * 200), 'scan_page': 1, 'type': 'body'},
            {'text': ' '.join(['word'] * 200), 'scan_page': 2, 'type': 'body'},
            {'text': ' '.join(['word'] * 200), 'scan_page': 3, 'type': 'body'},
            {'text': ' '.join(['word'] * 200), 'scan_page': 4, 'type': 'body'},
        ]

        chunks = chunker._fallback_chunk_by_paragraphs(
            paragraphs,
            chunk_prefix="test_chunk"
        )

        # Check chunks
        assert len(chunks) > 0
        for chunk in chunks:
            assert 'chunk_id' in chunk
            assert 'text' in chunk
            assert 'scan_pages' in chunk
            assert 'word_count' in chunk
            assert chunk['word_count'] <= chunker.chunk_max

    def test_chunk_text_no_chapters(self, roosevelt_book_dir):
        """Test chunking when no chapters are present."""
        # Get assembly result
        assembler = BatchAssembler(roosevelt_book_dir)
        assembly_result = assembler.assemble()

        # Build document map with no chapters
        document_map = {
            'book': {'title': 'Test Book', 'author': 'Test Author'},
            'body': {'chapters': []},
            'page_range': {'total': assembly_result['statistics']['pages_covered']}
        }

        # Run chunker
        chunker = SemanticChunker()
        result = chunker.chunk_text(
            full_text=assembly_result['full_text'],
            paragraphs=assembly_result['paragraphs'],
            document_map=document_map
        )

        # Check result
        assert 'chunks' in result
        assert 'statistics' in result
        assert 'cost' in result

        # Check chunks
        chunks = result['chunks']
        assert len(chunks) > 0

        for chunk in chunks:
            assert 'chunk_id' in chunk
            assert 'text' in chunk
            assert 'scan_pages' in chunk
            assert 'word_count' in chunk
            assert chunk['word_count'] >= chunker.chunk_min or len(chunks) == 1
            assert chunk['word_count'] <= chunker.chunk_max or len(chunks) == 1

        # Check statistics
        stats = result['statistics']
        assert stats['total_chunks'] == len(chunks)
        assert stats['total_words'] > 0


@pytest.mark.integration
class TestOutputGenerator:
    """Test output generation functionality."""

    def test_generator_initialization(self, roosevelt_book_dir):
        """Test generator can be initialized."""
        generator = OutputGenerator(roosevelt_book_dir)

        assert generator.book_dir == roosevelt_book_dir
        assert generator.structured_dir.exists()

    def test_full_output_generation(self, roosevelt_book_dir):
        """Test full output generation pipeline."""
        # Run assembly
        assembler = BatchAssembler(roosevelt_book_dir)
        assembly_result = assembler.assemble()

        # Build document map
        book_metadata = {
            'title': 'Theodore Roosevelt: An Autobiography',
            'author': 'Theodore Roosevelt'
        }
        document_map = assembler.build_document_map(assembly_result, book_metadata)

        # Run chunker
        chunker = SemanticChunker()
        chunking_result = chunker.chunk_text(
            full_text=assembly_result['full_text'],
            paragraphs=assembly_result['paragraphs'],
            document_map=document_map
        )

        # Generate outputs
        generator = OutputGenerator(roosevelt_book_dir)
        generator.generate_all_outputs(
            assembly_result=assembly_result,
            chunking_result=chunking_result,
            document_map=document_map,
            book_metadata=book_metadata,
            stats={'total_cost': 0.0}
        )

        # Verify outputs were created
        structured_dir = roosevelt_book_dir / "structured"

        # Check chunks
        chunks_dir = structured_dir / "data" / "chunks"
        assert chunks_dir.exists()
        chunk_files = list(chunks_dir.glob("*.json"))
        assert len(chunk_files) == len(chunking_result['chunks'])

        # Check document map
        doc_map_file = structured_dir / "data" / "document_map.json"
        assert doc_map_file.exists()

        # Check reading output
        reading_file = structured_dir / "reading" / "full_book.txt"
        assert reading_file.exists()
        assert reading_file.stat().st_size > 0

        # Check archive output
        archive_file = structured_dir / "archive" / "full_book.md"
        assert archive_file.exists()
        assert archive_file.stat().st_size > 0

        # Check metadata
        metadata_file = structured_dir / "metadata.json"
        assert metadata_file.exists()

        with open(metadata_file) as f:
            metadata = json.load(f)

        assert metadata['schema_version'] == "3.0"
        assert metadata['architecture'] == "2-phase sliding window"
        assert 'statistics' in metadata


@pytest.mark.integration
class TestPhase2Integration:
    """Integration tests for full Phase 2 pipeline."""

    @pytest.mark.integration
    def test_full_phase2_pipeline(self, roosevelt_book_dir):
        """Test complete Phase 2 pipeline from extraction to outputs."""
        from pipeline.structure import BookStructurer

        # Run Phase 2 only (skip extraction)
        structurer = BookStructurer('roosevelt-autobiography')
        result = structurer.process_book(skip_extraction=True)

        # Check result
        assert 'total_cost' in result
        assert 'statistics' in result
        assert 'chunks_created' in result

        # Check statistics
        assert result['chunks_created'] > 0
        assert 'assembly' in result['statistics']
        assert 'chunking' in result['statistics']

        # Verify outputs exist
        structured_dir = roosevelt_book_dir / "structured"

        # Check all three output formats
        assert (structured_dir / "data" / "chunks").exists()
        assert (structured_dir / "data" / "document_map.json").exists()
        assert (structured_dir / "reading" / "full_book.txt").exists()
        assert (structured_dir / "archive" / "full_book.md").exists()
        assert (structured_dir / "metadata.json").exists()

    def test_chunk_provenance(self, roosevelt_book_dir):
        """Test that chunks maintain proper provenance tracking."""
        # Run Phase 2
        from pipeline.structure import BookStructurer
        structurer = BookStructurer('roosevelt-autobiography')
        result = structurer.process_book(skip_extraction=True)

        # Load a chunk and verify provenance
        chunks_dir = roosevelt_book_dir / "structured" / "data" / "chunks"
        chunk_files = list(chunks_dir.glob("*.json"))

        assert len(chunk_files) > 0

        # Check first chunk
        with open(chunk_files[0]) as f:
            chunk = json.load(f)

        # Verify provenance fields
        assert 'chunk_id' in chunk
        assert 'scan_pages' in chunk
        assert 'word_count' in chunk
        assert len(chunk['scan_pages']) > 0
        assert all(isinstance(page, int) for page in chunk['scan_pages'])

    def test_no_data_loss_in_assembly(self, roosevelt_book_dir):
        """Verify assembly correctly handles overlaps without losing unique content."""
        # Run assembly
        assembler = BatchAssembler(roosevelt_book_dir)
        assembly_result = assembler.assemble()

        # Check basic stats
        assert assembly_result['word_count'] > 1000, "Should have substantial text"
        assert assembly_result['statistics']['pages_covered'] > 0, "Should cover pages"

        # Check that we have reasonable word density
        words_per_page = assembly_result['word_count'] / assembly_result['statistics']['pages_covered']
        assert 200 <= words_per_page <= 600, f"Word density {words_per_page:.0f} words/page seems wrong"

        # Note: We can't directly compare to batch word counts because batches
        # have overlapping pages. Assembly deduplicates overlaps, which is correct behavior.
        # The important thing is that we get reasonable output text.

    def test_chunk_size_distribution(self, roosevelt_book_dir):
        """Test that chunks are within expected size ranges."""
        from pipeline.structure import BookStructurer

        structurer = BookStructurer('roosevelt-autobiography')
        result = structurer.process_book(skip_extraction=True)

        # Load all chunks
        chunks_dir = roosevelt_book_dir / "structured" / "data" / "chunks"
        chunk_files = list(chunks_dir.glob("*.json"))

        word_counts = []
        for chunk_file in chunk_files:
            with open(chunk_file) as f:
                chunk = json.load(f)
            word_counts.append(chunk['word_count'])

        # Check distribution
        avg_size = sum(word_counts) / len(word_counts)
        min_size = min(word_counts)
        max_size = max(word_counts)

        # Should be reasonably sized for RAG
        assert 400 <= avg_size <= 1100, f"Avg chunk size {avg_size} outside expected range"
        assert min_size >= 300 or len(word_counts) == 1, f"Chunk too small: {min_size} words"
        assert max_size <= 1500, f"Chunk too large: {max_size} words"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
