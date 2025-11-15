from infra.pipeline.status import PhaseStatusTracker
from ..schemas.merged_output import LabelStructurePageOutput
from ..schemas.mechanical import MechanicalExtractionOutput
from ..schemas.structure import StructuralMetadataOutput
from ..schemas.annotations import AnnotationsOutput


def merge_outputs(
    tracker: PhaseStatusTracker,
    **kwargs
) -> None:
    """Merge mechanical, structure, and annotations outputs into final page files.

    Args:
        tracker: PhaseStatusTracker providing access to storage, logger, status
        **kwargs: Optional configuration (unused for this phase)
    """
    tracker.logger.info(f"=== Merge: Combining outputs ===")

    remaining_pages = tracker.get_remaining_items()
    if not remaining_pages:
        tracker.logger.info("No pages to merge (all completed)")
        return

    tracker.logger.info(f"Merging {len(remaining_pages)} pages")

    stage_storage = tracker.storage.stage("label-structure")
    merged_count = 0

    for page_num in remaining_pages:
        page_filename = f"page_{page_num:04d}.json"

        try:
            mechanical_data = stage_storage.load_file(f"mechanical/{page_filename}")
            mechanical = MechanicalExtractionOutput(**mechanical_data)

            structure_data = stage_storage.load_file(f"structure/{page_filename}")
            structure = StructuralMetadataOutput(**structure_data)

            annotations_data = stage_storage.load_file(f"annotations/{page_filename}")
            annotations = AnnotationsOutput(**annotations_data)

            merged = LabelStructurePageOutput(
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

            stage_storage.save_file(
                page_filename,
                merged.model_dump(),
                schema=LabelStructurePageOutput
            )

            merged_count += 1
            tracker.logger.debug(f"✓ Merged page_{page_num:04d}")

        except FileNotFoundError as e:
            tracker.logger.error(
                f"✗ Missing input for page_{page_num:04d}: {e}",
                page_num=page_num,
                error=str(e)
            )
        except Exception as e:
            tracker.logger.error(
                f"✗ Failed to merge page_{page_num:04d}: {e}",
                page_num=page_num,
                error=str(e)
            )

    tracker.logger.info(f"Merge complete: {merged_count}/{len(remaining_pages)} pages merged")
