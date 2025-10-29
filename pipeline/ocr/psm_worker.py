"""
PSM worker function for parallel OCR processing.

Standalone worker that runs Tesseract OCR with a specific PSM mode
in a separate process via ProcessPoolExecutor.
"""

import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Tuple
from PIL import Image
import pytesseract

from infra.storage.book_storage import BookStorage
from pipeline.ocr.schemas import OCRPageOutput
from pipeline.ocr.parsers import (
    parse_tesseract_hierarchy,
    parse_hocr_typography,
    merge_typography_into_blocks
)
from pipeline.ocr.image_detection import validate_image_candidates, ImageDetector


def process_page_psm_worker(task: Dict[str, Any]) -> Tuple[bool, int, str, Dict[str, Any], Dict[str, Any]]:
    """
    Standalone worker function for parallel OCR processing with specific PSM mode.

    Runs in separate process via ProcessPoolExecutor.

    Args:
        task: Dict with storage_root, scan_id, page_number, psm_mode

    Returns:
        (success, page_number, error_msg, page_data, metrics)
    """
    try:
        start_time = time.time()

        # Reconstruct storage in worker process
        storage = BookStorage(
            scan_id=task['scan_id'],
            storage_root=Path(task['storage_root'])
        )

        page_number = task['page_number']
        psm_mode = task['psm_mode']

        # Load image from source
        page_file = storage.stage('source').output_page(page_number, extension='png')
        pil_image = Image.open(page_file)

        # Create PSM-specific images directory for this page
        ocr_dir = storage.book_dir / "ocr"
        psm_images_dir = ocr_dir / f"psm{psm_mode}" / f"page_{page_number:04d}_images"
        psm_images_dir.mkdir(parents=True, exist_ok=True)

        # Extract dimensions
        width, height = pil_image.size

        # Run Tesseract OCR with specified PSM mode
        # 1. Extract TSV for hierarchical structure
        tsv_output = pytesseract.image_to_data(
            pil_image,
            lang='eng',
            config=f'--psm {psm_mode}',
            output_type=pytesseract.Output.STRING
        )

        # 2. Extract hOCR for typography metadata
        hocr_output = pytesseract.image_to_pdf_or_hocr(
            pil_image,
            lang='eng',
            config=f'--psm {psm_mode}',
            extension='hocr'
        )

        # Parse TSV into hierarchical blocks (returns blocks_data and confidence stats)
        blocks_data, confidence_stats = parse_tesseract_hierarchy(tsv_output)

        # Parse hOCR for typography metadata
        typography_data = parse_hocr_typography(hocr_output)

        # Merge typography into blocks
        blocks_data = merge_typography_into_blocks(blocks_data, typography_data)

        # Detect image regions
        text_boxes = []
        for block in blocks_data:
            for para in block['paragraphs']:
                text_boxes.append(para['bbox'])

        image_candidates = ImageDetector.detect_images(pil_image, text_boxes)

        # Validate image candidates (filter out decorative text)
        confirmed_images, recovered_text_blocks = validate_image_candidates(
            pil_image,
            image_candidates,
            psm_mode
        )

        # Create image regions from confirmed images
        images = []
        for img_id, img_box in enumerate(confirmed_images, 1):
            x, y, w, h = img_box
            cropped = pil_image.crop((x, y, x + w, y + h))

            # Save to PSM-specific page images directory
            img_filename = f"img_{img_id:03d}.png"
            img_path = psm_images_dir / img_filename
            cropped.save(img_path)

            # Store relative path from book root
            relative_path = img_path.relative_to(storage.book_dir)

            images.append({
                'image_id': img_id,
                'bbox': list(img_box),
                'image_file': str(relative_path),
                'ocr_attempted': True,
                'ocr_text_recovered': None
            })

        # Add recovered text blocks back to blocks_data
        if recovered_text_blocks:
            for recovered_block in recovered_text_blocks:
                # Create a new block for recovered text
                new_block_num = max((b['block_num'] for b in blocks_data), default=0) + 1
                blocks_data.append({
                    'block_num': new_block_num,
                    'bbox': recovered_block['bbox'],
                    'paragraphs': [{
                        'par_num': 0,
                        'text': recovered_block['text'],
                        'bbox': recovered_block['bbox'],
                        'avg_confidence': recovered_block['confidence'],
                        'source': 'recovered_from_image',
                        'lines': []  # No line detail for recovered text
                    }]
                })

        # Build page data
        page_data = {
            'page_number': page_number,
            'page_dimensions': {'width': width, 'height': height},
            'ocr_timestamp': datetime.now().isoformat(),
            'blocks': blocks_data,
            'images': images
        }

        # Validate against schema
        validated_page = OCRPageOutput(**page_data)
        page_data = validated_page.model_dump()

        # Build metrics
        processing_time = time.time() - start_time
        tesseract_version = pytesseract.get_tesseract_version()

        metrics = {
            'page_num': page_number,
            'processing_time_seconds': processing_time,
            'cost_usd': 0.0,  # No cost for Tesseract
            'psm_mode': psm_mode,
            'tesseract_version': str(tesseract_version),
            'confidence_mean': confidence_stats['mean_confidence'],
            'blocks_detected': len(blocks_data),
            'recovered_text_blocks_count': len(recovered_text_blocks)
        }

        return (True, page_number, None, page_data, metrics)

    except Exception as e:
        return (False, task['page_number'], str(e), None, None)
