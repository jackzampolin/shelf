import csv
import io


def parse_tesseract_hierarchy(tsv_string):
    reader = csv.DictReader(io.StringIO(tsv_string), delimiter='\t', quoting=csv.QUOTE_NONE)
    blocks = {}
    all_confidences = []
    for row in reader:
        try:
            level = int(row['level'])
            if level != 5:
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

            if block_num not in blocks:
                blocks[block_num] = {}
            if par_num not in blocks[block_num]:
                blocks[block_num][par_num] = {}
            if line_num not in blocks[block_num][par_num]:
                blocks[block_num][par_num][line_num] = []

            blocks[block_num][par_num][line_num].append({
                'text': text,
                'bbox': [left, top, width, height],
                'confidence': round(conf / 100, 3)
            })

            all_confidences.append(conf)

        except (ValueError, KeyError):
            continue

    blocks_list = []
    for block_num in sorted(blocks.keys()):
        paragraphs_list = []

        for par_num in sorted(blocks[block_num].keys()):
            lines_dict = blocks[block_num][par_num]
            lines_list = []

            for line_num in sorted(lines_dict.keys()):
                words = lines_dict[line_num]

                if not words:
                    continue

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

                line_text = ' '.join(w['text'] for w in words)

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

            para_text = ' '.join(line['text'] for line in lines_list)

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

    if all_confidences:
        mean_conf = sum(all_confidences) / len(all_confidences)
        confidence_stats = {
            'mean_confidence': round(mean_conf / 100, 3)
        }
    else:
        confidence_stats = {
            'mean_confidence': 0.0
        }

    return blocks_list, confidence_stats


def parse_hocr_typography(hocr_bytes):
    from bs4 import BeautifulSoup
    import re

    try:
        hocr_string = hocr_bytes.decode('utf-8') if isinstance(hocr_bytes, bytes) else hocr_bytes
        soup = BeautifulSoup(hocr_string, 'html.parser')
    except Exception as e:
        return {}

    typography = {}

    for line_elem in soup.find_all('span', class_='ocr_line'):
        title = line_elem.get('title', '')

        props = {}
        for prop in title.split('; '):
            if ' ' in prop:
                key_val = prop.split(maxsplit=1)
                if len(key_val) == 2:
                    props[key_val[0]] = key_val[1]

        baseline_str = props.get('baseline', '0 0')
        baseline_parts = baseline_str.split()
        baseline = (float(baseline_parts[0]), float(baseline_parts[1])) if len(baseline_parts) == 2 else (0.0, 0.0)

        x_size = float(props.get('x_size', 0))
        x_ascenders = float(props.get('x_ascenders', 0))
        x_descenders = float(props.get('x_descenders', 0))

        bbox_str = props.get('bbox', '')
        bbox_match = re.match(r'(\d+) (\d+) (\d+) (\d+)', bbox_str)
        if bbox_match:
            x1, y1, x2, y2 = map(int, bbox_match.groups())
            bbox = (x1, y1, x2, y2)

            typography[bbox] = {
                'baseline': baseline,
                'x_size': x_size,
                'x_ascenders': x_ascenders,
                'x_descenders': x_descenders
            }

    return typography


def merge_typography_into_blocks(blocks_data, typography_data):
    if not typography_data:
        return blocks_data

    for block in blocks_data:
        for para in block['paragraphs']:
            for line in para.get('lines', []):
                line_bbox = line['bbox']
                line_bbox_tuple = (line_bbox[0], line_bbox[1],
                                   line_bbox[0] + line_bbox[2],
                                   line_bbox[1] + line_bbox[3])

                typography = None
                for hocr_bbox, typo_data in typography_data.items():
                    if (abs(hocr_bbox[0] - line_bbox_tuple[0]) < 5 and
                        abs(hocr_bbox[1] - line_bbox_tuple[1]) < 5 and
                        abs(hocr_bbox[2] - line_bbox_tuple[2]) < 5 and
                        abs(hocr_bbox[3] - line_bbox_tuple[3]) < 5):
                        typography = typo_data
                        break

                if typography:
                    line['baseline'] = typography['baseline']
                    line['x_size'] = typography['x_size']
                    line['x_ascenders'] = typography['x_ascenders']
                    line['x_descenders'] = typography['x_descenders']

    return blocks_data
