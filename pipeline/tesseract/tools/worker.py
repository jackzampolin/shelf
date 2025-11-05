import time
from pathlib import Path
from typing import Dict, Any
from PIL import Image
import pytesseract
import io
from collections import defaultdict


def process_page_with_tesseract(
    image_path: Path,
    page_num: int,
    psm_mode: int = 3
) -> Dict[str, Any]:
    """
    Process a single page with Tesseract OCR.

    Returns paragraph-level output only (no complex hierarchy).
    Uses PSM mode 3 by default (automatic page segmentation).
    """
    start_time = time.time()

    pil_image = Image.open(image_path)

    tsv_output = pytesseract.image_to_data(
        pil_image,
        lang="eng",
        config=f"--psm {psm_mode}",
        output_type=pytesseract.Output.STRING,
    )

    paragraphs = _extract_paragraphs_from_tsv(tsv_output)

    avg_confidence = _calculate_average_confidence(paragraphs)

    processing_time = time.time() - start_time

    return {
        "page_num": page_num,
        "paragraphs": paragraphs,
        "avg_confidence": avg_confidence,
        "processing_time_seconds": processing_time,
    }


def _extract_paragraphs_from_tsv(tsv_output: str) -> list:
    """Extract paragraph-level text from Tesseract TSV output."""
    lines = tsv_output.strip().split('\n')

    if len(lines) < 2:
        return []

    header = lines[0].split('\t')

    try:
        par_num_idx = header.index('par_num')
        text_idx = header.index('text')
        conf_idx = header.index('conf')
    except ValueError as e:
        raise ValueError(f"Missing required column in TSV header: {e}")

    paragraph_data = defaultdict(lambda: {"words": [], "confidences": []})

    for line in lines[1:]:
        fields = line.split('\t')

        if len(fields) <= max(par_num_idx, text_idx, conf_idx):
            continue

        try:
            par_num = int(fields[par_num_idx])
            text = fields[text_idx]
            conf = float(fields[conf_idx])
        except (ValueError, IndexError):
            continue

        if text.strip() and conf >= 0:
            paragraph_data[par_num]["words"].append(text)
            paragraph_data[par_num]["confidences"].append(conf)

    paragraphs = []
    for par_num in sorted(paragraph_data.keys()):
        data = paragraph_data[par_num]

        if not data["words"]:
            continue

        full_text = " ".join(data["words"])
        avg_conf = sum(data["confidences"]) / len(data["confidences"])

        paragraphs.append({
            "par_num": par_num,
            "text": full_text,
            "confidence": avg_conf / 100.0,  # Tesseract confidence is 0-100
        })

    return paragraphs


def _calculate_average_confidence(paragraphs: list) -> float:
    """Calculate average confidence across all paragraphs."""
    if not paragraphs:
        return 0.0

    total_conf = sum(p["confidence"] for p in paragraphs)
    return total_conf / len(paragraphs)
