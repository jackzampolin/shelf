"""
Book Ingestion Tool

Scans directories for book PDFs, extracts pages, and registers them in the library system.
Book identification is based on filename patterns.
"""

import re
import json
import shutil
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

from pdf2image import convert_from_path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from infra.config import Config
from tools.library import LibraryIndex


def _slugify_title(title: str) -> str:
    """Convert title to URL-safe slug (inline replacement for deleted tools.names)."""
    slug = title.lower()
    slug = re.sub(r'^(the|a|an)\s+', '', slug)
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')[:50]


def _ensure_unique_slug(base_slug: str, existing_ids: list) -> str:
    """Ensure slug is unique (inline replacement for deleted tools.names)."""
    if base_slug in existing_ids:
        raise ValueError(f"Scan ID '{base_slug}' already exists. Use --id to specify different name.")
    return base_slug


def _extract_single_page(task: Tuple[Path, int, Path, int]) -> Tuple[bool, int, Optional[str]]:
    """
    Extract a single page from PDF (worker function for parallel extraction).

    Args:
        task: (pdf_path, local_page_num, output_path, dpi)

    Returns:
        (success: bool, global_page_num: int, error_msg: Optional[str])
    """
    pdf_path, local_page, output_path, dpi = task

    try:
        # Convert single page to image
        page_images = convert_from_path(
            pdf_path,
            first_page=local_page,
            last_page=local_page,
            dpi=dpi
        )

        if page_images:
            # Save as PNG
            page_images[0].save(output_path, format='PNG')
            return (True, None)
        else:
            return (False, f"No image returned for page {local_page}")

    except Exception as e:
        return (False, str(e))


def group_batch_pdfs(pdf_paths: List[Path]) -> Dict[str, List[Path]]:
    """
    Group PDFs that belong to the same book based on filename patterns.

    Examples:
        hap-arnold-1.pdf, hap-arnold-2.pdf -> "hap-arnold": [1.pdf, 2.pdf]
        book-part1.pdf, book-part2.pdf -> "book": [part1.pdf, part2.pdf]

    Returns:
        Dict mapping base name to list of PDF paths
    """
    groups = defaultdict(list)

    for pdf_path in pdf_paths:
        name = pdf_path.stem  # Filename without extension

        # Remove common batch indicators
        base_name = re.sub(r'[-_](part|batch|section|volume)?[-_]?\d+$', '', name, flags=re.IGNORECASE)

        groups[base_name].append(pdf_path)

    # Sort PDFs within each group
    for base_name in groups:
        groups[base_name] = sorted(groups[base_name])

    return dict(groups)


def ingest_book_group(
    base_name: str,
    pdf_paths: List[Path],
    library: LibraryIndex,
    auto_confirm: bool = False
) -> Optional[str]:
    """
    Ingest a group of PDFs as a single book.

    Args:
        base_name: Base filename (e.g., "hap-arnold") - used as scan_id
        pdf_paths: List of batch PDF files
        library: LibraryIndex instance
        auto_confirm: Skip confirmation prompts

    Returns:
        Scan ID if successful, None otherwise
    """
    print(f"\n📚 Processing: {base_name}")
    print(f"   PDFs: {len(pdf_paths)}")

    # Use base_name as scan_id and title
    scan_id = base_name
    title = base_name.replace('-', ' ').replace('_', ' ').title()
    author = 'Unknown'
    year = None
    publisher = None
    isbn = None

    print(f"   Using filename as title: {title}")
    print(f"   Scan ID: {scan_id}")

    # Check scan_id is unique
    existing_ids = [
        scan['scan_id']
        for book in library.data['books'].values()
        for scan in book['scans']
    ]

    if scan_id in existing_ids:
        print(f"\n   ❌ Error: Scan ID '{scan_id}' already exists in library")
        return None

    print(f"\n   📖 Book Info:")
    print(f"      Title:     {title}")
    print(f"      Author:    {author}")
    print(f"      Scan ID:   {scan_id}")

    # Create directory structure
    scan_dir = library.storage_root / scan_id
    scan_dir.mkdir(exist_ok=True)

    source_dir = scan_dir / "source"
    source_dir.mkdir(exist_ok=True)

    # Extract all pages as individual PNG files to source/ (parallelized)
    print(f"   Extracting pages from {len(pdf_paths)} PDF(s) at {Config.PDF_EXTRACTION_DPI_OCR} DPI...")
    from pdf2image import pdfinfo_from_path

    # Build list of all extraction tasks across all PDFs
    tasks = []
    global_page_num = 1

    for pdf_idx, pdf_path in enumerate(pdf_paths, 1):
        # Copy source PDF for reference
        dest_pdf = source_dir / f"{base_name}-{pdf_idx}.pdf"
        shutil.copy2(pdf_path, dest_pdf)

        # Get page count
        info = pdfinfo_from_path(pdf_path)
        page_count = info['Pages']

        # Create task for each page
        for local_page in range(1, page_count + 1):
            output_path = source_dir / f"page_{global_page_num:04d}.png"
            tasks.append((pdf_path, local_page, output_path, Config.PDF_EXTRACTION_DPI_OCR))
            global_page_num += 1

    total_pages = len(tasks)
    print(f"     Processing {total_pages} pages in parallel...")

    # Extract in parallel using all CPU cores
    max_workers = multiprocessing.cpu_count()
    completed = 0
    failed = 0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {executor.submit(_extract_single_page, task): task for task in tasks}

        for future in as_completed(future_to_task):
            task = future_to_task[future]
            pdf_path, local_page, output_path, dpi = task

            try:
                success, error_msg = future.result()
                if success:
                    completed += 1
                else:
                    failed += 1
                    print(f"       ⚠️  Failed {output_path.name}: {error_msg}")
            except Exception as e:
                failed += 1
                print(f"       ⚠️  Exception for {output_path.name}: {e}")

            # Progress update every 10 pages
            if (completed + failed) % 10 == 0:
                print(f"     Progress: {completed + failed}/{total_pages} pages ({completed} ok, {failed} failed)")

    print(f"     ✓ Extracted {completed}/{total_pages} pages → source/")
    if failed > 0:
        print(f"     ⚠️  {failed} pages failed")

    # Create initial metadata.json
    metadata = {
        "title": title,
        "author": author,
        "isbn": isbn,
        "scan_date": datetime.now().isoformat(),
        "source_files": [f"{base_name}-{i}.pdf" for i in range(1, len(pdf_paths) + 1)],
        "total_pages": completed,
        "status": "registered",
        "extraction_dpi": Config.PDF_EXTRACTION_DPI_OCR,
        "extraction_workers": max_workers
    }

    metadata_file = scan_dir / "metadata.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    # Register in library
    library.add_book(
        title=title,
        author=author,
        scan_id=scan_id,
        isbn=isbn,
        year=year,
        source_file=", ".join([p.name for p in pdf_paths]),
        notes=f"Ingested from {pdf_paths[0].parent}"
    )

    print(f"   ✓ Registered in library")
    print(f"   ✓ Created: {scan_dir}")

    return scan_id


def ingest_from_directories(
    directories: List[Path],
    auto_confirm: bool = False
) -> List[str]:
    """
    Scan directories for book PDFs and ingest them.

    Args:
        directories: List of directories to scan
        auto_confirm: Skip confirmation prompts

    Returns:
        List of scan IDs created
    """
    library = LibraryIndex()

    # Find all PDFs
    all_pdfs = []
    for directory in directories:
        directory = Path(directory).expanduser()
        if not directory.exists():
            print(f"⚠️  Directory not found: {directory}")
            continue

        pdfs = list(directory.glob("*.pdf"))
        all_pdfs.extend(pdfs)
        print(f"Found {len(pdfs)} PDF(s) in {directory}")

    if not all_pdfs:
        print("No PDFs found.")
        return []

    # Group by book
    groups = group_batch_pdfs(all_pdfs)

    print(f"\nDetected {len(groups)} book(s):")
    for base_name, pdfs in groups.items():
        print(f"  • {base_name}: {len(pdfs)} PDF(s)")

    # Process each group
    scan_ids = []
    for base_name, pdfs in groups.items():
        scan_id = ingest_book_group(base_name, pdfs, library, auto_confirm)
        if scan_id:
            scan_ids.append(scan_id)

    # Summary
    print(f"\n✓ Ingested {len(scan_ids)} book(s)")
    if scan_ids:
        print("\nNext steps:")
        for scan_id in scan_ids:
            print(f"  ar pipeline {scan_id}")

    return scan_ids


def add_books_to_library(pdf_paths: List[Path], storage_root: Path = None, run_ocr: bool = False) -> Dict[str, Any]:
    """
    Add books to library (CLI wrapper).

    Args:
        pdf_paths: List of PDF file paths
        storage_root: Storage root (defaults to Config.BOOK_STORAGE_ROOT)
        run_ocr: If True, automatically run OCR stage after adding (default: False)

    Returns:
        Dict with books_added count and scan_ids list
    """
    library = LibraryIndex(storage_root=storage_root)

    # Group PDFs by book
    groups = group_batch_pdfs(pdf_paths)

    print(f"\nDetected {len(groups)} book(s):")
    for base_name, pdfs in groups.items():
        print(f"  • {base_name}: {len(pdfs)} PDF(s)")

    # Process each group
    scan_ids = []
    for base_name, pdfs in groups.items():
        scan_id = ingest_book_group(base_name, pdfs, library, auto_confirm=True)
        if scan_id:
            scan_ids.append(scan_id)

    # Run OCR if requested
    if run_ocr and scan_ids:
        print(f"\n🔍 Running OCR on {len(scan_ids)} book(s)...")
        import importlib
        ocr_module = importlib.import_module('pipeline.1_ocr')
        BookOCRProcessor = getattr(ocr_module, 'BookOCRProcessor')

        processor = BookOCRProcessor(
            storage_root=str(storage_root or Config.BOOK_STORAGE_ROOT),
            max_workers=8
        )

        for scan_id in scan_ids:
            print(f"\n📄 OCR: {scan_id}")
            processor.process_book(scan_id, resume=False)

    return {
        'books_added': len(scan_ids),
        'scan_ids': scan_ids
    }


if __name__ == "__main__":
    import sys

    directories = sys.argv[1:] if len(sys.argv) > 1 else [
        "~/Documents/Scans",
        "~/Documents/ScanSnap"
    ]

    ingest_from_directories(directories)
