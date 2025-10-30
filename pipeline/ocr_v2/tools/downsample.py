"""
OCR output downsampling utilities.

Provides functions to reduce OCR output to structure-preserving summaries
for efficient LLM processing (vision prompts, analysis, etc.).
"""

from typing import Dict, Any


def downsample_ocr_for_vision(ocr_output: Dict[str, Any], text_preview_chars: int = 100) -> Dict[str, Any]:
    """
    Downsample OCR output to structure-preserving summary for vision LLM.

    Strips out most text content while preserving:
    - Block/paragraph structure
    - Bounding boxes
    - Confidence scores
    - Word counts
    - Short text previews

    This reduces prompt size by ~50-100x while maintaining enough context
    for the LLM to evaluate OCR quality and layout structure.

    Args:
        ocr_output: Full OCR output dict (OCRPageOutput format)
        text_preview_chars: Number of characters to keep per paragraph (default: 100)

    Returns:
        Downsampled dict with structure preserved, text minimized

    Example:
        >>> full_ocr = {"blocks": [...]}  # 50KB of text
        >>> summary = downsample_ocr_for_vision(full_ocr, text_preview_chars=100)
        >>> # summary is ~1KB with same structure
    """
    return {
        "blocks": [
            {
                "block_num": block.get('block_num'),
                "bbox": block.get('bbox'),
                "confidence": block.get('confidence'),
                "paragraphs": [
                    {
                        "par_num": para.get('par_num'),
                        "bbox": para.get('bbox'),
                        "confidence": para.get('confidence'),
                        "word_count": len(para.get('text', '').split()),
                        "text_preview": para.get('text', '')[:text_preview_chars],
                    }
                    for para in block.get('paragraphs', [])
                ]
            }
            for block in ocr_output.get('blocks', [])
        ]
    }


def calculate_ocr_summary_stats(ocr_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate summary statistics for OCR output.

    Useful for quick comparisons and prompt context.

    Args:
        ocr_output: Full OCR output dict (OCRPageOutput format)

    Returns:
        Dict with:
        - num_blocks: int
        - num_paragraphs: int
        - mean_confidence: float
        - total_words: int

    Example:
        >>> stats = calculate_ocr_summary_stats(ocr_output)
        >>> print(f"Blocks: {stats['num_blocks']}, Mean confidence: {stats['mean_confidence']:.3f}")
    """
    blocks = ocr_output.get('blocks', [])
    
    num_blocks = len(blocks)
    num_paragraphs = sum(len(block.get('paragraphs', [])) for block in blocks)
    
    # Calculate mean confidence across all paragraphs
    all_confidences = []
    total_words = 0
    
    for block in blocks:
        for para in block.get('paragraphs', []):
            conf = para.get('confidence', 0.0)
            if conf > 0:
                all_confidences.append(conf)
            
            text = para.get('text', '')
            if text:
                total_words += len(text.split())
    
    mean_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
    
    return {
        "num_blocks": num_blocks,
        "num_paragraphs": num_paragraphs,
        "mean_confidence": mean_confidence,
        "total_words": total_words,
    }
