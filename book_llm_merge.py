#!/usr/bin/env python3
"""
Merge LLM-corrected pages into final clean text with dual structures.

Creates two output formats:
1. Logical structure: Continuous reading text (chapters, sections)
2. Page structure: Individual pages with metadata for physical book referencing

Usage:
    python book_llm_merge.py <book-slug>

Example:
    python book_llm_merge.py The-Accidental-President
"""

import sys
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


class BookMerger:
    """Merge corrected pages into final clean text structures."""

    def __init__(self, book_slug: str):
        self.book_slug = book_slug
        self.base_dir = Path.home() / "Documents" / "book_scans" / book_slug

        self.corrected_dir = self.base_dir / "llm_agent2_corrected"
        self.output_dir = self.base_dir / "final_text"
        self.output_dir.mkdir(exist_ok=True)

        # Create subdirectories for dual structures
        self.logical_dir = self.output_dir / "logical"
        self.pages_dir = self.output_dir / "pages"
        self.logical_dir.mkdir(exist_ok=True)
        self.pages_dir.mkdir(exist_ok=True)

        self.metadata_file = self.base_dir / "metadata.json"

    def load_metadata(self) -> Dict:
        """Load book metadata."""
        with open(self.metadata_file) as f:
            return json.load(f)

    def remove_correction_markers(self, text: str) -> str:
        """Remove [CORRECTED:id] markers from text."""
        return re.sub(r'\[CORRECTED:\d+\]', '', text)

    def remove_metadata_headers(self, text: str) -> str:
        """Remove metadata comment lines from top of file."""
        lines = text.split('\n')
        cleaned_lines = []
        skip_headers = True

        for line in lines:
            # Skip lines starting with # at the beginning
            if skip_headers and line.strip().startswith('#'):
                continue
            else:
                skip_headers = False
                cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def detect_header_footer(self, text: str) -> Tuple[int, int]:
        """
        Detect likely header/footer lines based on patterns.

        Returns:
            (header_lines, footer_lines) - number of lines to skip from top/bottom
        """
        lines = text.strip().split('\n')
        header_lines = 0
        footer_lines = 0

        # Common header/footer patterns
        page_num_pattern = r'^\s*\d+\s*$'  # Just a number
        roman_pattern = r'^[ivxlcdm]+\s*/\s*'  # Roman numerals like "xvi /"
        section_pattern = r'^\s*[A-Z\s]+\s*/\s*'  # "Timeline /" or similar

        # Check first few lines for headers
        for i, line in enumerate(lines[:3]):
            if not line.strip():
                continue
            if re.match(page_num_pattern, line.strip()):
                header_lines = i + 1
                break
            if re.match(roman_pattern, line.strip()) or re.match(section_pattern, line.strip()):
                header_lines = i + 1
                break

        # Check last few lines for footers
        for i, line in enumerate(reversed(lines[-3:])):
            if not line.strip():
                continue
            if re.match(page_num_pattern, line.strip()):
                footer_lines = i + 1
                break

        return header_lines, footer_lines

    def clean_page_text(self, text: str) -> str:
        """
        Fully clean page text: remove markers, metadata, headers, footers.
        """
        # Remove correction markers
        text = self.remove_correction_markers(text)

        # Remove metadata headers
        text = self.remove_metadata_headers(text)

        # Detect and remove headers/footers
        header_lines, footer_lines = self.detect_header_footer(text)
        lines = text.split('\n')

        if header_lines > 0:
            lines = lines[header_lines:]
        if footer_lines > 0:
            lines = lines[:-footer_lines]

        # Clean up excessive blank lines
        text = '\n'.join(lines)
        text = re.sub(r'\n{3,}', '\n\n', text)  # Max 2 consecutive newlines

        return text.strip()

    def process_page_structure(self, page_num: int, raw_text: str) -> Dict:
        """
        Create page structure metadata with cleaned text.

        Returns dict with page metadata for database ingestion.
        """
        cleaned_text = self.clean_page_text(raw_text)

        return {
            "page_number": page_num,
            "physical_page": page_num,
            "text": cleaned_text,
            "char_count": len(cleaned_text),
            "word_count": len(cleaned_text.split()),
            "has_content": bool(cleaned_text.strip())
        }

    def merge_logical_structure(self, pages: List[Dict]) -> str:
        """
        Merge pages into continuous logical reading text.

        Handles:
        - Joining hyphenated words across pages
        - Maintaining paragraph structure
        - Chapter/section detection
        """
        continuous_text = []

        for i, page in enumerate(pages):
            if not page["has_content"]:
                continue

            text = page["text"]

            # If previous page ended with hyphen, join with current
            if continuous_text and continuous_text[-1].endswith('-'):
                # Remove hyphen and join
                continuous_text[-1] = continuous_text[-1][:-1]
                # Get first word of current page
                first_word = text.split()[0] if text.split() else ""
                if first_word:
                    continuous_text[-1] += first_word
                    # Remove first word from current text
                    text = ' '.join(text.split()[1:])

            continuous_text.append(text)

        # Join with double newlines to maintain paragraph structure
        return '\n\n'.join(continuous_text)

    def detect_chapter_breaks(self, pages: List[Dict]) -> List[Dict]:
        """
        Detect chapter/section breaks in the text.

        Returns list of chapter metadata dicts.
        """
        chapters = []
        current_chapter = None
        chapter_num = 0

        chapter_patterns = [
            r'^CHAPTER\s+[IVXLCDM\d]+',  # CHAPTER 1, CHAPTER I
            r'^PROLOGUE$',
            r'^EPILOGUE$',
            r'^INTRODUCTION$',
            r'^PREFACE$',
            r'^PART\s+[IVXLCDM\d]+',
        ]

        for page in pages:
            if not page["has_content"]:
                continue

            lines = page["text"].split('\n')

            # Check first few lines for chapter markers
            for line in lines[:5]:
                line = line.strip().upper()
                if any(re.match(pattern, line) for pattern in chapter_patterns):
                    # Save previous chapter if exists
                    if current_chapter:
                        chapters.append(current_chapter)

                    # Start new chapter
                    chapter_num += 1
                    current_chapter = {
                        "chapter_number": chapter_num,
                        "title": line,
                        "start_page": page["page_number"],
                        "end_page": page["page_number"],
                        "pages": [page["page_number"]]
                    }
                    break

            # Add page to current chapter
            if current_chapter:
                current_chapter["end_page"] = page["page_number"]
                current_chapter["pages"].append(page["page_number"])

        # Don't forget the last chapter
        if current_chapter:
            chapters.append(current_chapter)

        return chapters

    def save_page_structure(self, pages: List[Dict]):
        """Save individual page files with metadata."""
        print(f"\n💾 Saving page structure...")

        # Save individual page files
        for page in pages:
            page_file = self.pages_dir / f"page_{page['page_number']:04d}.txt"
            with open(page_file, 'w') as f:
                f.write(page["text"])

        # Save page metadata JSON
        metadata_file = self.pages_dir / "pages_metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(pages, f, indent=2)

        print(f"   ✓ Saved {len(pages)} individual page files")
        print(f"   ✓ Saved pages_metadata.json")

    def save_logical_structure(self, continuous_text: str, chapters: List[Dict], pages: List[Dict]):
        """Save continuous reading text and chapter metadata."""
        print(f"\n📚 Saving logical structure...")

        # Save full continuous text
        full_text_file = self.logical_dir / "full_text.txt"
        with open(full_text_file, 'w') as f:
            f.write(continuous_text)

        print(f"   ✓ Saved full_text.txt ({len(continuous_text):,} chars)")

        # Save chapter metadata
        if chapters:
            chapters_file = self.logical_dir / "chapters.json"
            with open(chapters_file, 'w') as f:
                json.dump(chapters, f, indent=2)
            print(f"   ✓ Saved chapters.json ({len(chapters)} chapters)")

            # Save individual chapter files
            for chapter in chapters:
                chapter_pages = [p for p in pages if p["page_number"] in chapter["pages"]]
                chapter_text = self.merge_logical_structure(chapter_pages)

                chapter_file = self.logical_dir / f"chapter_{chapter['chapter_number']:02d}.txt"
                with open(chapter_file, 'w') as f:
                    # Add chapter header
                    f.write(f"{chapter['title']}\n")
                    f.write(f"Pages {chapter['start_page']}-{chapter['end_page']}\n\n")
                    f.write(chapter_text)

            print(f"   ✓ Saved {len(chapters)} individual chapter files")
        else:
            print(f"   ⚠️  No chapters detected")

    def generate_summary_report(self, pages: List[Dict], chapters: List[Dict]) -> Dict:
        """Generate summary statistics for the merge."""
        total_chars = sum(p["char_count"] for p in pages)
        total_words = sum(p["word_count"] for p in pages)
        empty_pages = sum(1 for p in pages if not p["has_content"])

        return {
            "book_slug": self.book_slug,
            "total_pages": len(pages),
            "pages_with_content": len(pages) - empty_pages,
            "empty_pages": empty_pages,
            "total_characters": total_chars,
            "total_words": total_words,
            "chapters_detected": len(chapters),
            "average_chars_per_page": total_chars // len(pages) if pages else 0,
            "average_words_per_page": total_words // len(pages) if pages else 0
        }

    def merge(self):
        """Main merge process."""
        print("=" * 60)
        print("📖 Merging LLM-corrected pages")
        print(f"   Book: {self.book_slug}")
        print("=" * 60)

        # Load metadata
        metadata = self.load_metadata()
        total_pages = metadata.get("total_pages", 0)
        print(f"\n📄 Processing {total_pages} pages...")

        # Process each page
        pages = []
        processed_count = 0

        for page_num in range(1, total_pages + 1):
            corrected_file = self.corrected_dir / f"page_{page_num:04d}.txt"

            if not corrected_file.exists():
                print(f"   ⚠️  Page {page_num} not found, skipping...")
                continue

            with open(corrected_file) as f:
                raw_text = f.read()

            page_data = self.process_page_structure(page_num, raw_text)
            pages.append(page_data)
            processed_count += 1

            if processed_count % 50 == 0:
                print(f"   ... processed {processed_count}/{total_pages} pages")

        print(f"   ✓ Processed {processed_count} pages")

        # Detect chapters
        print(f"\n🔍 Detecting chapter structure...")
        chapters = self.detect_chapter_breaks(pages)

        # Create logical continuous text
        print(f"\n📝 Creating continuous text...")
        continuous_text = self.merge_logical_structure(pages)

        # Save both structures
        self.save_page_structure(pages)
        self.save_logical_structure(continuous_text, chapters, pages)

        # Generate and save summary
        summary = self.generate_summary_report(pages, chapters)
        summary_file = self.output_dir / "merge_summary.json"
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)

        # Print summary
        print("\n" + "=" * 60)
        print("✅ MERGE COMPLETE")
        print("=" * 60)
        print(f"\n📊 Summary:")
        print(f"   Total pages: {summary['total_pages']}")
        print(f"   Pages with content: {summary['pages_with_content']}")
        print(f"   Empty pages: {summary['empty_pages']}")
        print(f"   Total words: {summary['total_words']:,}")
        print(f"   Total characters: {summary['total_characters']:,}")
        print(f"   Chapters detected: {summary['chapters_detected']}")
        print(f"   Avg words/page: {summary['average_words_per_page']}")

        print(f"\n📁 Output structure:")
        print(f"   Logical: {self.logical_dir}")
        print(f"   Pages:   {self.pages_dir}")
        print(f"   Summary: {summary_file}")
        print()


def main():
    if len(sys.argv) != 2:
        print("Usage: python book_llm_merge.py <book-slug>")
        print("Example: python book_llm_merge.py The-Accidental-President")
        sys.exit(1)

    book_slug = sys.argv[1]
    merger = BookMerger(book_slug)
    merger.merge()


if __name__ == "__main__":
    main()