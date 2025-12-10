import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timezone

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import artifact_tracker

from pipeline.common_structure.schemas import CommonStructureOutput

from .schemas import EpubConfig
from .builders import extract_chapter_content, build_epub


class EpubOutputStage(BaseStage):
    name = "epub-output"
    dependencies = ["common-structure", "label-structure"]

    # Metadata
    icon = "📖"
    short_name = "Generate Output"
    description = "Create ePub files, audiobook scripts, or structured API output"
    phases = [
        {"name": "generate_epub", "description": "Build and validate ePub 3.0 file"},
    ]

    @classmethod
    def default_kwargs(cls, **overrides):
        defaults = {
            "footnote_placement": "end_of_chapter",
            "include_headers_footers": False,
            "css_theme": "serif",
            "image_quality": "original",
            "ocr_source": "mistral",
            "epub_version": "3.0",
            "generate_page_list": True,
            "validate_output": True,
        }
        defaults.update(overrides)
        return defaults

    def __init__(self, storage: BookStorage, **kwargs):
        super().__init__(storage)
        self.config = EpubConfig(**kwargs)

        def generate_epub(tracker, **kwargs):
            return self._generate_epub(tracker)

        # The epub file is generated in the book's root directory, not the stage directory
        def discover_epub(phase_dir):
            return [f"{storage.scan_id}.epub"]

        # Output path ignores phase_dir and uses book root
        def output_path_for_epub(item, phase_dir):
            return storage.book_dir / item

        from infra.pipeline.status import PhaseStatusTracker
        self.status_tracker = PhaseStatusTracker(
            stage_storage=self.stage_storage,
            phase_name="generate_epub",
            discoverer=discover_epub,
            output_path_fn=output_path_for_epub,
            run_fn=generate_epub,
            use_subdir=False,
            description="Build and validate ePub 3.0 file",
        )


    def _generate_epub(self, tracker) -> Dict[str, Any]:
        storage = tracker.storage
        logger = tracker.logger

        epub_path = storage.book_dir / f"{storage.scan_id}.epub"

        start_time = datetime.now(timezone.utc)

        logger.info("Phase 1: Loading structure...")
        structure = self._load_structure(storage)
        logger.info(
            f"✓ Loaded structure: {structure.total_chapters} chapters, "
            f"{structure.total_sections} sections"
        )

        logger.info("Phase 2: Extracting chapter content...")
        chapters = self._extract_all_chapters(storage, logger, structure)
        logger.info(f"✓ Extracted {len(chapters)} chapters")

        logger.info("Phase 3: Building ePub...")
        book = build_epub(
            output_path=epub_path,
            structure=structure,
            chapters=chapters,
            logger=logger,
            generate_page_list=self.config.generate_page_list,
            css_theme=self.config.css_theme
        )

        validation_result = None
        if self.config.validate_output:
            logger.info("Phase 4: Validating ePub...")
            validation_result = self._validate_epub(logger, epub_path)

        end_time = datetime.now(timezone.utc)
        processing_time = (end_time - start_time).total_seconds()

        metadata = {
            "scan_id": storage.scan_id,
            "epub_path": str(epub_path),
            "total_chapters": len(chapters),
            "config": self.config.model_dump(),
            "generated_at": end_time.isoformat(),
            "processing_time_seconds": processing_time,
            "validation": validation_result
        }

        metadata_path = tracker.phase_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(
            f"✓ ePub generation complete in {processing_time:.1f}s"
        )
        logger.info(f"  → Output: {epub_path}")

        return {
            "status": "success",
            "epub_path": str(epub_path),
            "chapters": len(chapters),
            "processing_time": processing_time
        }

    def _load_structure(self, storage) -> CommonStructureOutput:
        structure_path = storage.stage("common-structure").output_dir / "structure.json"

        if not structure_path.exists():
            raise FileNotFoundError(
                f"Structure file not found: {structure_path}\n"
                f"Run common-structure stage first."
            )

        with open(structure_path, "r") as f:
            data = json.load(f)

        return CommonStructureOutput(**data)

    def _extract_all_chapters(self, storage, logger, structure: CommonStructureOutput) -> list:
        chapters = []

        content_entries = [
            e for e in structure.entries
            if e.level >= 2
        ]

        for entry in content_entries:
            logger.debug(
                f"Extracting: {entry.title} "
                f"(pages {entry.scan_page_start}-{entry.scan_page_end})"
            )

            chapter = extract_chapter_content(
                storage=storage,
                entry_id=entry.entry_id,
                title=entry.title,
                level=entry.level,
                page_start=entry.scan_page_start,
                page_end=entry.scan_page_end,
                ocr_source=self.config.ocr_source,
                include_headers_footers=self.config.include_headers_footers
            )

            chapters.append(chapter)

        return chapters

    def _validate_epub(self, logger, epub_path: Path) -> Dict[str, Any]:
        try:
            from epubcheck import EpubCheck

            result = EpubCheck(str(epub_path))

            if result.valid:
                logger.info("✅ ePub validation passed!")
                return {
                    "valid": True,
                    "errors": [],
                    "warnings": []
                }
            else:
                logger.warning(
                    f"⚠️  ePub validation found {len(result.messages)} issues"
                )
                for msg in result.messages[:5]:
                    logger.warning(f"  - {msg}")

                return {
                    "valid": False,
                    "errors": result.messages,
                    "warnings": []
                }

        except ImportError:
            logger.warning(
                "epubcheck not installed - skipping validation\n"
                "Install with: pip install epubcheck"
            )
            return {
                "valid": None,
                "errors": [],
                "warnings": ["epubcheck not installed"]
            }
        except Exception as e:
            logger.error(f"Validation error: {e}")
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": []
            }


__all__ = [
    "EpubOutputStage",
    "EpubConfig",
]
