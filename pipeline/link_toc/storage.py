from pathlib import Path
from typing import List, Dict, Optional
from infra.storage.book_storage import BookStorage

from .schemas import LinkedTableOfContents, LinkedToCEntry, LinkTocReportEntry


class LinkTocStageStorage:
    """Storage operations for link-toc stage."""

    def __init__(self, stage_name: str = "link-toc"):
        self.stage_name = stage_name

    # Load inputs
    def load_extract_toc_output(self, storage: BookStorage) -> Dict:
        """Load complete ToC output from extract-toc/toc.json."""
        extract_toc_stage = storage.stage("extract-toc")
        toc_data = extract_toc_stage.load_file("toc.json")

        if not toc_data:
            raise RuntimeError("extract-toc stage has not produced toc.json")

        return toc_data

    def load_boundary_pages(self, storage: BookStorage) -> List[Dict]:
        """Load pages where is_boundary=true from label-pages."""
        label_pages_stage = storage.stage("label-pages")

        # Find all page output files
        output_files = sorted(label_pages_stage.output_dir.glob("page_*.json"))

        boundary_pages = []
        for output_file in output_files:
            page_data = label_pages_stage.load_file(output_file.name)
            if page_data and page_data.get("is_boundary", False):
                boundary_pages.append({
                    "page_number": page_data["page_number"],
                    "boundary_confidence": page_data.get("boundary_confidence", 0.0),
                    "reasoning": page_data.get("reasoning", ""),
                })

        return boundary_pages

    def load_all_pages_data(self, storage: BookStorage) -> Dict[int, Dict]:
        """Load all page data from label-pages (for OCR and boundary info)."""
        label_pages_stage = storage.stage("label-pages")

        # Find all page output files
        output_files = sorted(label_pages_stage.output_dir.glob("page_*.json"))

        pages_data = {}
        for output_file in output_files:
            page_data = label_pages_stage.load_file(output_file.name)
            if page_data:
                page_num = page_data["page_number"]
                pages_data[page_num] = page_data

        return pages_data

    # Save outputs
    def save_linked_toc(self, storage: BookStorage, output: LinkedTableOfContents):
        """Save linked_toc.json (enriched ToC with scan pages)."""
        stage_storage = storage.stage(self.stage_name)
        validated = LinkedTableOfContents(**output.model_dump())
        stage_storage.save_file("linked_toc.json", validated.model_dump())

    def update_linked_entry(self, storage: BookStorage, entry_index: int, linked_entry: LinkedToCEntry):
        """Update a single entry in linked_toc.json for incremental progress.

        Thread-safe: Uses StageStorage._lock (RLock already in place).
        """
        stage_storage = storage.stage(self.stage_name)

        # Load or create linked_toc structure
        if self.linked_toc_exists(storage):
            data = stage_storage.load_file("linked_toc.json")
        else:
            # Initialize empty structure
            data = {
                "entries": [],
                "toc_page_range": {},
                "entries_by_level": {},
                "original_parsing_confidence": 0.0,
                "total_entries": 0,
                "linked_entries": 0,
                "unlinked_entries": 0,
                "avg_link_confidence": 0.0,
                "total_cost_usd": 0.0,
                "total_time_seconds": 0.0,
                "avg_iterations_per_entry": 0.0
            }

        # Update or append entry
        entries = data.get("entries", [])
        entry_dict = linked_entry.model_dump()

        # Pad list if needed and insert at index
        while len(entries) <= entry_index:
            entries.append(None)
        entries[entry_index] = entry_dict

        data["entries"] = entries

        # Save using existing infrastructure (already has locking)
        stage_storage.save_file("linked_toc.json", data)

    def get_completed_entry_indices(self, storage: BookStorage) -> List[int]:
        """Return list of entry indices that have already been processed."""
        if not self.linked_toc_exists(storage):
            return []

        linked_toc = self.load_linked_toc(storage)
        if not linked_toc or not linked_toc.entries:
            return []

        # Return indices of non-None entries
        completed = []
        for idx, entry in enumerate(linked_toc.entries):
            if entry is not None:
                completed.append(idx)

        return completed

    def finalize_linked_toc_metadata(
        self,
        storage: BookStorage,
        toc_page_range: Dict,
        entries_by_level: Dict,
        original_parsing_confidence: float,
        total_entries: int,
        linked_entries: int,
        unlinked_entries: int,
        avg_link_confidence: float,
        total_cost_usd: float,
        total_time_seconds: float,
        avg_iterations_per_entry: float
    ):
        """Update metadata fields in linked_toc.json after all entries processed.

        Thread-safe: Uses StageStorage._lock (RLock already in place).
        """
        stage_storage = storage.stage(self.stage_name)

        if not self.linked_toc_exists(storage):
            return

        # Load existing data
        data = stage_storage.load_file("linked_toc.json")

        # Update metadata
        data.update({
            "toc_page_range": toc_page_range,
            "entries_by_level": entries_by_level,
            "original_parsing_confidence": original_parsing_confidence,
            "total_entries": total_entries,
            "linked_entries": linked_entries,
            "unlinked_entries": unlinked_entries,
            "avg_link_confidence": avg_link_confidence,
            "total_cost_usd": total_cost_usd,
            "total_time_seconds": total_time_seconds,
            "avg_iterations_per_entry": avg_iterations_per_entry
        })

        # Save using existing infrastructure (already has locking)
        stage_storage.save_file("linked_toc.json", data)

    def save_report(self, storage: BookStorage, report_entries: List[LinkTocReportEntry]):
        """Save report.csv."""
        import csv

        report_path = self.get_report_path(storage)
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, 'w', newline='') as f:
            if not report_entries:
                # Write header only if no entries
                writer = csv.DictWriter(f, fieldnames=[
                    "toc_index", "toc_title", "printed_page", "scan_page",
                    "confidence", "search_strategy", "iterations", "reasoning"
                ])
                writer.writeheader()
            else:
                writer = csv.DictWriter(f, fieldnames=[
                    "toc_index", "toc_title", "printed_page", "scan_page",
                    "confidence", "search_strategy", "iterations", "reasoning"
                ])
                writer.writeheader()
                for entry in report_entries:
                    writer.writerow(entry.model_dump())

    # Artifact checks
    def linked_toc_exists(self, storage: BookStorage) -> bool:
        """Check if linked_toc.json exists."""
        stage_storage = storage.stage(self.stage_name)
        return (stage_storage.output_dir / "linked_toc.json").exists()

    def load_linked_toc(self, storage: BookStorage) -> Optional[LinkedTableOfContents]:
        """Load linked_toc.json."""
        if not self.linked_toc_exists(storage):
            return None
        stage_storage = storage.stage(self.stage_name)
        data = stage_storage.load_file("linked_toc.json")
        return LinkedTableOfContents(**data) if data else None

    def report_exists(self, storage: BookStorage) -> bool:
        """Check if report.csv exists."""
        return self.get_report_path(storage).exists()

    def get_report_path(self, storage: BookStorage) -> Path:
        """Get path to report CSV file."""
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.output_dir / "report.csv"
