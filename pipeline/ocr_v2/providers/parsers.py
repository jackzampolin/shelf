"""
Tesseract and hOCR parsing utilities.

Functions for parsing Tesseract TSV output into hierarchical block structure
and extracting typography metadata from hOCR output.
"""

import csv
import io


def parse_tesseract_hierarchy(tsv_string):
    """
    Parse Tesseract TSV into hierarchical blocks->paragraphs->lines->words structure.

    Preserves line-level detail for downstream analysis.

    Args:
        tsv_string: TSV output from pytesseract

    Returns:
        (blocks_list, confidence_stats) where confidence_stats contains
        'mean_confidence' and other aggregate metrics
    """
    reader = csv.DictReader(io.StringIO(tsv_string), delimiter='\t', quoting=csv.QUOTE_NONE)
    blocks = {}
    all_confidences = []  # Track all word-level confidences for stats

    # Parse words into nested structure: block -> para -> line -> word
    for row in reader:
        try:
            level = int(row['level'])
            if level != 5:  # Word level
                continue

            block_num = int(row['block_num'])
            par_num = int(row['par_num'])
            line_num = int(row['line_num'])
            conf = float(row['conf'])
            text = row['text'].strip()

            if conf < 0 or not text:
                continue

            left = int(row['left'])
            top = int(row['top'])
            width = int(row['width'])
            height = int(row['height'])

            # Initialize nested structure
            if block_num not in blocks:
                blocks[block_num] = {}
            if par_num not in blocks[block_num]:
                blocks[block_num][par_num] = {}
            if line_num not in blocks[block_num][par_num]:
                blocks[block_num][par_num][line_num] = []

            # Add word to line
            blocks[block_num][par_num][line_num].append({
                'text': text,
                'bbox': [left, top, width, height],
                'confidence': round(conf / 100, 3)  # Normalize to 0-1
            })

            # Track for page-level stats
            all_confidences.append(conf)

        except (ValueError, KeyError):
            continue

    # Convert nested structure to list format with line preservation
    blocks_list = []
    for block_num in sorted(blocks.keys()):
        paragraphs_list = []

        for par_num in sorted(blocks[block_num].keys()):
            lines_dict = blocks[block_num][par_num]
            lines_list = []

            # Build lines from words
            for line_num in sorted(lines_dict.keys()):
                words = lines_dict[line_num]

                if not words:
                    continue

                # Calculate line bbox from words
                xs = [w['bbox'][0] for w in words]
                ys = [w['bbox'][1] for w in words]
                x2s = [w['bbox'][0] + w['bbox'][2] for w in words]
                y2s = [w['bbox'][1] + w['bbox'][3] for w in words]

                line_bbox = [
                    min(xs),
                    min(ys),
                    max(x2s) - min(xs),
                    max(y2s) - min(ys)
                ]

                # Join word text
                line_text = ' '.join(w['text'] for w in words)

                # Calculate line confidence
                line_conf = sum(w['confidence'] for w in words) / len(words)

                lines_list.append({
                    'line_num': line_num,
                    'text': line_text,
                    'bbox': line_bbox,
                    'words': words,
                    'avg_confidence': round(line_conf, 3)
                })

            if not lines_list:
                continue

            # Build paragraph from lines
            para_text = ' '.join(line['text'] for line in lines_list)

            # Calculate paragraph bbox from lines
            xs = [line['bbox'][0] for line in lines_list]
            ys = [line['bbox'][1] for line in lines_list]
            x2s = [line['bbox'][0] + line['bbox'][2] for line in lines_list]
            y2s = [line['bbox'][1] + line['bbox'][3] for line in lines_list]

            para_bbox = [
                min(xs),
                min(ys),
                max(x2s) - min(xs),
                max(y2s) - min(ys)
            ]

            # Calculate paragraph confidence
            para_conf = sum(line['avg_confidence'] for line in lines_list) / len(lines_list)

            paragraphs_list.append({
                'par_num': par_num,
                'text': para_text,
                'bbox': para_bbox,
                'lines': lines_list,
                'avg_confidence': round(para_conf, 3)
            })

        if not paragraphs_list:
            continue

        # Calculate block bounding box from paragraphs
        xs = [p['bbox'][0] for p in paragraphs_list]
        ys = [p['bbox'][1] for p in paragraphs_list]
        x2s = [p['bbox'][0] + p['bbox'][2] for p in paragraphs_list]
        y2s = [p['bbox'][1] + p['bbox'][3] for p in paragraphs_list]

        block_bbox = [
            min(xs),
            min(ys),
            max(x2s) - min(xs),
            max(y2s) - min(ys)
        ]

        blocks_list.append({
            'block_num': block_num,
            'bbox': block_bbox,
            'paragraphs': paragraphs_list
        })

    # Calculate confidence statistics
    if all_confidences:
        mean_conf = sum(all_confidences) / len(all_confidences)
        # Tesseract confidence is 0-100, normalize to 0-1
        confidence_stats = {
            'mean_confidence': round(mean_conf / 100, 3)
        }
    else:
        confidence_stats = {
            'mean_confidence': 0.0
        }

    return blocks_list, confidence_stats


def parse_hocr_typography(hocr_bytes):
    """
    Parse hOCR XML to extract typography metadata.

    Args:
        hocr_bytes: hOCR output from pytesseract (bytes)

    Returns:
        Dict mapping (block_num, par_num, line_num) -> typography dict
    """
    from bs4 import BeautifulSoup
    import re

    try:
        # Decode bytes to string
        hocr_string = hocr_bytes.decode('utf-8') if isinstance(hocr_bytes, bytes) else hocr_bytes
        soup = BeautifulSoup(hocr_string, 'html.parser')
    except Exception as e:
        # If hOCR parsing fails, return empty dict (typography is optional)
        return {}

    typography = {}

    # Parse all ocr_line elements
    for line_elem in soup.find_all('span', class_='ocr_line'):
        title = line_elem.get('title', '')

        # Parse title string: "bbox 120 456 890 489; baseline 0.002 -5; x_size 28; ..."
        props = {}
        for prop in title.split('; '):
            if ' ' in prop:
                key_val = prop.split(maxsplit=1)
                if len(key_val) == 2:
                    props[key_val[0]] = key_val[1]

        # Extract typography properties
        baseline_str = props.get('baseline', '0 0')
        baseline_parts = baseline_str.split()
        baseline = (float(baseline_parts[0]), float(baseline_parts[1])) if len(baseline_parts) == 2 else (0.0, 0.0)

        x_size = float(props.get('x_size', 0))
        x_ascenders = float(props.get('x_ascenders', 0))
        x_descenders = float(props.get('x_descenders', 0))

        # Extract bbox to correlate with TSV line
        bbox_str = props.get('bbox', '')
        bbox_match = re.match(r'(\d+) (\d+) (\d+) (\d+)', bbox_str)
        if bbox_match:
            x1, y1, x2, y2 = map(int, bbox_match.groups())
            bbox = (x1, y1, x2, y2)

            # Store by bbox (will match to TSV line later)
            typography[bbox] = {
                'baseline': baseline,
                'x_size': x_size,
                'x_ascenders': x_ascenders,
                'x_descenders': x_descenders
            }

    return typography


def merge_typography_into_blocks(blocks_data, typography_data):
    """
    Merge typography metadata from hOCR into TSV-based blocks.

    Matches lines by bbox coordinates and adds typography fields.

    Args:
        blocks_data: List of blocks from TSV parser
        typography_data: Dict of bbox -> typography from hOCR parser

    Returns:
        blocks_data with typography merged into lines
    """
    if not typography_data:
        return blocks_data  # No typography to merge

    for block in blocks_data:
        for para in block['paragraphs']:
            for line in para.get('lines', []):
                # Convert line bbox to tuple for matching
                line_bbox = line['bbox']
                line_bbox_tuple = (line_bbox[0], line_bbox[1],
                                   line_bbox[0] + line_bbox[2],
                                   line_bbox[1] + line_bbox[3])

                # Look for matching typography (allow small tolerance)
                typography = None
                for hocr_bbox, typo_data in typography_data.items():
                    # Check if bboxes are close (within 5 pixels)
                    if (abs(hocr_bbox[0] - line_bbox_tuple[0]) < 5 and
                        abs(hocr_bbox[1] - line_bbox_tuple[1]) < 5 and
                        abs(hocr_bbox[2] - line_bbox_tuple[2]) < 5 and
                        abs(hocr_bbox[3] - line_bbox_tuple[3]) < 5):
                        typography = typo_data
                        break

                # Merge typography if found
                if typography:
                    line['baseline'] = typography['baseline']
                    line['x_size'] = typography['x_size']
                    line['x_ascenders'] = typography['x_ascenders']
                    line['x_descenders'] = typography['x_descenders']

    return blocks_data
