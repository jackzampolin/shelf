from typing import Optional
from pathlib import Path
import json
from infra.pipeline.status import PhaseStatusTracker
from infra.pipeline.storage.book_storage import BookStorage
from ..schemas.merged_output import LabelStructurePageOutput
from ..schemas.mechanical import MechanicalExtractionOutput
from ..schemas.structure import StructuralMetadataOutput
from ..schemas.annotations import AnnotationsOutput


def _merge_three_sources(stage_storage, page_num: int) -> LabelStructurePageOutput:
    page_filename = f"page_{page_num:04d}.json"

    try:
        mechanical_data = stage_storage.load_file(f"mechanical/{page_filename}")
        mechanical = MechanicalExtractionOutput(**mechanical_data)
    except FileNotFoundError:
        raise FileNotFoundError(f"Missing mechanical output: mechanical/{page_filename}")
    except Exception as e:
        raise ValueError(f"Failed to load mechanical output for page {page_num}: {type(e).__name__}: {e}")

    try:
        structure_data = stage_storage.load_file(f"structure/{page_filename}")
        structure = StructuralMetadataOutput(**structure_data)
    except FileNotFoundError:
        raise FileNotFoundError(f"Missing structure output: structure/{page_filename}")
    except Exception as e:
        raise ValueError(f"Failed to load structure output for page {page_num}: {type(e).__name__}: {e}")

    try:
        annotations_data = stage_storage.load_file(f"annotations/{page_filename}")
        annotations = AnnotationsOutput(**annotations_data)
    except FileNotFoundError:
        raise FileNotFoundError(f"Missing annotations output: annotations/{page_filename}")
    except Exception as e:
        raise ValueError(f"Failed to load annotations output for page {page_num}: {type(e).__name__}: {e}")

    return LabelStructurePageOutput(
        headings_present=mechanical.headings_present,
        headings=mechanical.headings,
        pattern_hints=mechanical.pattern_hints,
        header=structure.header,
        footer=structure.footer,
        page_number=structure.page_number,
        markers_present=annotations.markers_present,
        markers=annotations.markers,
        footnotes_present=annotations.footnotes_present,
        footnotes=annotations.footnotes,
        cross_references_present=annotations.cross_references_present,
        cross_references=annotations.cross_references,
        has_horizontal_rule=annotations.has_horizontal_rule,
        has_small_text_at_bottom=annotations.has_small_text_at_bottom,
    )


def _apply_patch(base: LabelStructurePageOutput, patch_data: dict) -> LabelStructurePageOutput:
    base_dict = base.model_dump()

    patched_fields = []
    for key, value in patch_data.items():
        if key in ['agent_id', 'reasoning']:
            continue

        if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
            base_dict[key].update(value)
        else:
            base_dict[key] = value
        patched_fields.append(key)

    try:
        return LabelStructurePageOutput(**base_dict)
    except Exception as e:
        raise ValueError(
            f"Failed to apply patch (fields: {', '.join(patched_fields)}): "
            f"{type(e).__name__}: {e}"
        )


def _load_patch_if_exists(phase_dir: Path, page_num: int, logger=None, phase_name: str = "unknown") -> Optional[dict]:
    patch_file = phase_dir / f"page_{page_num:04d}.json"
    if not patch_file.exists():
        return None

    try:
        with open(patch_file, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        if logger:
            logger.error(
                f"Corrupted patch: {patch_file.name} ({phase_name})",
                page_num=page_num,
                phase=phase_name,
                error=str(e)
            )
        return None
    except Exception as e:
        if logger:
            logger.error(f"Failed to load patch: {patch_file.name}", error=str(e), error_type=type(e).__name__)
        raise


def get_base_merged_page(storage: BookStorage, scan_page: int) -> LabelStructurePageOutput:
    stage_storage = storage.stage("label-structure")
    return _merge_three_sources(stage_storage, scan_page)


def get_simple_fixes_merged_page(storage: BookStorage, scan_page: int) -> LabelStructurePageOutput:
    stage_storage = storage.stage("label-structure")
    merged = _merge_three_sources(stage_storage, scan_page)
    simple_patch = _load_patch_if_exists(stage_storage.output_dir / "simple_gap_healing", scan_page)
    if simple_patch:
        merged = _apply_patch(merged, simple_patch)
    return merged


def get_merged_page(storage: BookStorage, scan_page: int) -> LabelStructurePageOutput:
    stage_storage = storage.stage("label-structure")
    merged = _merge_three_sources(stage_storage, scan_page)
    simple_patch = _load_patch_if_exists(stage_storage.output_dir / "simple_gap_healing", scan_page)
    if simple_patch:
        merged = _apply_patch(merged, simple_patch)
    agent_patch = _load_patch_if_exists(stage_storage.output_dir / "agent_healing", scan_page)
    if agent_patch:
        merged = _apply_patch(merged, agent_patch)
    return merged


def merge_outputs(tracker: PhaseStatusTracker, **kwargs) -> None:
    tracker.logger.info(f"=== Merge: Combining outputs ===")
    remaining_pages = tracker.get_remaining_items()
    if not remaining_pages:
        tracker.logger.info("No pages to merge (all completed)")
        return

    tracker.logger.info(f"Merging {len(remaining_pages)} pages")
    stage_storage = tracker.storage.stage("label-structure")
    merged_count = 0
    failed_pages = []

    for page_num in remaining_pages:
        page_filename = f"page_{page_num:04d}.json"
        try:
            merged = get_merged_page(stage_storage, page_num)
            stage_storage.save_file(page_filename, merged.model_dump(), schema=LabelStructurePageOutput)
            merged_count += 1
            tracker.logger.debug(f"✓ Merged page_{page_num:04d}")
        except FileNotFoundError as e:
            tracker.logger.error(f"✗ Missing input for page_{page_num:04d}: {e}", page_num=page_num, error=str(e))
            failed_pages.append({"page": page_num, "error": str(e), "type": "missing"})
        except Exception as e:
            tracker.logger.error(f"✗ Failed to merge page_{page_num:04d}: {e}", page_num=page_num, error=str(e), error_type=type(e).__name__)
            failed_pages.append({"page": page_num, "error": str(e), "type": type(e).__name__})

    if failed_pages:
        error_file = tracker.phase_dir / "merge_errors.json"
        error_file.write_text(json.dumps(failed_pages, indent=2))
        raise ValueError(f"{len(failed_pages)} pages failed to merge - see {error_file}")

    tracker.logger.info(f"Merge complete: {merged_count}/{len(remaining_pages)} pages merged")
