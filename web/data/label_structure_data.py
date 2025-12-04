from typing import Optional, List, Dict, Any
from infra.pipeline.storage.book_storage import BookStorage
from pipeline.label_structure.merge.processor import get_merged_page
from pipeline.label_structure.gap_analysis.processor import parse_page_number


def _calculate_sequence(rows: List[Dict]) -> List[Dict]:
    prev_type = None
    prev_value = None

    for row in rows:
        page_num_str = row.get("page_num_value", "")
        num_type, num_value = parse_page_number(page_num_str)

        row["sequence_status"] = "unknown"
        row["sequence_gap"] = 0
        row["expected_value"] = ""
        row["needs_review"] = False

        if num_type == "none":
            row["sequence_status"] = "no_number"
        elif num_value is None:
            row["sequence_status"] = "unparseable"
            row["needs_review"] = True
        elif prev_value is None:
            row["sequence_status"] = "first_page"
            prev_type = num_type
            prev_value = num_value
        elif num_type != prev_type:
            row["sequence_status"] = "type_change"
            row["expected_value"] = str(prev_value + 1)
            prev_type = num_type
            prev_value = num_value
        else:
            gap = num_value - prev_value
            row["sequence_gap"] = gap
            row["expected_value"] = str(prev_value + 1)

            if gap < 0:
                row["sequence_status"] = "backward_jump"
                row["needs_review"] = True
            elif gap == 1:
                row["sequence_status"] = "ok"
            else:
                row["sequence_status"] = f"gap_{gap - 1}"
                if gap > 3:
                    row["needs_review"] = True

            prev_type = num_type
            prev_value = num_value

    return rows


def get_label_structure_report(storage: BookStorage) -> Optional[List[Dict[str, Any]]]:
    stage_storage = storage.stage("label-structure")

    if not stage_storage.output_dir.exists():
        return None

    mechanical_dir = stage_storage.output_dir / "mechanical"
    if not mechanical_dir.exists() or not list(mechanical_dir.glob("page_*.json")):
        return None

    source_pages = storage.stage("source").list_pages(extension="png")

    rows = []
    for page_num in source_pages:
        try:
            page_output = get_merged_page(storage, page_num)
            data = page_output.model_dump()

            row = {
                "page_num": page_num,
                "headings_present": data.get("headings_present", False),
                "headings_count": len(data.get("headings", [])),
                "headings_text": data["headings"][0]["text"] if data.get("headings") else "",
                "header_present": data.get("running_header", {}).get("present", False),
                "header_text": data.get("running_header", {}).get("text", ""),
                "page_num_present": data.get("page_number", {}).get("present", False),
                "page_num_value": data.get("page_number", {}).get("number", ""),
                "page_num_location": data.get("page_number", {}).get("location", ""),
            }
            rows.append(row)
        except Exception:
            rows.append({
                "page_num": page_num,
                "headings_present": False,
                "headings_count": 0,
                "headings_text": "",
                "header_present": False,
                "header_text": "",
                "page_num_present": False,
                "page_num_value": "",
                "page_num_location": "",
            })

    return _calculate_sequence(rows)


def get_page_labels(storage: BookStorage, page_num: int) -> Optional[Dict[str, Any]]:
    try:
        page_output = get_merged_page(storage, page_num)
        return page_output.model_dump()
    except Exception:
        return None
