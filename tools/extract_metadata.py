#!/usr/bin/env python3
"""
Extract book metadata from OCR text using LLM.

Reads the first 10-20 pages of OCR output and uses an LLM to identify:
- Title
- Author(s)
- Publication year
- Publisher
- Book type (biography, history, memoir, etc.)

Updates the book's metadata.json with extracted information.
"""

import json
import sys
from pathlib import Path
from typing import Optional, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from infra.config import Config
from infra.llm.client import LLMClient


def extract_book_metadata(scan_id: str, storage_root: Optional[Path] = None, num_pages: int = 15) -> Optional[Dict]:
    """
    Extract book metadata from OCR text using LLM.

    Args:
        scan_id: Book scan ID
        storage_root: Root directory for book storage (default: ~/Documents/book_scans)
        num_pages: Number of pages to analyze from start (default: 15)

    Returns:
        Dict with extracted metadata, or None if extraction fails
    """
    storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
    book_dir = storage_root / scan_id

    if not book_dir.exists():
        print(f"❌ Book directory not found: {book_dir}")
        return None

    # Check for OCR outputs
    ocr_dir = book_dir / "ocr"
    if not ocr_dir.exists():
        print(f"❌ No OCR directory found. Run OCR stage first.")
        return None

    ocr_files = sorted(ocr_dir.glob("page_*.json"))
    if not ocr_files:
        print(f"❌ No OCR outputs found. Run OCR stage first.")
        return None

    print(f"\n📖 Extracting metadata from: {scan_id}")
    print(f"   Analyzing first {min(num_pages, len(ocr_files))} pages...")

    # Collect text from first N pages
    pages_text = []
    for i, ocr_file in enumerate(ocr_files[:num_pages], 1):
        try:
            with open(ocr_file, 'r') as f:
                ocr_data = json.load(f)

            # Extract all text from blocks/paragraphs
            page_text = []
            for block in ocr_data.get('blocks', []):
                for para in block.get('paragraphs', []):
                    text = para.get('text', '').strip()
                    if text:
                        page_text.append(text)

            if page_text:
                pages_text.append(f"--- Page {i} ---\n" + "\n".join(page_text))

        except Exception as e:
            print(f"   ⚠️  Failed to read page {i}: {e}")
            continue

    if not pages_text:
        print(f"❌ No text extracted from OCR files")
        return None

    combined_text = "\n\n".join(pages_text)
    print(f"   Extracted {len(combined_text)} characters from {len(pages_text)} pages")

    # Build prompt for metadata extraction
    prompt = f"""<task>
Analyze the text from the FIRST PAGES of this scanned book and extract bibliographic metadata.

These pages typically contain:
- Title page (large title text)
- Copyright page (publisher, year, ISBN)
- Table of contents
- Dedication or foreword

Extract the following information:
- title: Complete book title including subtitle
- author: Author name(s) - format as "First Last" or "First Last and First Last"
- year: Publication year (integer)
- publisher: Publisher name
- type: Book genre/type (biography, history, memoir, political_analysis, military_history, etc.)
- isbn: ISBN if visible (can be null)

Return ONLY information you can clearly identify from the text. Do not guess.
Set confidence to 0.9+ if information is on a clear title/copyright page.
Set confidence to 0.5-0.8 if inferred from content.
Set confidence below 0.5 if uncertain.
</task>

<text>
{combined_text[:15000]}
</text>

<output_format>
Return JSON only. No explanations.
</output_format>"""

    # Define JSON schema for structured output
    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "book_metadata",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "author": {"type": ["string", "null"]},
                    "year": {"type": ["integer", "null"]},
                    "publisher": {"type": ["string", "null"]},
                    "type": {"type": ["string", "null"]},
                    "isbn": {"type": ["string", "null"]},
                    "confidence": {"type": "number"}
                },
                "required": ["title", "author", "year", "publisher", "type", "isbn", "confidence"],
                "additionalProperties": False
            }
        }
    }

    try:
        # Call LLM with structured output and JSON retry
        client = LLMClient()

        messages = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "{"}  # Prefill for JSON
        ]

        def parse_metadata_json(response_text):
            """Parse and validate metadata JSON."""
            data = json.loads(response_text)
            return data

        # call_with_json_retry returns already-parsed JSON
        metadata, usage, cost = client.call_with_json_retry(
            model=Config.VISION_MODEL,
            messages=messages,
            json_parser=parse_metadata_json,
            temperature=0.0,
            max_retries=3,
            response_format=response_schema,
            timeout=60
        )

        print(f"\n   ✓ Metadata extracted (confidence: {metadata.get('confidence', 0):.2f})")
        print(f"   Title:     {metadata.get('title', 'Unknown')}")
        print(f"   Author:    {metadata.get('author', 'Unknown')}")
        print(f"   Year:      {metadata.get('year', 'Unknown')}")
        print(f"   Publisher: {metadata.get('publisher', 'Unknown')}")
        print(f"   Type:      {metadata.get('type', 'Unknown')}")
        print(f"   Cost:      ${cost:.4f}")

        return metadata

    except Exception as e:
        print(f"❌ LLM metadata extraction failed: {e}")
        return None


def update_book_metadata(scan_id: str, storage_root: Optional[Path] = None, num_pages: int = 15):
    """
    Extract and update book metadata in metadata.json.

    Args:
        scan_id: Book scan ID
        storage_root: Root directory for book storage
        num_pages: Number of pages to analyze
    """
    storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
    book_dir = storage_root / scan_id
    metadata_file = book_dir / "metadata.json"

    # Extract metadata
    extracted = extract_book_metadata(scan_id, storage_root, num_pages)

    if not extracted:
        print("❌ Failed to extract metadata")
        return False

    # Load existing metadata
    if metadata_file.exists():
        with open(metadata_file, 'r') as f:
            metadata = json.load(f)
    else:
        metadata = {}

    # Update with extracted fields (only if confidence >= 0.5)
    confidence = extracted.get('confidence', 0)

    if confidence < 0.5:
        print(f"\n⚠️  Low confidence ({confidence:.2f}) - metadata not updated")
        print("   Review extracted values above and update manually if correct")
        return False

    # Update fields (preserve existing non-None values if extraction is None)
    for field in ['title', 'author', 'year', 'publisher', 'type', 'isbn']:
        extracted_value = extracted.get(field)
        if extracted_value is not None:
            metadata[field] = extracted_value

    metadata['metadata_extraction_confidence'] = confidence

    # Save updated metadata
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n✅ Metadata updated in {metadata_file.name}")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract book metadata from OCR text")
    parser.add_argument("scan_id", help="Book scan ID")
    parser.add_argument("--pages", type=int, default=15, help="Number of pages to analyze (default: 15)")
    parser.add_argument("--storage-root", help="Storage root directory")

    args = parser.parse_args()

    update_book_metadata(
        scan_id=args.scan_id,
        storage_root=Path(args.storage_root) if args.storage_root else None,
        num_pages=args.pages
    )
