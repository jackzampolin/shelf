#!/usr/bin/env python3
"""
Download Internet Archive structured data for Roosevelt autobiography.

Downloads ground truth data for validation:
- ABBYY GZ: Industry-standard OCR with coordinates
- HOCR HTML: Alternative OCR format
- DjVu Text: Plain text fulltext
- Page Numbers JSON: Page mapping

Run once to set up validation data (~20MB total).
"""

import requests
from pathlib import Path
import sys


def download_file(url: str, output_path: Path) -> bool:
    """Download a file with progress indication."""
    try:
        print(f"⬇️  Downloading {output_path.name}...")
        response = requests.get(url, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"   {percent:.1f}% ({downloaded / 1024 / 1024:.1f} MB)", end='\r')

        size_mb = output_path.stat().st_size / 1024 / 1024
        print(f"✅ Downloaded {output_path.name} ({size_mb:.1f} MB)" + " " * 20)
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to download {output_path.name}: {e}")
        return False


def download_ia_data():
    """Download all Internet Archive validation data."""

    # Setup directories
    ia_dir = Path(__file__).parent / "roosevelt" / "ia_ground_truth"
    ia_dir.mkdir(parents=True, exist_ok=True)

    print("📚 Internet Archive Data Downloader")
    print("=" * 60)
    print(f"Book: Theodore Roosevelt: An Autobiography")
    print(f"Source: archive.org/details/theorooseauto00roosrich")
    print(f"Destination: {ia_dir}")
    print("=" * 60)
    print()

    # Base URL for Roosevelt book
    base_url = "https://archive.org/download/theorooseauto00roosrich"

    # Files to download
    files = {
        "abbyy.gz": "theorooseauto00roosrich_abbyy.gz",
        "hocr.html": "theorooseauto00roosrich_hocr.html",
        "djvu_text.txt": "theorooseauto00roosrich_djvu.txt",
        "page_numbers.json": "theorooseauto00roosrich_page_numbers.json"
    }

    # Download each file
    success_count = 0
    for local_name, ia_filename in files.items():
        output_path = ia_dir / local_name

        # Skip if already exists
        if output_path.exists():
            size_mb = output_path.stat().st_size / 1024 / 1024
            print(f"✓ {local_name} already exists ({size_mb:.1f} MB)")
            success_count += 1
            continue

        # Download file
        url = f"{base_url}/{ia_filename}"
        if download_file(url, output_path):
            success_count += 1

    print()
    print("=" * 60)

    if success_count == len(files):
        print("✅ All IA data downloaded successfully!")
        print()
        print("📊 Downloaded Files:")
        total_size = 0
        for file_path in ia_dir.glob("*"):
            if file_path.is_file():
                size_mb = file_path.stat().st_size / 1024 / 1024
                total_size += size_mb
                print(f"   {file_path.name}: {size_mb:.1f} MB")
        print(f"   Total: {total_size:.1f} MB")
        print()
        print("Next steps:")
        print("1. Implement ABBYY parser (tests/validation/abbyy_parser.py)")
        print("2. Create comparison helpers (tests/validation/comparison.py)")
        print("3. Write e2e validation tests (tests/test_ia_e2e_validation.py)")
        return True
    else:
        print(f"⚠️  Downloaded {success_count}/{len(files)} files")
        print("Some files failed to download. Please check network and try again.")
        return False


if __name__ == "__main__":
    success = download_ia_data()
    sys.exit(0 if success else 1)
