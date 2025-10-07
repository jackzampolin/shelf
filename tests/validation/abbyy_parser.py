"""
ABBYY XML Parser for Internet Archive ground truth data.

Extracts text from ABBYY FineReader XML format (compressed .gz files)
to compare against Scanshelf OCR output.
"""

import gzip
from pathlib import Path
from typing import Optional
from lxml import etree


class ABBYYParser:
    """
    Parse ABBYY GZ format to extract ground truth text.

    ABBYY XML Structure:
    - <document> root with pages
    - Each <page> contains <block> elements
    - Blocks can be "Text", "Picture", "Table", etc.
    - Text blocks contain <text><par><line> hierarchy
    - Each line has <charParams> with individual characters

    Example Usage:
        parser = ABBYYParser("abbyy.gz")
        text = parser.get_page_text(10)  # Get page 10 text
        print(f"Total pages: {parser.get_page_count()}")
    """

    # ABBYY XML namespace
    NAMESPACE = {"abbyy": "http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml"}

    def __init__(self, abbyy_gz_path: str | Path):
        """
        Load and parse ABBYY XML from compressed file.

        Args:
            abbyy_gz_path: Path to .abbyy.gz file
        """
        self.path = Path(abbyy_gz_path)
        if not self.path.exists():
            raise FileNotFoundError(f"ABBYY file not found: {self.path}")

        # Parse XML from gzip file
        with gzip.open(self.path, 'rb') as f:
            self.tree = etree.parse(f)

        self.root = self.tree.getroot()

        # Cache page elements for faster access
        # Pages are direct children of root in ABBYY format
        self._pages = list(self.root)

    def get_page_count(self) -> int:
        """Get total number of pages in document."""
        return len(self._pages)

    def get_page_text(self, page_num: int, include_formatting: bool = False) -> str:
        """
        Extract clean text from a specific page.

        Args:
            page_num: Page number (1-indexed, matching PDF page numbers)
            include_formatting: If True, preserve spacing/structure hints

        Returns:
            Extracted text from the page

        Raises:
            IndexError: If page_num is out of range
        """
        if page_num < 1 or page_num > self.get_page_count():
            raise IndexError(
                f"Page {page_num} out of range (1-{self.get_page_count()})"
            )

        # Pages are 0-indexed in the list, but we use 1-indexed numbering
        page = self._pages[page_num - 1]

        # Extract all text blocks (need to use namespace-aware search)
        ns = {'a': 'http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml'}
        text_blocks = page.xpath('.//a:block[@blockType="Text"]', namespaces=ns)

        lines = []
        for block in text_blocks:
            block_text = self._extract_block_text(block, include_formatting)
            if block_text:
                lines.append(block_text)

        return '\n'.join(lines)

    def _extract_block_text(self, block, include_formatting: bool) -> str:
        """
        Extract text from a text block element.

        Args:
            block: XML block element
            include_formatting: Whether to preserve spacing

        Returns:
            Extracted text from block
        """
        lines = []

        # Find all line elements (namespace-aware)
        ns = {'a': 'http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml'}
        line_elements = block.xpath('.//a:line', namespaces=ns)

        for line_elem in line_elements:
            line_text = self._extract_line_text(line_elem)
            if line_text:
                lines.append(line_text)

        if include_formatting:
            # Preserve line breaks within block
            return '\n'.join(lines)
        else:
            # Join lines with spaces (more similar to OCR output)
            return ' '.join(lines)

    def _extract_line_text(self, line_elem) -> str:
        """
        Extract text from a line element.

        ABBYY stores text as individual character elements (<charParams>).
        We reconstruct the text by reading the character content.

        Args:
            line_elem: XML line element

        Returns:
            Reconstructed line text
        """
        chars = []

        # Get all charParams elements (individual characters)
        ns = {'a': 'http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml'}
        char_elements = line_elem.xpath('.//a:charParams', namespaces=ns)

        for char_elem in char_elements:
            # The text content of charParams is the actual character
            char_text = char_elem.text
            if char_text:
                chars.append(char_text)

        return ''.join(chars)

    def get_page_metadata(self, page_num: int) -> dict:
        """
        Get metadata for a specific page.

        Args:
            page_num: Page number (1-indexed)

        Returns:
            Dictionary with page metadata:
            - width: Page width
            - height: Page height
            - resolution: DPI resolution
            - text_blocks: Number of text blocks
            - picture_blocks: Number of picture blocks
        """
        if page_num < 1 or page_num > self.get_page_count():
            raise IndexError(
                f"Page {page_num} out of range (1-{self.get_page_count()})"
            )

        page = self._pages[page_num - 1]

        ns = {'a': 'http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml'}

        return {
            'width': int(page.get('width', 0)),
            'height': int(page.get('height', 0)),
            'resolution': int(page.get('resolution', 0)),
            'text_blocks': len(page.xpath('.//a:block[@blockType="Text"]', namespaces=ns)),
            'picture_blocks': len(page.xpath('.//a:block[@blockType="Picture"]', namespaces=ns)),
        }

    def get_page_confidence_scores(self, page_num: int) -> dict:
        """
        Get character confidence scores for a page.

        Args:
            page_num: Page number (1-indexed)

        Returns:
            Dictionary with:
            - avg_confidence: Average character confidence (0-100)
            - min_confidence: Lowest confidence score
            - suspicious_chars: Number of suspicious characters
        """
        if page_num < 1 or page_num > self.get_page_count():
            raise IndexError(
                f"Page {page_num} out of range (1-{self.get_page_count()})"
            )

        page = self._pages[page_num - 1]
        ns = {'a': 'http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml'}
        char_elements = page.xpath('.//a:charParams', namespaces=ns)

        if not char_elements:
            return {
                'avg_confidence': 0,
                'min_confidence': 0,
                'suspicious_chars': 0,
            }

        confidences = []
        suspicious_count = 0

        for char_elem in char_elements:
            conf = char_elem.get('charConfidence')
            suspicious = char_elem.get('suspicious')

            if conf is not None:
                confidences.append(int(conf))

            if suspicious == 'true':
                suspicious_count += 1

        if not confidences:
            return {
                'avg_confidence': 0,
                'min_confidence': 0,
                'suspicious_chars': suspicious_count,
            }

        return {
            'avg_confidence': sum(confidences) / len(confidences),
            'min_confidence': min(confidences),
            'suspicious_chars': suspicious_count,
        }


def extract_page_range(abbyy_gz_path: str | Path,
                      start_page: int,
                      end_page: int) -> dict[int, str]:
    """
    Convenience function to extract text from multiple pages.

    Args:
        abbyy_gz_path: Path to ABBYY .gz file
        start_page: First page to extract (1-indexed, inclusive)
        end_page: Last page to extract (1-indexed, inclusive)

    Returns:
        Dictionary mapping page numbers to extracted text
    """
    parser = ABBYYParser(abbyy_gz_path)

    results = {}
    for page_num in range(start_page, end_page + 1):
        try:
            results[page_num] = parser.get_page_text(page_num)
        except IndexError:
            break

    return results
