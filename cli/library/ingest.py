import re
import json
import shutil
import multiprocessing
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Tuple
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from pdf2image import convert_from_path
from pdf2image.pdf2image import pdfinfo_from_path
from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn, TimeRemainingColumn

from infra.config import Config


def _extract_single_page(task: Tuple[Path, int, Path, int]) -> Tuple[bool, str]:
    pdf_path, local_page, output_path, dpi = task

    try:
        page_images = convert_from_path(
            pdf_path,
            first_page=local_page,
            last_page=local_page,
            dpi=dpi
        )

        if page_images:
            page_images[0].save(output_path, format='PNG')
            return (True, None)
        else:
            return (False, f"No image returned for page {local_page}")

    except Exception as e:
        return (False, str(e))


def group_batch_pdfs(pdf_paths: List[Path]) -> Dict[str, List[Path]]:
    groups = defaultdict(list)

    for pdf_path in pdf_paths:
        name = pdf_path.stem
        base_name = re.sub(r'[-_](part|batch|section|volume)?[-_]?\d+$', '', name, flags=re.IGNORECASE)
        groups[base_name].append(pdf_path)

    for base_name in groups:
        groups[base_name] = sorted(groups[base_name])

    return dict(groups)


def ingest_book_group(
    base_name: str,
    pdf_paths: List[Path],
    storage_root: Path,
) -> str:
    scan_id = base_name
    title = base_name.replace('-', ' ').replace('_', ' ').title()
    author = 'Unknown'
    isbn = None

    print(f"\n📚 Book Ingestion ({scan_id})")
    print(f"   Title:     {title}")
    print(f"   Author:    {author}")
    print(f"   PDFs:      {len(pdf_paths)}")

    scan_dir = storage_root / scan_id
    if scan_dir.exists():
        print(f"   ❌ Scan ID '{scan_id}' already exists (directory found)")
        return None

    scan_dir.mkdir(exist_ok=True)

    source_dir = scan_dir / "source"
    source_dir.mkdir(exist_ok=True)

    tasks = []
    global_page_num = 1

    for pdf_idx, pdf_path in enumerate(pdf_paths, 1):
        dest_pdf = source_dir / f"{base_name}-{pdf_idx}.pdf"
        shutil.copy2(pdf_path, dest_pdf)

        info = pdfinfo_from_path(pdf_path)
        page_count = info['Pages']

        for local_page in range(1, page_count + 1):
            output_path = source_dir / f"page_{global_page_num:04d}.png"
            tasks.append((pdf_path, local_page, output_path, 600))
            global_page_num += 1

    total_pages = len(tasks)
    max_workers = multiprocessing.cpu_count()

    print(f"\n   Extracting {total_pages} pages at 600 DPI...")

    completed = 0
    failed = 0

    progress = Progress(
        TextColumn("   {task.description}"),
        BarColumn(bar_width=40),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        TextColumn("•"),
        TextColumn("{task.fields[suffix]}", justify="right"),
        transient=True
    )

    with progress, ProcessPoolExecutor(max_workers=max_workers) as executor:
        task_id = progress.add_task("", total=total_pages, suffix="")
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
                    print(f"\n   ⚠️  Failed {output_path.name}: {error_msg}")
            except Exception as e:
                failed += 1
                print(f"\n   ⚠️  Exception for {output_path.name}: {e}")

            current = completed + failed
            suffix = f"{completed} ok" + (f", {failed} failed" if failed > 0 else "")
            progress.update(task_id, completed=current, suffix=suffix)

    print(f"   ✓ Extracted {completed}/{total_pages} pages")
    if failed > 0:
        print(f"   ⚠️  {failed} pages failed")

    metadata = {
        "title": title,
        "author": author,
        "isbn": isbn,
        "scan_date": datetime.now().isoformat(),
        "source_files": [f"{base_name}-{i}.pdf" for i in range(1, len(pdf_paths) + 1)],
        "total_pages": completed,
        "status": "registered",
        "extraction_dpi": 600,
        "extraction_workers": max_workers
    }

    metadata_file = scan_dir / "metadata.json"
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n✅ Book added: {scan_id}")

    return scan_id


def add_books_to_library(pdf_paths: List[Path], storage_root: Path = None, run_ocr: bool = False) -> Dict[str, Any]:
    storage_root = storage_root or Config.book_storage_root

    groups = group_batch_pdfs(pdf_paths)

    print(f"\nDetected {len(groups)} book(s):")
    for base_name, pdfs in groups.items():
        print(f"  • {base_name}: {len(pdfs)} PDF(s)")

    scan_ids = []
    for base_name, pdfs in groups.items():
        scan_id = ingest_book_group(base_name, pdfs, storage_root)
        if scan_id:
            scan_ids.append(scan_id)

    if run_ocr and scan_ids:
        import importlib
        ocr_module = importlib.import_module('pipeline.1_ocr')
        BookOCRProcessor = getattr(ocr_module, 'BookOCRProcessor')

        processor = BookOCRProcessor(
            storage_root=str(storage_root or Config.book_storage_root),
            max_workers=None
        )

        for scan_id in scan_ids:
            processor.process_book(scan_id, resume=False)

    return {
        'books_added': len(scan_ids),
        'scan_ids': scan_ids
    }
