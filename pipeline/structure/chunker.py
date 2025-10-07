#!/usr/bin/env python3
"""
Semantic Chunker - Phase 2, Step 2

Creates RAG-optimized chunks with:
- Semantic boundaries (500-1000 words)
- Provenance tracking (chunk → pages)
- Self-contained context for retrieval
"""

import json
import sys
from pathlib import Path
from typing import List, Dict
import re

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from llm_client import call_llm
from pricing import get_pricing_for_model


class SemanticChunker:
    """Creates semantic chunks for RAG from assembled text."""

    def __init__(self, logger=None):
        self.logger = logger
        self.model = "openai/gpt-4o-mini"  # Cost-effective for chunking

        # Chunking parameters
        self.target_chunk_size = 750  # words
        self.chunk_min = 500
        self.chunk_max = 1000

    def chunk_text(self,
                   full_text: str,
                   paragraphs: List[Dict],
                   document_map: Dict) -> Dict:
        """
        Create semantic chunks from assembled text.

        Args:
            full_text: Complete merged book text
            paragraphs: List of paragraphs with provenance
            document_map: Document structure with chapters

        Returns:
            Dict with:
                - chunks: List of chunk dicts
                - statistics: Chunking stats
                - cost: LLM cost
        """
        print("\n" + "="*70)
        print("✂️  Phase 2.2: Semantic Chunking")
        print("="*70)

        chunks = []
        total_cost = 0.0

        chapters = document_map.get('body', {}).get('chapters', [])

        if chapters:
            # Chunk by chapter
            print(f"\n📖 Chunking {len(chapters)} chapters...")

            for chapter in chapters:
                chapter_chunks, cost = self._chunk_chapter(
                    chapter, paragraphs, full_text
                )
                chunks.extend(chapter_chunks)
                total_cost += cost

                print(f"  ✓ Chapter {chapter['number']}: {len(chapter_chunks)} chunks")

        else:
            # No chapters - chunk entire text as one unit
            print(f"\n📄 Chunking full text (no chapters found)...")

            text_chunks, cost = self._chunk_text_block(
                text=full_text,
                paragraphs=paragraphs,
                chunk_prefix="chunk"
            )
            chunks.extend(text_chunks)
            total_cost += cost

            print(f"  ✓ Created {len(text_chunks)} chunks")

        # Calculate statistics
        statistics = {
            'total_chunks': len(chunks),
            'avg_chunk_size': int(sum(c['word_count'] for c in chunks) / len(chunks)) if chunks else 0,
            'min_chunk_size': min(c['word_count'] for c in chunks) if chunks else 0,
            'max_chunk_size': max(c['word_count'] for c in chunks) if chunks else 0,
            'total_words': sum(c['word_count'] for c in chunks),
            'total_cost': total_cost
        }

        print(f"\n📊 Chunking Statistics:")
        print(f"  • Total chunks: {statistics['total_chunks']}")
        print(f"  • Avg size: {statistics['avg_chunk_size']} words")
        print(f"  • Range: {statistics['min_chunk_size']}-{statistics['max_chunk_size']} words")
        print(f"  • Total words: {statistics['total_words']:,}")
        print(f"  • Cost: ${statistics['total_cost']:.4f}")

        return {
            'chunks': chunks,
            'statistics': statistics,
            'cost': total_cost
        }

    def _chunk_chapter(self,
                      chapter: Dict,
                      all_paragraphs: List[Dict],
                      full_text: str) -> tuple[List[Dict], float]:
        """
        Chunk a single chapter into semantic sections.

        Returns:
            Tuple of (chunk_list, cost)
        """
        chapter_num = chapter['number']
        start_page = chapter['start_page']
        end_page = chapter['end_page']

        # Get paragraphs for this chapter
        chapter_paragraphs = [
            p for p in all_paragraphs
            if start_page <= p.get('scan_page', 0) <= end_page
        ]

        if not chapter_paragraphs:
            return [], 0.0

        # Build chapter text
        chapter_text = "\n\n".join(p['text'] for p in chapter_paragraphs)

        # Check if chapter is small enough to be one chunk
        word_count = len(chapter_text.split())

        if word_count <= self.chunk_max:
            # Single chunk for small chapter
            chunk = {
                'chunk_id': f"ch{chapter_num:02d}_chunk_001",
                'chapter': chapter_num,
                'chapter_title': chapter.get('title', f'Chapter {chapter_num}'),
                'text': chapter_text,
                'scan_pages': sorted(set(p['scan_page'] for p in chapter_paragraphs)),
                'word_count': word_count,
                'position_in_chapter': 1,
                'total_chunks_in_chapter': 1
            }
            return [chunk], 0.0

        # Large chapter - use LLM to split semantically
        chunks, cost = self._chunk_text_block(
            text=chapter_text,
            paragraphs=chapter_paragraphs,
            chunk_prefix=f"ch{chapter_num:02d}_chunk",
            chapter_num=chapter_num,
            chapter_title=chapter.get('title')
        )

        return chunks, cost

    def _chunk_text_block(self,
                         text: str,
                         paragraphs: List[Dict],
                         chunk_prefix: str,
                         chapter_num: int = None,
                         chapter_title: str = None) -> tuple[List[Dict], float]:
        """
        Split a text block into semantic chunks using LLM.

        Returns:
            Tuple of (chunk_list, cost)
        """
        # Call LLM to identify split points
        split_points = self._get_semantic_split_points(text)

        if not split_points:
            # LLM didn't return splits - fall back to simple paragraph grouping
            return self._fallback_chunk_by_paragraphs(
                paragraphs, chunk_prefix, chapter_num, chapter_title
            ), 0.0

        # Build chunks from split points
        chunks = []
        text_paragraphs = text.split("\n\n")

        for i, split in enumerate(split_points):
            start_para = split['start_paragraph']
            end_para = split['end_paragraph']

            # Get text for this chunk
            chunk_text = "\n\n".join(text_paragraphs[start_para:end_para+1])

            # Find scan pages for this chunk
            # Map paragraph indices to scan_pages
            scan_pages = set()
            for j in range(start_para, min(end_para+1, len(paragraphs))):
                if j < len(paragraphs):
                    scan_pages.add(paragraphs[j].get('scan_page', 0))

            chunk = {
                'chunk_id': f"{chunk_prefix}_{i+1:03d}",
                'text': chunk_text,
                'scan_pages': sorted(scan_pages),
                'word_count': len(chunk_text.split()),
                'position_in_chapter': i + 1,
                'total_chunks_in_chapter': len(split_points),
                'theme': split.get('theme', '')
            }

            # Add chapter info if available
            if chapter_num is not None:
                chunk['chapter'] = chapter_num
                chunk['chapter_title'] = chapter_title

            chunks.append(chunk)

        # Calculate cost (rough estimate)
        pricing = get_pricing_for_model(self.model)
        if pricing:
            input_tokens = len(text.split()) * 1.3  # Rough estimate
            cost = (input_tokens * pricing.get('input', 0)) + (500 * pricing.get('output', 0))
        else:
            cost = 0.01  # Default estimate

        return chunks, cost

    def _get_semantic_split_points(self, text: str) -> List[Dict]:
        """
        Use LLM to identify semantic split points in text.

        Returns:
            List of split point dicts with start_paragraph, end_paragraph, theme
        """
        paragraphs = text.split("\n\n")
        total_paragraphs = len(paragraphs)

        system_prompt = """You are a text chunking specialist. Your job is to split long text into semantic sections for RAG (Retrieval Augmented Generation).

Each section should:
1. Be 500-1000 words (target 750)
2. Start and end at natural boundaries (scene changes, topic shifts)
3. Never split mid-paragraph
4. Be self-contained enough for retrieval"""

        user_prompt = f"""Split this text into semantic sections.

TEXT ({len(text.split())} words, {total_paragraphs} paragraphs):

{text}

RULES:
1. Target 750 words per section (min 500, max 1000)
2. Split at natural boundaries only
3. Each section should be semantically coherent
4. Provide a brief theme description for each section

Return JSON:
{{
  "sections": [
    {{
      "start_paragraph": 0,
      "end_paragraph": 5,
      "word_count": 847,
      "theme": "brief description of what this section covers"
    }}
  ]
}}

IMPORTANT: Paragraph indices are 0-based. Last paragraph is index {total_paragraphs - 1}."""

        try:
            response = call_llm(
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format="json"
            )

            # Parse response
            result = json.loads(response)
            sections = result.get('sections', [])

            # Validate sections
            valid_sections = []
            for section in sections:
                if all(k in section for k in ['start_paragraph', 'end_paragraph']):
                    # Ensure indices are within bounds
                    start = max(0, section['start_paragraph'])
                    end = min(total_paragraphs - 1, section['end_paragraph'])

                    valid_sections.append({
                        'start_paragraph': start,
                        'end_paragraph': end,
                        'theme': section.get('theme', '')
                    })

            return valid_sections

        except Exception as e:
            if self.logger:
                self.logger.log_event('warning', f"LLM chunking failed: {e}")
            return []

    def _fallback_chunk_by_paragraphs(self,
                                     paragraphs: List[Dict],
                                     chunk_prefix: str,
                                     chapter_num: int = None,
                                     chapter_title: str = None) -> List[Dict]:
        """
        Fallback: Chunk by grouping paragraphs to target size.

        Used when LLM chunking fails.
        """
        chunks = []
        current_chunk_text = []
        current_chunk_pages = set()
        current_word_count = 0
        chunk_num = 1

        for para in paragraphs:
            para_text = para.get('text', '')
            para_words = len(para_text.split())
            para_page = para.get('scan_page', 0)

            # Check if adding this paragraph would exceed max
            if current_word_count + para_words > self.chunk_max and current_chunk_text:
                # Save current chunk
                chunk = {
                    'chunk_id': f"{chunk_prefix}_{chunk_num:03d}",
                    'text': "\n\n".join(current_chunk_text),
                    'scan_pages': sorted(current_chunk_pages),
                    'word_count': current_word_count,
                    'position_in_chapter': chunk_num
                }

                if chapter_num is not None:
                    chunk['chapter'] = chapter_num
                    chunk['chapter_title'] = chapter_title

                chunks.append(chunk)

                # Start new chunk
                current_chunk_text = []
                current_chunk_pages = set()
                current_word_count = 0
                chunk_num += 1

            # Add paragraph to current chunk
            current_chunk_text.append(para_text)
            current_chunk_pages.add(para_page)
            current_word_count += para_words

        # Save final chunk
        if current_chunk_text:
            chunk = {
                'chunk_id': f"{chunk_prefix}_{chunk_num:03d}",
                'text': "\n\n".join(current_chunk_text),
                'scan_pages': sorted(current_chunk_pages),
                'word_count': current_word_count,
                'position_in_chapter': chunk_num
            }

            if chapter_num is not None:
                chunk['chapter'] = chapter_num
                chunk['chapter_title'] = chapter_title

            chunks.append(chunk)

        # Update total_chunks_in_chapter for all chunks
        for chunk in chunks:
            chunk['total_chunks_in_chapter'] = len(chunks)

        return chunks


def main():
    """Test chunker on assembled text."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python chunker.py <assembly_result.json>")
        sys.exit(1)

    assembly_file = Path(sys.argv[1])

    if not assembly_file.exists():
        print(f"Error: Assembly file not found: {assembly_file}")
        sys.exit(1)

    # Load assembly result
    with open(assembly_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Mock data for testing
    full_text = data.get('sample_text', '')
    paragraphs = []  # Would need to load from actual assembly
    document_map = data.get('document_map', {})

    # Run chunker
    chunker = SemanticChunker()

    # For testing, create simple text
    test_text = full_text * 10  # Repeat to get enough text
    test_paragraphs = [
        {'text': full_text, 'scan_page': 75, 'type': 'body'}
        for _ in range(10)
    ]

    result = chunker.chunk_text(test_text, test_paragraphs, document_map)

    print(f"\n✅ Created {len(result['chunks'])} chunks")
    print(f"   Cost: ${result['cost']:.4f}")


if __name__ == "__main__":
    main()
