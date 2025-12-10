"""Phase 2: Extract text and polish entries (parallel LLM batch)."""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from infra.pipeline.status import PhaseStatusTracker
from infra.pipeline.storage.stage_storage import StageStorage
from infra.llm.batch import LLMBatchProcessor, LLMBatchConfig
from infra.llm.models import LLMRequest, LLMResult

from ..tools import extract_section_text
from ..tools.text_polish import (
    POLISH_SYSTEM_PROMPT,
    build_polish_prompt,
    POLISH_JSON_SCHEMA,
    parse_polish_result,
)
from ..schemas import StructureEntry, SectionText


def create_polish_tracker(stage_storage: StageStorage, model: str, max_workers: int = 10):
    # Sections to skip (redundant in structured digital form)
    SKIP_SEMANTIC_TYPES = {"index"}

    def discover_entries(phase_dir: Path) -> List[str]:
        """Discover entry IDs from the skeleton."""
        try:
            skeleton = stage_storage.load_file("build_structure/structure_skeleton.json")
        except FileNotFoundError:
            return []
        if not skeleton:
            return []
        entries = skeleton.get("entries", [])
        # Only entries with page ranges, skip Index (redundant with search)
        return [
            e["entry_id"] for e in entries
            if e.get("scan_page_end") and e.get("semantic_type") not in SKIP_SEMANTIC_TYPES
        ]

    def output_path_fn(entry_id: str, phase_dir: Path) -> Path:
        return phase_dir / f"{entry_id}.json"

    def process_entries(tracker: PhaseStatusTracker, model=model, max_workers=max_workers):
        storage = tracker.storage
        logger = tracker.logger

        # Load skeleton
        skeleton = storage.stage("common-structure").load_file("build_structure/structure_skeleton.json")
        entries_data = skeleton.get("entries", [])
        entry_lookup = {e["entry_id"]: StructureEntry(**e) for e in entries_data}

        # Pre-extract text for all entries (fast, no LLM)
        # Store in a dict for request_builder to access
        extracted_texts: Dict[str, tuple] = {}
        remaining = tracker.get_remaining_items()

        if not remaining:
            logger.info("All entries already processed")
            return

        logger.info(f"Extracting text for {len(remaining)} entries...")
        for entry_id in remaining:
            entry = entry_lookup.get(entry_id)
            if not entry:
                continue

            section_text = extract_section_text(
                storage=storage,
                logger=logger,
                scan_page_start=entry.scan_page_start,
                scan_page_end=entry.scan_page_end or entry.scan_page_start,
            )
            extracted_texts[entry_id] = (entry, section_text)

        logger.info(f"Processing {len(remaining)} entries with LLM polish (max {max_workers} workers)...")

        def request_builder(item, storage, **kwargs) -> Optional[LLMRequest]:
            """Build LLM request for an entry."""
            entry_id = item
            if entry_id not in extracted_texts:
                return None

            entry, section_text = extracted_texts[entry_id]
            if not section_text or not section_text.mechanical_text:
                # No text - save empty result immediately
                _save_entry_result(tracker.phase_dir, entry_id, entry.title, None)
                return None

            return LLMRequest(
                id=entry_id,
                messages=[
                    {"role": "system", "content": POLISH_SYSTEM_PROMPT},
                    {"role": "user", "content": build_polish_prompt(entry.title, section_text.mechanical_text)}
                ],
                response_format=POLISH_JSON_SCHEMA,
                max_tokens=2000,
                timeout=120,
            )

        def result_handler(result: LLMResult):
            """Handle LLM result and save entry file."""
            entry_id = result.request.id
            if entry_id not in extracted_texts:
                logger.warning(f"No context for entry {entry_id}")
                return

            entry, section_text = extracted_texts[entry_id]

            if result.success and result.parsed_json:
                edits = parse_polish_result(result.parsed_json, section_text.mechanical_text)
                section_text.edits_applied = edits

                # Apply edits
                final_text = section_text.mechanical_text
                for edit in edits:
                    if edit.old_text in final_text:
                        final_text = final_text.replace(edit.old_text, edit.new_text, 1)
                section_text.final_text = final_text
                section_text.word_count = len(final_text.split())

                result.record_to_metrics(
                    metrics_manager=tracker.stage_storage.metrics_manager,
                    key=f"polish_{entry_id}",
                )
                logger.info(f"✓ {entry_id}: {len(edits)} edits, {section_text.word_count} words")
            else:
                # LLM failed - use mechanical text as final
                section_text.final_text = section_text.mechanical_text
                section_text.edits_applied = []
                section_text.word_count = len(section_text.mechanical_text.split()) if section_text.mechanical_text else 0
                logger.warning(f"✗ {entry_id}: {result.error_message}")

            _save_entry_result(tracker.phase_dir, entry_id, entry.title, section_text)

        # Use batch processor
        batch_config = LLMBatchConfig(
            tracker=tracker,
            model=model,
            batch_name="polish_entries",
            request_builder=request_builder,
            result_handler=result_handler,
            max_workers=max_workers,
        )

        processor = LLMBatchProcessor(batch_config)
        processor.process()

        logger.info(f"Processed {len(remaining)} entries")

    return PhaseStatusTracker(
        stage_storage=stage_storage,
        phase_name="polish_entries",
        discoverer=discover_entries,
        output_path_fn=output_path_fn,
        run_fn=process_entries,
        use_subdir=True,
        run_kwargs={"model": model, "max_workers": max_workers},
        description="Extract and polish chapter text with LLM (parallel)",
    )


def _save_entry_result(phase_dir: Path, entry_id: str, title: str, section_text: Optional[SectionText]):
    """Save an entry result to JSON file."""
    output = {
        "entry_id": entry_id,
        "title": title,
        "content": section_text.model_dump() if section_text else None,
    }
    output_path = phase_dir / f"{entry_id}.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
