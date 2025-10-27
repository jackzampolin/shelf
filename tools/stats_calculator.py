"""
Statistics calculation functions for different pipeline stages.

Each stage has its own stats calculator that processes the report.csv data
and returns stage-specific analytics for visualization.
"""

from typing import List, Dict, Any


def calculate_ocr_stats(rows: List[Dict], total_pages: int) -> Dict[str, Any]:
    """Calculate detailed OCR-specific statistics."""
    confidences = []
    blocks = []
    low_quality_pages = []

    for row in rows:
        page_num = int(row['page_num'])

        # Confidence
        if 'confidence_mean' in row and row['confidence_mean']:
            try:
                conf = float(row['confidence_mean'])
                confidences.append(conf)

                # Flag low quality pages (< 0.8)
                if conf < 0.8:
                    low_quality_pages.append((page_num, conf))
            except ValueError:
                pass

        # Blocks
        if 'blocks_detected' in row and row['blocks_detected']:
            try:
                blocks.append(int(row['blocks_detected']))
            except ValueError:
                pass

    # Sort low quality pages by confidence (worst first)
    low_quality_pages.sort(key=lambda x: x[1])

    # Calculate confidence histogram bins
    histogram = {
        "0.0-0.5": 0,  # Unreadable
        "0.5-0.7": 0,  # Marginal
        "0.7-0.8": 0,  # Acceptable
        "0.8-0.9": 0,  # Good
        "0.9-1.0": 0,  # Excellent
    }

    for conf in confidences:
        if conf < 0.5:
            histogram["0.0-0.5"] += 1
        elif conf < 0.7:
            histogram["0.5-0.7"] += 1
        elif conf < 0.8:
            histogram["0.7-0.8"] += 1
        elif conf < 0.9:
            histogram["0.8-0.9"] += 1
        else:
            histogram["0.9-1.0"] += 1

    return {
        "total_pages": total_pages,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
        "min_confidence": min(confidences) if confidences else None,
        "max_confidence": max(confidences) if confidences else None,
        "avg_blocks": sum(blocks) / len(blocks) if blocks else None,
        "min_blocks": min(blocks) if blocks else None,
        "max_blocks": max(blocks) if blocks else None,
        "low_quality_count": len(low_quality_pages),
        "low_quality_pages": low_quality_pages[:20],  # Top 20 worst
        "confidence_histogram": histogram,
    }


def calculate_corrected_stats(rows: List[Dict], total_pages: int) -> Dict[str, Any]:
    """Calculate detailed correction-specific statistics.

    Key metrics:
    - text_similarity_ratio: Most important (0.95-1.0 green, 0.85-0.95 yellow, <0.85 red)
    - avg_confidence: Model confidence in corrections
    - total_corrections: Number of paragraphs corrected
    - characters_changed: Edit distance
    """
    similarities = []
    confidences = []
    corrections = []
    chars_changed = []
    problem_pages = []

    for row in rows:
        page_num = int(row['page_num'])

        # Text similarity (most important metric)
        if 'text_similarity_ratio' in row and row['text_similarity_ratio']:
            try:
                sim = float(row['text_similarity_ratio'])
                similarities.append(sim)

                # Flag problem pages (< 0.90 similarity or low confidence)
                conf = float(row.get('avg_confidence', 0))
                if sim < 0.90 or conf < 0.85:
                    problem_pages.append({
                        'page_num': page_num,
                        'similarity': sim,
                        'confidence': conf,
                        'corrections': int(row.get('total_corrections', 0))
                    })
            except (ValueError, TypeError):
                pass

        # Confidence
        if 'avg_confidence' in row and row['avg_confidence']:
            try:
                confidences.append(float(row['avg_confidence']))
            except ValueError:
                pass

        # Correction count
        if 'total_corrections' in row and row['total_corrections']:
            try:
                corrections.append(int(row['total_corrections']))
            except ValueError:
                pass

        # Characters changed
        if 'characters_changed' in row and row['characters_changed']:
            try:
                chars_changed.append(int(row['characters_changed']))
            except ValueError:
                pass

    # Sort problem pages by similarity (worst first)
    problem_pages.sort(key=lambda x: x['similarity'])

    # Calculate similarity histogram bins
    similarity_histogram = {
        "0.00-0.85": 0,  # Red flag (over-correction)
        "0.85-0.90": 0,  # Concerning
        "0.90-0.95": 0,  # Normal corrections
        "0.95-0.98": 0,  # Minor fixes
        "0.98-1.00": 0,  # Very minor fixes
    }

    for sim in similarities:
        if sim < 0.85:
            similarity_histogram["0.00-0.85"] += 1
        elif sim < 0.90:
            similarity_histogram["0.85-0.90"] += 1
        elif sim < 0.95:
            similarity_histogram["0.90-0.95"] += 1
        elif sim < 0.98:
            similarity_histogram["0.95-0.98"] += 1
        else:
            similarity_histogram["0.98-1.00"] += 1

    # Calculate confidence histogram bins
    confidence_histogram = {
        "0.0-0.5": 0,
        "0.5-0.7": 0,
        "0.7-0.85": 0,
        "0.85-0.95": 0,
        "0.95-1.0": 0,
    }

    for conf in confidences:
        if conf < 0.5:
            confidence_histogram["0.0-0.5"] += 1
        elif conf < 0.7:
            confidence_histogram["0.5-0.7"] += 1
        elif conf < 0.85:
            confidence_histogram["0.7-0.85"] += 1
        elif conf < 0.95:
            confidence_histogram["0.85-0.95"] += 1
        else:
            confidence_histogram["0.95-1.0"] += 1

    return {
        "total_pages": total_pages,
        "avg_similarity": sum(similarities) / len(similarities) if similarities else None,
        "min_similarity": min(similarities) if similarities else None,
        "max_similarity": max(similarities) if similarities else None,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
        "min_confidence": min(confidences) if confidences else None,
        "max_confidence": max(confidences) if confidences else None,
        "total_corrections": sum(corrections) if corrections else 0,
        "avg_corrections": sum(corrections) / len(corrections) if corrections else None,
        "avg_chars_changed": sum(chars_changed) / len(chars_changed) if chars_changed else None,
        "problem_pages": problem_pages[:20],  # Top 20 worst
        "similarity_histogram": similarity_histogram,
        "confidence_histogram": confidence_histogram,
    }


def calculate_labels_stats(rows: List[Dict], total_pages: int) -> Dict[str, Any]:
    """Calculate detailed label-specific statistics.

    Key metrics:
    - avg_classification_confidence: Block classification quality
    - page_number_extracted: Printed page numbers found
    - page_region_classified: Regions identified
    - has_chapter_heading: Chapter boundary markers
    """
    confidences = []
    page_numbers_extracted = 0
    regions_classified = 0
    chapter_headings = []
    problem_pages = []
    region_breakdown = {"front_matter": 0, "body": 0, "back_matter": 0, "toc_area": 0, "unknown": 0}

    for row in rows:
        page_num = int(row['page_num'])

        # Confidence
        if 'avg_classification_confidence' in row and row['avg_classification_confidence']:
            try:
                conf = float(row['avg_classification_confidence'])
                confidences.append(conf)

                # Flag problem pages (< 0.80 confidence or missing classification)
                if conf < 0.80:
                    problem_pages.append({
                        'page_num': page_num,
                        'confidence': conf,
                        'region': row.get('page_region', 'unknown'),
                        'blocks': int(row.get('total_blocks_classified', 0))
                    })
            except (ValueError, TypeError):
                pass

        # Page number extraction
        if row.get('page_number_extracted', '').lower() == 'true':
            page_numbers_extracted += 1

        # Region classification
        region = row.get('page_region', 'unknown')
        if region and region != 'null':
            regions_classified += 1
            region_breakdown[region] = region_breakdown.get(region, 0) + 1
        else:
            region_breakdown['unknown'] += 1

        # Chapter headings
        if row.get('has_chapter_heading', '').lower() == 'true':
            chapter_headings.append({
                'page_num': page_num,
                'printed_page': row.get('printed_page_number', '-'),
                'text': row.get('chapter_heading_text', '(No text)')
            })

    # Sort problem pages by confidence (worst first)
    problem_pages.sort(key=lambda x: x['confidence'])

    # Calculate confidence histogram bins
    confidence_histogram = {
        "0.00-0.80": 0,  # Red flag
        "0.80-0.85": 0,  # Concerning
        "0.85-0.90": 0,  # Acceptable
        "0.90-0.95": 0,  # Good
        "0.95-1.00": 0,  # Excellent
    }

    for conf in confidences:
        if conf < 0.80:
            confidence_histogram["0.00-0.80"] += 1
        elif conf < 0.85:
            confidence_histogram["0.80-0.85"] += 1
        elif conf < 0.90:
            confidence_histogram["0.85-0.90"] += 1
        elif conf < 0.95:
            confidence_histogram["0.90-0.95"] += 1
        else:
            confidence_histogram["0.95-1.00"] += 1

    return {
        "total_pages": total_pages,
        "avg_confidence": sum(confidences) / len(confidences) if confidences else None,
        "min_confidence": min(confidences) if confidences else None,
        "max_confidence": max(confidences) if confidences else None,
        "page_numbers_extracted": page_numbers_extracted,
        "page_numbers_percentage": (page_numbers_extracted / total_pages * 100) if total_pages > 0 else 0,
        "regions_classified": regions_classified,
        "regions_percentage": (regions_classified / total_pages * 100) if total_pages > 0 else 0,
        "chapter_headings_count": len(chapter_headings),
        "chapter_headings": chapter_headings[:20],  # Top 20
        "region_breakdown": region_breakdown,
        "problem_pages": problem_pages[:20],  # Top 20 worst
        "confidence_histogram": confidence_histogram,
    }
