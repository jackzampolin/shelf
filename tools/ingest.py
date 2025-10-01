"""
Smart Book Ingestion Tool

Scans directories for book PDFs, intelligently identifies them using LLM + web search,
and properly registers them in the library system.
"""

import re
import json
import shutil
import base64
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from io import BytesIO

import requests
from pdf2image import convert_from_path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from pricing import CostCalculator

from config import Config
from tools.library import LibraryIndex
from tools.names import ensure_unique_scan_id


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


def sample_pdf_pages(pdf_path: Path, num_samples: int = 10) -> List[str]:
    """
    Extract images from the first N pages of a PDF.

    Title pages and copyright pages are almost always in the first few pages,
    so we sample from the start rather than randomly throughout the document.

    Args:
        pdf_path: Path to PDF
        num_samples: Number of pages to sample from start (default 10)

    Returns:
        List of base64-encoded PNG images
    """
    from pdf2image import pdfinfo_from_path

    # Get total page count
    info = pdfinfo_from_path(pdf_path)
    total_pages = info['Pages']

    # Sample first N pages (where title/copyright/TOC usually are)
    page_numbers = list(range(1, min(num_samples + 1, total_pages + 1)))

    print(f"  Sampling first {len(page_numbers)} pages: {page_numbers}")

    images = []
    for page_num in page_numbers:
        try:
            # Convert single page
            page_images = convert_from_path(
                pdf_path,
                first_page=page_num,
                last_page=page_num,
                dpi=150
            )

            if page_images:
                buffer = BytesIO()
                page_images[0].save(buffer, format='PNG')
                img_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                images.append(img_b64)
        except Exception as e:
            print(f"    ⚠️  Failed to extract page {page_num}: {e}")

    return images


def identify_book_with_llm(pdf_paths: List[Path]) -> Optional[Dict]:
    """
    Use LLM vision model to identify book from PDF samples.

    Args:
        pdf_paths: List of PDF files for this book (batch files)

    Returns:
        Dict with title, author, and other identifiable metadata
    """
    print(f"  Analyzing {len(pdf_paths)} PDF(s) with LLM...")

    # Sample first 10 pages from first PDF (where title/copyright pages are)
    images = sample_pdf_pages(pdf_paths[0], num_samples=10)

    if not images:
        print("    ✗ No pages extracted")
        return None

    # Build prompt
    prompt = """Analyze the FIRST PAGES from this scanned book and identify:

1. **Title**: The complete book title
2. **Author**: Author name(s)
3. **Type**: Type of book (biography, history, memoir, political analysis, etc.)

You are looking at the FIRST 10 pages of the book, which typically contain:
- Title page (usually page 1-3)
- Copyright page with publisher info
- Table of contents
- Dedication or introduction

Look carefully for:
- Large title text on title page
- Author name on title page or copyright page
- Publisher and publication year on copyright page
- Subtitle or series information

Return ONLY the information you can clearly see. Do not guess based on content.

Return as JSON:
```json
{
  "title": "Complete Book Title: With Subtitle if Present",
  "author": "Author Full Name",
  "type": "biography",
  "confidence": 0.9,
  "year": 2010,
  "publisher": "Publisher Name"
}
```

If you cannot find a clear title page, return confidence < 0.5 with null values.
"""

    # Build message with images (using OpenAI vision format for OpenRouter)
    content = [{"type": "text", "text": prompt}]
    for img_b64 in images:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}"
            }
        })

    try:
        # Call OpenRouter API
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {Config.OPEN_ROUTER_API_KEY}",
                "HTTP-Referer": Config.OPEN_ROUTER_SITE_URL,
                "X-Title": Config.OPEN_ROUTER_SITE_NAME,
                "Content-Type": "application/json"
            },
            json={
                "model": Config.STRUCTURE_MODEL,  # Claude Sonnet 4.5
                "messages": [{"role": "user", "content": content}]
            },
            timeout=60
        )

        response.raise_for_status()
        result = response.json()

        # Track cost using dynamic pricing
        usage = result.get('usage', {})
        if usage:
            calc = CostCalculator()
            cost = calc.calculate_cost(
                Config.STRUCTURE_MODEL,
                usage.get('prompt_tokens', 0),
                usage.get('completion_tokens', 0),
                num_images=len(images)
            )
            print(f"    💰 LLM cost: ${cost:.4f}")

        # Extract JSON from response
        assistant_message = result["choices"][0]["message"]["content"]
        metadata = extract_json_from_text(assistant_message)

        if metadata:
            print(f"    ✓ Identified: {metadata.get('title')} by {metadata.get('author')}")
            print(f"      Confidence: {metadata.get('confidence', 0.0)}")
            return metadata
        else:
            print("    ✗ Failed to parse LLM response")
            print(f"    Response was: {assistant_message[:200]}...")
            return None

    except Exception as e:
        print(f"    ✗ Error: {e}")
        return None


def search_book_metadata(title: str, author: str = None) -> Optional[Dict]:
    """
    Search online for complete book metadata using web search.

    Args:
        title: Book title
        author: Author name (optional)

    Returns:
        Dict with ISBN, year, publisher, etc.
    """
    # Build search query
    query_parts = [title]
    if author:
        query_parts.append(author)
    query_parts.extend(["book", "ISBN"])

    query = " ".join(query_parts)

    print(f"  Searching: {query}")

    # Use web search tool (would need to import WebSearch)
    # For now, return None and let user fill in manually
    # In production, integrate with WebSearch or Google Books API

    return None


def ingest_book_group(
    base_name: str,
    pdf_paths: List[Path],
    library: LibraryIndex,
    auto_confirm: bool = False
) -> Optional[str]:
    """
    Ingest a group of PDFs as a single book.

    Args:
        base_name: Base filename (e.g., "hap-arnold")
        pdf_paths: List of batch PDF files
        library: LibraryIndex instance
        auto_confirm: Skip confirmation prompts

    Returns:
        Scan ID if successful, None otherwise
    """
    print(f"\n📚 Processing: {base_name}")
    print(f"   PDFs: {len(pdf_paths)}")

    # Step 1: Identify with LLM
    llm_metadata = identify_book_with_llm(pdf_paths)

    if not llm_metadata or llm_metadata.get('confidence', 0) < 0.5:
        print("   ⚠️  Low confidence identification")
        if not auto_confirm:
            response = input("   Continue anyway? (y/n): ").strip().lower()
            if response != 'y':
                return None

    # Step 2: Get title and author from LLM, with filename fallback
    if llm_metadata and llm_metadata.get('confidence', 0) >= 0.5:
        # Trust LLM if confidence is decent
        title = llm_metadata.get('title', base_name)
        author = llm_metadata.get('author', 'Unknown')
        year = llm_metadata.get('year', None)
        publisher = llm_metadata.get('publisher', None)
    else:
        # Fallback to cleaned-up filename
        title = base_name.replace('-', ' ').replace('_', ' ').title()
        author = 'Unknown'
        year = None
        publisher = None
        print(f"   Using filename as title: {title}")

    # Step 3: Search for additional metadata (currently disabled)
    web_metadata = search_book_metadata(title, author)

    # Step 4: Present findings and get confirmation
    print(f"\n   📖 Identified:")
    print(f"      Title:     {title}")
    print(f"      Author:    {author}")
    if year:
        print(f"      Year:      {year}")
    if publisher:
        print(f"      Publisher: {publisher}")
    if web_metadata:
        print(f"      ISBN:      {web_metadata.get('isbn')}")

    if not auto_confirm:
        print("\n   Options:")
        print("     1. Accept")
        print("     2. Edit metadata")
        print("     3. Skip")

        try:
            choice = input("   Choice (1/2/3): ").strip()
        except EOFError:
            # Non-interactive mode, accept defaults
            choice = '1'

        if choice == '2':
            try:
                title = input(f"   Title [{title}]: ").strip() or title
                author = input(f"   Author [{author}]: ").strip() or author
                isbn = input("   ISBN: ").strip() or None
                year_input = input("   Year: ").strip()
                year = int(year_input) if year_input else None
            except EOFError:
                isbn = None
                year = None
        elif choice == '3':
            return None
        else:
            # Prefer LLM-extracted year over web metadata
            isbn = web_metadata.get('isbn') if web_metadata else None
            if not year:
                year = web_metadata.get('year') if web_metadata else None
    else:
        # Prefer LLM-extracted year over web metadata
        isbn = web_metadata.get('isbn') if web_metadata else None
        if not year:
            year = web_metadata.get('year') if web_metadata else None

    # Step 5: Generate scan ID
    existing_ids = [
        scan['scan_id']
        for book in library.data['books'].values()
        for scan in book['scans']
    ]
    scan_id = ensure_unique_scan_id(existing_ids)

    print(f"\n   Scan ID: {scan_id}")

    # Step 6: Create directory structure
    scan_dir = library.storage_root / scan_id
    scan_dir.mkdir(exist_ok=True)

    source_dir = scan_dir / "source"
    source_dir.mkdir(exist_ok=True)

    # Step 7: Copy PDFs to source/
    print(f"   Copying PDFs...")
    for i, pdf_path in enumerate(pdf_paths, 1):
        dest = source_dir / f"{base_name}-{i}.pdf"
        shutil.copy2(pdf_path, dest)
        print(f"     ✓ {pdf_path.name} → {dest.name}")

    # Step 8: Create initial metadata.json
    metadata = {
        "title": title,
        "author": author,
        "isbn": isbn,
        "scan_date": datetime.now().isoformat(),
        "source_files": [f"{base_name}-{i}.pdf" for i in range(1, len(pdf_paths) + 1)],
        "status": "registered"
    }

    metadata_file = scan_dir / "metadata.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    # Step 9: Register in library
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


def extract_json_from_text(text: str) -> Optional[Dict]:
    """Extract JSON object from text."""
    import re

    # Try code blocks first
    code_block_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
    matches = re.findall(code_block_pattern, text, re.DOTALL)

    if matches:
        try:
            return json.loads(matches[0])
        except json.JSONDecodeError:
            pass

    # Try raw JSON
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, text, re.DOTALL)

    for match in matches:
        try:
            data = json.loads(match)
            if "title" in data or "author" in data:
                return data
        except json.JSONDecodeError:
            continue

    return None


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


if __name__ == "__main__":
    import sys

    directories = sys.argv[1:] if len(sys.argv) > 1 else [
        "~/Documents/Scans",
        "~/Documents/ScanSnap"
    ]

    ingest_from_directories(directories)
