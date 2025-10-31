from typing import Dict, Any

def downsample_ocr_for_vision(ocr_output: Dict[str, Any], text_preview_chars: int = 100) -> Dict[str, Any]:
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
    blocks = ocr_output.get('blocks', [])
    
    num_blocks = len(blocks)
    num_paragraphs = sum(len(block.get('paragraphs', [])) for block in blocks)
    
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
