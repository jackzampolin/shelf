import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timezone

from infra.pipeline.base_stage import BaseStage
from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.status import MultiPhaseStatusTracker

from pipeline.common_structure.schemas import CommonStructureOutput

from .schemas import EpubConfig
from .builders import extract_chapter_content, build_epub


class EpubOutputStage(BaseStage):
    name = "epub-output"
    dependencies = ["common-structure", "label-structure"]

    @classmethod
    def default_kwargs(cls, **overrides):
        defaults = {
            "footnote_placement": "end_of_chapter",
            "include_headers_footers": False,
            "css_theme": "serif",
            "image_quality": "original",
            "ocr_source": "mistral-ocr",
            "epub_version": "3.0",
            "generate_page_list": True,
            "validate_output": True,
        }
        defaults.update(overrides)
        return defaults

    def __init__(self, storage: BookStorage, **kwargs):
        super().__init__(storage)
        self.config = EpubConfig(**kwargs)

        self.status_tracker = MultiPhaseStatusTracker(
            storage=self.storage,
            logger=self.logger,
            stage_name=self.name,
            phases=[
                {"name": "load_structure", "artifact": "structure loaded"},
                {"name": "extract_content", "artifact": "chapters extracted"},
                {"name": "build_epub", "artifact": f"{storage.scan_id}.epub"},
                {"name": "validate", "artifact": "validation complete"}
            ]
        )

    def run(self) -> Dict[str, Any]:
        if self.status_tracker.is_completed():
            return self.status_tracker.get_skip_response()

        epub_path = self.storage.root_dir / f"{self.storage.scan_id}.epub"
        if epub_path.exists():
            self.logger.info(f"✓ ePub already exists: {epub_path}")
            return {"status": "success", "epub_path": str(epub_path)}

        start_time = datetime.now(timezone.utc)

        self.logger.info("Phase 1: Loading structure...")
        structure = self._load_structure()
        self.logger.info(
            f"✓ Loaded structure: {structure.total_chapters} chapters, "
            f"{structure.total_sections} sections"
        )

        self.logger.info("Phase 2: Extracting chapter content...")
        chapters = self._extract_all_chapters(structure)
        self.logger.info(f"✓ Extracted {len(chapters)} chapters")

        self.logger.info("Phase 3: Building ePub...")
        book = build_epub(
            output_path=epub_path,
            structure=structure,
            chapters=chapters,
            logger=self.logger,
            generate_page_list=self.config.generate_page_list,
            css_theme=self.config.css_theme
        )

        validation_result = None
        if self.config.validate_output:
            self.logger.info("Phase 4: Validating ePub...")
            validation_result = self._validate_epub(epub_path)

        end_time = datetime.now(timezone.utc)
        processing_time = (end_time - start_time).total_seconds()

        metadata = {
            "scan_id": self.storage.scan_id,
            "epub_path": str(epub_path),
            "total_chapters": len(chapters),
            "config": self.config.model_dump(),
            "generated_at": end_time.isoformat(),
            "processing_time_seconds": processing_time,
            "validation": validation_result
        }

        metadata_path = self.stage_storage.output_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        self.logger.info(
            f"✓ ePub generation complete in {processing_time:.1f}s"
        )
        self.logger.info(f"  → Output: {epub_path}")

        return {
            "status": "success",
            "epub_path": str(epub_path),
            "chapters": len(chapters),
            "processing_time": processing_time
        }

    def _load_structure(self) -> CommonStructureOutput:
        structure_path = self.storage.stage("common-structure").output_dir / "structure.json"

        if not structure_path.exists():
            raise FileNotFoundError(
                f"Structure file not found: {structure_path}\n"
                f"Run common-structure stage first."
            )

        with open(structure_path, "r") as f:
            data = json.load(f)

        return CommonStructureOutput(**data)

    def _extract_all_chapters(self, structure: CommonStructureOutput) -> list:
        chapters = []

        content_entries = [
            e for e in structure.entries
            if e.level >= 2
        ]

        for entry in content_entries:
            self.logger.debug(
                f"Extracting: {entry.title} "
                f"(pages {entry.scan_page_start}-{entry.scan_page_end})"
            )

            chapter = extract_chapter_content(
                storage=self.storage,
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

    def _validate_epub(self, epub_path: Path) -> Dict[str, Any]:
        try:
            from epubcheck import EpubCheck

            result = EpubCheck(str(epub_path))

            if result.valid:
                self.logger.info("✅ ePub validation passed!")
                return {
                    "valid": True,
                    "errors": [],
                    "warnings": []
                }
            else:
                self.logger.warning(
                    f"⚠️  ePub validation found {len(result.messages)} issues"
                )
                for msg in result.messages[:5]:
                    self.logger.warning(f"  - {msg}")

                return {
                    "valid": False,
                    "errors": result.messages,
                    "warnings": []
                }

        except ImportError:
            self.logger.warning(
                "epubcheck not installed - skipping validation\n"
                "Install with: pip install epubcheck"
            )
            return {
                "valid": None,
                "errors": [],
                "warnings": ["epubcheck not installed"]
            }
        except Exception as e:
            self.logger.error(f"Validation error: {e}")
            return {
                "valid": False,
                "errors": [str(e)],
                "warnings": []
            }


__all__ = [
    "EpubOutputStage",
    "EpubConfig",
]
