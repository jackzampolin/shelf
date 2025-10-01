#!/usr/bin/env python3
"""
Output Generator - Phase 8

Generates three output formats (pure Python, no LLM calls):
- reading/ : TTS-optimized text
- data/    : Structured JSON for RAG/analysis
- archive/ : Complete markdown for human reading
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict


class OutputGenerator:
    """Generate all three output formats."""

    def __init__(self, book_dir: Path):
        self.book_dir = book_dir
        self.structured_dir = book_dir / "structured"
        self.logger = None  # Will be set by parent BookStructurer

        # Output directories
        self.reading_dir = self.structured_dir / "reading"
        self.data_dir = self.structured_dir / "data"
        self.archive_dir = self.structured_dir / "archive"

        # Data subdirectories
        self.body_dir = self.data_dir / "body"
        self.front_matter_dir = self.data_dir / "front_matter"
        self.back_matter_dir = self.data_dir / "back_matter"

        # Create all directories
        for d in [
            self.structured_dir, self.reading_dir, self.data_dir, self.archive_dir,
            self.body_dir, self.front_matter_dir, self.back_matter_dir
        ]:
            d.mkdir(exist_ok=True, parents=True)

    def generate_all_outputs(self,
                            pages: List[Dict],
                            document_map: Dict,
                            page_mapping: List[Dict],
                            footnotes: List[Dict],
                            bibliography: List[Dict],
                            stats: Dict):
        """Generate all three output formats."""
        print("\n" + "="*70)
        print("📦 Phase 8: Output Generation")
        print("="*70)

        self.save_document_map(document_map, stats)
        self.save_page_mapping(page_mapping, document_map)
        self.save_chapters(pages, document_map, footnotes)
        self.save_footnotes(footnotes)
        self.save_bibliography(bibliography)
        self.generate_reading_output(pages, document_map, footnotes)
        self.generate_archive_output(pages, document_map)
        self.save_metadata(document_map, stats)

        print(f"\n✅ All outputs generated")

    def save_document_map(self, document_map: Dict, stats: Dict):
        """Save document_map.json to data directory."""
        output_path = self.data_dir / "document_map.json"

        document_map_copy = document_map.copy()
        document_map_copy['processing'] = {
            "date": datetime.now().isoformat(),
            "model": "anthropic/claude-sonnet-4.5",
            "cost_usd": stats['total_cost_usd'],
            "schema_version": "2.0"
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(document_map_copy, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Saved document map: {output_path.name}")

    def save_page_mapping(self, page_mapping: List[Dict], document_map: Dict):
        """Save page_mapping.json to both reading and data directories."""
        book_info = document_map.get('book', {})

        page_mapping_data = {
            "mapping": page_mapping,
            "citation_format": "{author}. *{title}*. {publisher}, {year}. p. {book_page}.",
            "citation_example": f"{book_info.get('author', 'Author')}. *{book_info.get('title', 'Title')}*. {book_info.get('publisher', 'Publisher')}, {book_info.get('year', 'Year')}. p. 42."
        }

        # Save to both locations
        for output_dir in [self.reading_dir, self.data_dir]:
            output_path = output_dir / "page_mapping.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(page_mapping_data, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Saved page mappings")

    def save_chapters(self, pages: List[Dict], document_map: Dict, footnotes: List[Dict]):
        """Save chapter files to data/body directory."""
        chapters = document_map.get('body', {}).get('chapters', [])

        for chapter in chapters:
            ch_num = chapter['number']

            # Get pages for this chapter
            chapter_pages = []
            for page in pages:
                if chapter['start_page'] <= page['scan_page'] <= chapter['end_page']:
                    chapter_pages.append(page)

            # Build chapter structure
            chapter_data = {
                "chapter": ch_num,
                "title": chapter['title'],
                "start_page": chapter['start_page'],
                "end_page": chapter['end_page'],
                "summary": chapter.get('summary', ''),
                "paragraphs": [
                    {
                        "id": f"ch{ch_num:02d}_p{i+1:03d}",
                        "text": page['text'],
                        "scan_pages": [page['scan_page']],
                        "type": "body"
                    }
                    for i, page in enumerate(chapter_pages)
                ],
                "word_count": sum(len(p['text'].split()) for p in chapter_pages),
                "paragraph_count": len(chapter_pages)
            }

            # Add notes for this chapter
            chapter_notes = [n for n in footnotes if n.get('chapter') == ch_num]
            if chapter_notes:
                chapter_data['notes'] = chapter_notes

            # Save JSON
            output_path = self.body_dir / f"chapter_{ch_num:02d}.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(chapter_data, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Saved {len(chapters)} chapter files")

    def save_footnotes(self, footnotes: List[Dict]):
        """Save notes.json to back_matter directory."""
        if not footnotes:
            return

        notes_data = {
            "notes": footnotes,
            "summary": {
                "total_notes": len(footnotes),
                "by_chapter": {}
            }
        }

        # Count by chapter
        for note in footnotes:
            ch = note.get('chapter', 0)
            notes_data['summary']['by_chapter'][str(ch)] = \
                notes_data['summary']['by_chapter'].get(str(ch), 0) + 1

        output_path = self.back_matter_dir / "notes.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(notes_data, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Saved footnotes: {output_path.name}")

    def save_bibliography(self, bibliography: List[Dict]):
        """Save bibliography.json to back_matter directory."""
        if not bibliography:
            return

        biblio_data = {
            "bibliography": bibliography,
            "summary": {
                "total_sources": len(bibliography),
                "books": sum(1 for b in bibliography if b.get('type') == 'book'),
                "articles": sum(1 for b in bibliography if b.get('type') == 'article')
            }
        }

        output_path = self.back_matter_dir / "bibliography.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(biblio_data, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Saved bibliography: {output_path.name}")

    def generate_reading_output(self, pages: List[Dict], document_map: Dict, footnotes: List[Dict]):
        """Generate reading text (TTS-optimized) and metadata."""
        book_info = document_map.get('book', {})
        chapters = document_map.get('body', {}).get('chapters', [])
        front_matter_sections = document_map.get('front_matter', {}).get('sections', [])

        # Build reading text (body only)
        reading_parts = []
        reading_parts.append(book_info.get('title', 'Unknown Title'))
        reading_parts.append(f"by {book_info.get('author', 'Unknown Author')}")
        reading_parts.append("")

        total_word_count = 0
        chapter_metadata = []

        for chapter in chapters:
            start_pos = len("\n".join(reading_parts))

            reading_parts.append(f"=== Chapter {chapter['number']}: {chapter['title']} ===")
            reading_parts.append("")

            # Add chapter text
            for page in pages:
                if chapter['start_page'] <= page['scan_page'] <= chapter['end_page']:
                    reading_parts.append(page['text'])
                    reading_parts.append("")

            # Add chapter notes if any
            chapter_notes = [n for n in footnotes if n.get('chapter') == chapter['number']]
            if chapter_notes:
                reading_parts.append("--- Chapter Notes ---")
                reading_parts.append("")
                for note in chapter_notes:
                    reading_parts.append(f"[{note['note_id']}] {note['text']}")
                    reading_parts.append("")

            end_pos = len("\n".join(reading_parts))
            word_count = sum(
                len(p['text'].split()) for p in pages
                if chapter['start_page'] <= p['scan_page'] <= chapter['end_page']
            )
            total_word_count += word_count

            chapter_metadata.append({
                "number": chapter['number'],
                "title": chapter['title'],
                "start_position": start_pos,
                "end_position": end_pos,
                "duration_estimate_minutes": int(word_count / 200),  # ~200 words/minute
                "word_count": word_count
            })

        # Save reading text
        reading_text = "\n".join(reading_parts)
        output_path = self.reading_dir / "full_book.txt"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(reading_text)

        # Save metadata
        metadata = {
            "book": {
                "title": book_info.get('title', 'Unknown'),
                "author": book_info.get('author', 'Unknown')
            },
            "chapters": chapter_metadata,
            "reading_notes": {
                "footnotes": "collected_at_chapter_end",
                "front_matter_excluded": [s['type'] for s in front_matter_sections],
                "back_matter_excluded": ["index"],
                "total_word_count": total_word_count,
                "estimated_reading_time_hours": round(total_word_count / 12000, 1)  # ~200 wpm
            }
        }

        metadata_path = self.reading_dir / "metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Generated reading output: {total_word_count:,} words")

    def generate_archive_output(self, pages: List[Dict], document_map: Dict):
        """Generate complete archive markdown (everything)."""
        book_info = document_map.get('book', {})
        chapters = document_map.get('body', {}).get('chapters', [])
        front_matter_sections = document_map.get('front_matter', {}).get('sections', [])
        back_matter_sections = document_map.get('back_matter', {}).get('sections', [])

        md_parts = []

        # Title
        md_parts.append(f"# {book_info.get('title', 'Unknown Title')}")
        md_parts.append("")
        md_parts.append(f"**By {book_info.get('author', 'Unknown Author')}**")
        md_parts.append("")
        if book_info.get('publisher'):
            md_parts.append(f"*{book_info.get('publisher')}, {book_info.get('year', 'n.d.')}*")
            md_parts.append("")
        md_parts.append("---")
        md_parts.append("")

        # Front matter
        if front_matter_sections:
            md_parts.append("## Front Matter")
            md_parts.append("")

            for section in front_matter_sections:
                if section['type'] in ['title_page', 'copyright', 'contents']:
                    continue  # Skip these in archive

                md_parts.append(f"### {section['type'].replace('_', ' ').title()}")
                md_parts.append("")

                for page in pages:
                    if section['start_page'] <= page['scan_page'] <= section['end_page']:
                        md_parts.append(page['text'])
                        md_parts.append("")

        # Body (chapters)
        for chapter in chapters:
            md_parts.append(f"## Chapter {chapter['number']}: {chapter['title']}")
            md_parts.append("")
            md_parts.append(f"*{chapter.get('summary', '')}*")
            md_parts.append("")

            for page in pages:
                if chapter['start_page'] <= page['scan_page'] <= chapter['end_page']:
                    md_parts.append(page['text'])
                    md_parts.append("")

        # Back matter
        if back_matter_sections:
            md_parts.append("## Back Matter")
            md_parts.append("")

            for section in back_matter_sections:
                if section['type'] == 'index':
                    continue  # Skip index

                md_parts.append(f"### {section['type'].replace('_', ' ').title()}")
                md_parts.append("")

                for page in pages:
                    if section['start_page'] <= page['scan_page'] <= section['end_page']:
                        md_parts.append(page['text'])
                        md_parts.append("")

        # Save archive
        archive_md = "\n".join(md_parts)
        output_path = self.archive_dir / "full_book.md"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(archive_md)

        print(f"  ✓ Generated archive markdown")

    def save_metadata(self, document_map: Dict, stats: Dict):
        """Save processing metadata."""
        chapters = document_map.get('body', {}).get('chapters', [])

        metadata = {
            "book_slug": self.book_dir.name,
            "book_info": document_map.get('book', {}),
            "processing_date": datetime.now().isoformat(),
            "schema_version": "2.0",
            "stats": stats,
            "phase_costs": stats.get('phase_costs', {}),
            "chapters": [
                {
                    "number": ch['number'],
                    "title": ch['title'],
                    "pages": [ch['start_page'], ch['end_page']]
                }
                for ch in chapters
            ]
        }

        output_path = self.structured_dir / "metadata.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        print(f"  ✓ Saved processing metadata")
