"""OCR stage file I/O operations using thread-safe StageStorage APIs."""

from pathlib import Path
from typing import Dict, Any, Optional

from infra.storage.book_storage import BookStorage
from .providers.schemas import ProviderSelection


class OCRStageStorage:
    def __init__(self, stage_name: str = "ocr"):
        self.stage_name = stage_name

    def load_selection_map(self, storage: BookStorage) -> Dict[str, Any]:
        stage_storage = storage.stage(self.stage_name)
        selection_map_file = stage_storage.output_dir / "selection_map.json"

        if selection_map_file.exists():
            return stage_storage.load_file("selection_map.json")

        return {}

    def save_selection_map(
        self,
        storage: BookStorage,
        selection_map: Dict[str, Any]
    ) -> None:
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file("selection_map.json", selection_map)

    def update_selection(
        self,
        storage: BookStorage,
        page_num: int,
        selection_data: Dict[str, Any]
    ) -> None:
        # Atomic read-modify-write under lock for resume support
        validated = ProviderSelection(**selection_data)
        stage_storage = storage.stage(self.stage_name)

        with stage_storage._lock:
            selection_map = self.load_selection_map(storage)
            selection_map[str(page_num)] = validated.model_dump()
            self.save_selection_map(storage, selection_map)

    def load_selected_page(
        self,
        storage: BookStorage,
        page_num: int,
        include_line_word_data: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Load the selected OCR output for a page.

        Args:
            storage: BookStorage instance
            page_num: Page number to load
            include_line_word_data: If False, strips line/word nested data to reduce size
                                   (useful for correction stages that only need paragraph text)

        Returns:
            Selected OCR output dict, or None if not found
        """
        selection_map = self.load_selection_map(storage)

        page_key = str(page_num)
        if page_key not in selection_map:
            return None

        provider_name = selection_map[page_key]["provider"]
        ocr_data = self.load_provider_page(storage, provider_name, page_num)

        # Strip line/word data if requested (reduces token cost)
        if ocr_data and not include_line_word_data:
            ocr_data = self._strip_line_word_data(ocr_data)

        return ocr_data

    def _strip_line_word_data(self, ocr_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove line and word-level data from OCR output.

        Keeps only paragraph-level text, bounding boxes, and metadata.
        Reduces token usage for downstream stages that only need paragraph text.

        Args:
            ocr_data: Full OCR output dict

        Returns:
            Filtered OCR output with lines/words removed
        """
        filtered = ocr_data.copy()

        if 'blocks' in filtered:
            filtered['blocks'] = [
                {
                    'block_num': block.get('block_num'),
                    'bbox': block.get('bbox'),
                    'paragraphs': [
                        {
                            'par_num': para.get('par_num'),
                            'bbox': para.get('bbox'),
                            'text': para.get('text'),
                            'avg_confidence': para.get('avg_confidence'),
                            'source': para.get('source', 'primary_ocr'),
                            # lines field removed - not needed for correction
                        }
                        for para in block.get('paragraphs', [])
                    ]
                }
                for block in filtered['blocks']
            ]

        return filtered

    def load_provider_page(
        self,
        storage: BookStorage,
        provider_name: str,
        page_num: int
    ) -> Optional[Dict[str, Any]]:
        stage_storage = storage.stage(self.stage_name)
        provider_file = stage_storage.output_page(page_num, extension="json", subfolder=provider_name)

        if not provider_file.exists():
            return None

        return stage_storage.load_page(page_num, subfolder=provider_name)

    def get_provider_dir(self, storage: BookStorage, provider_name: str) -> Path:
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.output_dir / provider_name

    def provider_page_exists(
        self,
        storage: BookStorage,
        provider_name: str,
        page_num: int
    ) -> bool:
        stage_storage = storage.stage(self.stage_name)
        provider_file = stage_storage.output_page(page_num, extension="json", subfolder=provider_name)
        return provider_file.exists()

    def save_provider_output(
        self,
        storage: BookStorage,
        page_num: int,
        provider_name: str,
        result,  # OCRResult
        output_schema,  # OCRPageOutput
    ):
        from PIL import Image
        import json

        provider_dir = self.get_provider_dir(storage, provider_name)
        provider_dir.mkdir(parents=True, exist_ok=True)

        images_metadata = []
        if "confirmed_image_boxes" in result.metadata:
            confirmed_boxes = result.metadata["confirmed_image_boxes"]
            if confirmed_boxes:
                images_dir = provider_dir / "images"
                images_dir.mkdir(parents=True, exist_ok=True)

                source_file = storage.stage("source").output_page(page_num, extension="png")
                pil_image = Image.open(source_file)

                for img_id, img_box in enumerate(confirmed_boxes, 1):
                    x, y, w, h = img_box
                    cropped = pil_image.crop((x, y, x + w, y + h))

                    img_filename = f"page_{page_num:04d}_img_{img_id:03d}.png"
                    img_path = images_dir / img_filename

                    cropped.save(img_path)

                    relative_path = img_path.relative_to(storage.book_dir)
                    images_metadata.append({
                        "image_id": img_id,
                        "bbox": list(img_box),
                        "image_file": str(relative_path),
                        "ocr_attempted": True,
                        "ocr_text_recovered": None,
                    })

        page_data = {
            "page_number": page_num,
            "page_dimensions": result.metadata.get("page_dimensions", {}),
            "ocr_timestamp": result.metadata.get("ocr_timestamp"),
            "blocks": result.blocks,
            "images": images_metadata,
        }

        output_file = provider_dir / f"page_{page_num:04d}.json"
        validated = output_schema(**page_data)
        with open(output_file, "w") as f:
            json.dump(validated.model_dump(), f, indent=2)
