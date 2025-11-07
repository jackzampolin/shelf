from typing import Dict, Any

from infra.config import Config
from infra.pipeline.base_stage import BaseStage
from infra.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker
from pipeline.find_toc import FindTocStage
from pipeline.ocr_pages import OcrPagesStage

from .schemas import ExtractTocBookOutput


class ExtractTocStage(BaseStage):

    name = "extract-toc"
    dependencies = ["source", "find-toc", "ocr-pages"]

    output_schema = ExtractTocBookOutput
    checkpoint_schema = None
    report_schema = None
    self_validating = True

    def __init__(self, storage: BookStorage, model: str = None):
        super().__init__(storage)
        self.model = model or Config.text_model_expensive

        # Two-phase tracking: extract entries + assemble toc
        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[
                {"name": "extract_entries", "artifact": "entries.json"},
                {"name": "assemble_toc", "artifact": "toc.json"}
            ]
        )

    def before(self) -> None:
        self.logger.info(f"Extract-ToC with {self.model}")
        self.check_source_exists()

        # Check find-toc dependency
        find_toc_stage = FindTocStage(self.storage)
        self.check_dependency_completed(find_toc_stage)

        # Load finder result to check if ToC was found
        find_toc_storage = self.storage.stage('find-toc')
        finder_result = find_toc_storage.load_file("finder_result.json")
        if not finder_result or not finder_result.get('toc_found'):
            raise RuntimeError(
                "Find-toc stage completed but no ToC was found. "
                "Cannot proceed with ToC extraction."
            )

        toc_range = finder_result.get('toc_page_range')
        self.logger.info(f"Find-toc found ToC: pages {toc_range['start_page']}-{toc_range['end_page']}")

        # Check ocr-pages dependency
        ocr_pages_stage = OcrPagesStage(self.storage)
        self.check_dependency_completed(ocr_pages_stage)

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        self.logger.info("Starting extract-toc", model=self.model)

        # Load finder result from find-toc stage
        find_toc_storage = self.storage.stage('find-toc')
        finder_result = find_toc_storage.load_file("finder_result.json")

        from .schemas import PageRange
        toc_range = PageRange(**finder_result["toc_page_range"])
        structure_notes_from_finder = finder_result.get("structure_notes") or {}

        global_structure_from_finder = None
        if finder_result.get("structure_summary"):
            global_structure_from_finder = finder_result["structure_summary"]
            self.logger.info(f"Using global structure from find-toc: {global_structure_from_finder.get('total_levels')} levels")

        self.logger.info("Using ToC range from find-toc", start=toc_range.start_page, end=toc_range.end_page)

        # Phase 1: Extract ToC entries (if-gate pattern)
        entries_path = self.stage_storage.output_dir / "entries.json"
        if not entries_path.exists():
            self.logger.info("=== Phase 1: Extract ToC Entries ===")
            print("👁️  Phase 1: Extract ToC entries")

            from .detection import extract_toc_entries

            entries_data, phase1_metrics = extract_toc_entries(
                storage=self.storage,
                toc_range=toc_range,
                structure_notes_from_finder=structure_notes_from_finder,
                logger=self.logger,
                global_structure_from_finder=global_structure_from_finder,
                model=self.model
            )

            self.stage_storage.save_file("entries.json", entries_data)

            self.stage_storage.metrics_manager.record(
                key="phase1_entry_extraction",
                cost_usd=phase1_metrics['cost_usd'],
                time_seconds=phase1_metrics['time_seconds'],
                custom_metrics={
                    "phase": "extract_entries",
                    "pages_processed": phase1_metrics['pages_processed'],
                    "total_entries": phase1_metrics['total_entries'],
                    "completion_tokens": phase1_metrics['completion_tokens'],
                    "prompt_tokens": phase1_metrics['prompt_tokens'],
                    "reasoning_tokens": phase1_metrics['reasoning_tokens'],
                }
            )

            self.logger.info(f"Saved entries.json ({phase1_metrics['total_entries']} entries from {phase1_metrics['pages_processed']} pages)")

        # Phase 2: Assemble ToC (if-gate pattern)
        toc_path = self.stage_storage.output_dir / "toc.json"
        if not toc_path.exists():
            self.logger.info("=== Phase 2: Assemble ToC ===")
            print("📝 Phase 2: Assemble and validate ToC")

            from .assembly import assemble_toc

            toc_data, phase2_metrics = assemble_toc(
                storage=self.storage,
                toc_range=toc_range,
                logger=self.logger,
                model=self.model
            )

            self.stage_storage.save_file("toc.json", toc_data)

            self.stage_storage.metrics_manager.record(
                key="phase2_assembly",
                cost_usd=phase2_metrics['cost_usd'],
                time_seconds=phase2_metrics['time_seconds'],
                custom_metrics={
                    "phase": "assembly",
                    "total_entries": phase2_metrics['total_entries'],
                    "confidence": phase2_metrics['confidence'],
                    "issues_found": phase2_metrics['issues_found'],
                    "completion_tokens": phase2_metrics['completion_tokens'],
                    "prompt_tokens": phase2_metrics['prompt_tokens'],
                    "reasoning_tokens": phase2_metrics['reasoning_tokens'],
                }
            )

            self.logger.info(f"Saved toc.json ({phase2_metrics['total_entries']} entries, confidence={phase2_metrics['confidence']:.2f})")

        return {"status": "success"}
