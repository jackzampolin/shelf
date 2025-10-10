"""
PDF Utilities

Helper functions for working with PDF files:
- Extract page images for vision model validation
- Handle multi-PDF books (e.g., book split across multiple PDFs)
- Convert images to base64 for API calls
"""

from pathlib import Path
from typing import List
import base64
import io
from PIL import Image
import logging

logger = logging.getLogger(__name__)

try:
    from pdf2image import convert_from_path
    from pdf2image.pdf2image import pdfinfo_from_path
except ImportError:
    logger.warning("pdf2image not available - PDF image extraction will fail")
    convert_from_path = None
    pdfinfo_from_path = None


def get_page_from_book(
    book_dir: Path,
    page_number: int,
    dpi: int = 150,
) -> Image.Image:
    """
    Extract a page image from a multi-PDF book.

    Handles books split across multiple PDF files. Uses the same pattern as
    Stage 2 (Correction) for consistent multi-PDF handling.

    Args:
        book_dir: Path to book directory (contains source/ subdirectory with PDFs)
        page_number: Global page number (1-indexed, continuous across all PDFs)
        dpi: Resolution for rendering (default 150 for good quality/size balance)

    Returns:
        PIL Image of the requested page

    Raises:
        FileNotFoundError: If no PDFs found in source directory
        ValueError: If page_number is out of range
        ImportError: If pdf2image not installed

    Example:
        # Get page 195 from book with 5 PDFs (pages 1-447)
        image = get_page_from_book(
            Path("~/Documents/book_scans/my-book"),
            page_number=195,
            dpi=150
        )
    """
    if convert_from_path is None or pdfinfo_from_path is None:
        raise ImportError(
            "pdf2image not installed. Run: uv pip install pdf2image"
        )

    # Get sorted list of source PDFs
    source_dir = book_dir / "source"
    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    pdf_files = sorted(source_dir.glob("*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in {source_dir}")

    # Find which PDF contains this page
    page_offset = 0
    for pdf_path in pdf_files:
        # Get page count for this PDF
        info = pdfinfo_from_path(str(pdf_path))
        page_count = info['Pages']

        # Check if page is in this PDF
        if page_number <= page_offset + page_count:
            # Calculate local page number within this PDF (1-indexed)
            local_page = page_number - page_offset

            logger.debug(
                f"Page {page_number} found in {pdf_path.name} "
                f"(local page {local_page}/{page_count})"
            )

            # Extract the page
            images = convert_from_path(
                str(pdf_path),
                dpi=dpi,
                first_page=local_page,
                last_page=local_page
            )

            return images[0]

        page_offset += page_count

    # Page not found in any PDF
    raise ValueError(
        f"Page {page_number} not found in book "
        f"(total pages across {len(pdf_files)} PDFs: {page_offset})"
    )


def get_pages_from_book(
    book_dir: Path,
    page_numbers: List[int],
    dpi: int = 150,
) -> List[Image.Image]:
    """
    Extract multiple pages from a multi-PDF book.

    Args:
        book_dir: Path to book directory
        page_numbers: List of global page numbers to extract
        dpi: Resolution for rendering

    Returns:
        List of PIL Images in the same order as page_numbers

    Example:
        # Get pages 100, 101, 102 for ±1 window around page 101
        images = get_pages_from_book(
            book_dir,
            page_numbers=[100, 101, 102],
            dpi=150
        )
    """
    images = []
    for page_num in page_numbers:
        try:
            image = get_page_from_book(book_dir, page_num, dpi=dpi)
            images.append(image)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(f"Could not extract page {page_num}: {e}")
            # Continue with other pages even if one fails

    return images


def extract_page_images(
    pdf_path: Path,
    page_numbers: List[int],
    dpi: int = 150,
) -> List[Image.Image]:
    """
    Extract specific pages from PDF as PIL Images.

    Args:
        pdf_path: Path to PDF file
        page_numbers: List of page numbers to extract (1-indexed)
        dpi: Resolution for rendering (default 150 for good quality/size balance)

    Returns:
        List of PIL Images, one per page

    Raises:
        FileNotFoundError: If PDF doesn't exist
        ImportError: If pdf2image not installed
    """
    if convert_from_path is None:
        raise ImportError(
            "pdf2image not installed. Run: uv pip install pdf2image"
        )

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Sort page numbers to extract in order
    sorted_pages = sorted(page_numbers)

    logger.debug(
        f"Extracting {len(sorted_pages)} pages from {pdf_path.name} "
        f"at {dpi} DPI"
    )

    # Extract pages
    # Note: pdf2image is 1-indexed, page_numbers list is also 1-indexed
    images = convert_from_path(
        pdf_path,
        dpi=dpi,
        first_page=min(sorted_pages),
        last_page=max(sorted_pages),
    )

    # Filter to only requested pages
    # pdf2image returns all pages in range, we may only want specific ones
    page_range = range(min(sorted_pages), max(sorted_pages) + 1)
    page_to_image = dict(zip(page_range, images))

    result = []
    for page_num in page_numbers:
        if page_num in page_to_image:
            result.append(page_to_image[page_num])
        else:
            logger.warning(f"Page {page_num} not found in extracted range")

    return result


def image_to_base64(image: Image.Image, format: str = "JPEG") -> str:
    """
    Convert PIL Image to base64 string for API calls.

    Args:
        image: PIL Image
        format: Image format (JPEG, PNG, etc.)

    Returns:
        Base64-encoded image string (without data URI prefix)
    """
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode('utf-8')


def extract_page_image_base64(
    pdf_path: Path,
    page_number: int,
    dpi: int = 150,
) -> str:
    """
    Extract a single page from PDF as base64-encoded image.

    Convenience function combining extract_page_images + image_to_base64.

    Args:
        pdf_path: Path to PDF file
        page_number: Page number to extract (1-indexed)
        dpi: Resolution for rendering

    Returns:
        Base64-encoded JPEG image string
    """
    images = extract_page_images(pdf_path, [page_number], dpi=dpi)

    if not images:
        raise ValueError(f"Could not extract page {page_number} from {pdf_path}")

    return image_to_base64(images[0])
