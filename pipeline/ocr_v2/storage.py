"""
OCR Stage V2 Storage

Handles all file I/O operations for OCR v2 stage using thread-safe StageStorage APIs.
Separates storage logic from pipeline orchestration.
"""

from pathlib import Path
from typing import Dict, Any, Optional

from infra.storage.book_storage import BookStorage
from .providers.schemas import ProviderSelection


class OCRStageV2Storage:
    """
    Storage manager for OCR v2 stage.

    Wraps StageStorage to provide OCR-specific convenience methods
    while using thread-safe file operations.

    Responsibilities:
    - Loading/saving selection mappings
    - Loading selected OCR outputs from provider subdirectories
    - Providing thread-safe access to provider outputs

    All file I/O uses StageStorage APIs for thread safety.
    """

    def __init__(self, stage_name: str = "ocr_v2"):
        """
        Args:
            stage_name: OCR stage name (default: "ocr_v2")
        """
        self.stage_name = stage_name

    def load_selection_map(self, storage: BookStorage) -> Dict[str, Any]:
        """
        Load selection mapping from disk using thread-safe StageStorage.

        Returns:
            Dict mapping page_num (str) -> {provider, method, agreement, confidence}
            Empty dict if file doesn't exist.
        """
        stage_storage = storage.stage(self.stage_name)
        selection_map_file = stage_storage.output_dir / "selection_map.json"

        if selection_map_file.exists():
            # Use thread-safe load_file method
            return stage_storage.load_file("selection_map.json")

        return {}

    def save_selection_map(
        self,
        storage: BookStorage,
        selection_map: Dict[str, Any]
    ) -> None:
        """
        Save selection mapping to disk using thread-safe StageStorage.

        Args:
            storage: BookStorage instance
            selection_map: Dict mapping page_num -> selection metadata
        """
        stage_storage = storage.stage(self.stage_name)
        # Use thread-safe save_file method
        stage_storage.save_file("selection_map.json", selection_map)

    def update_selection(
        self,
        storage: BookStorage,
        page_num: int,
        selection_data: Dict[str, Any]
    ) -> None:
        """
        Update selection map for a single page atomically.

        Performs read-modify-write under lock to ensure thread-safe incremental updates.
        Critical for resume support: each selection persisted immediately.

        Args:
            storage: BookStorage instance
            page_num: Page number to update
            selection_data: Selection metadata dict with keys:
                - provider: str (e.g., "tesseract-psm3")
                - method: str ("automatic" or "vision")
                - agreement: float (0.0-1.0)
                - confidence: Optional[float]
        """
        # Validate selection data against schema
        validated = ProviderSelection(**selection_data)

        stage_storage = storage.stage(self.stage_name)

        # Atomic read-modify-write under lock
        with stage_storage._lock:
            selection_map = self.load_selection_map(storage)
            selection_map[str(page_num)] = validated.model_dump()
            self.save_selection_map(storage, selection_map)

    def load_selected_page(
        self,
        storage: BookStorage,
        page_num: int
    ) -> Optional[Dict[str, Any]]:
        """
        Load the selected OCR output for a page using the selection mapping.

        Args:
            storage: BookStorage instance
            page_num: Page number to load

        Returns:
            Selected OCR output dict, or None if not found
        """
        # Load selection mapping
        selection_map = self.load_selection_map(storage)

        page_key = str(page_num)
        if page_key not in selection_map:
            return None

        # Get provider name
        provider_name = selection_map[page_key]["provider"]

        # Load from provider subdirectory
        return self.load_provider_page(storage, provider_name, page_num)

    def load_provider_page(
        self,
        storage: BookStorage,
        provider_name: str,
        page_num: int
    ) -> Optional[Dict[str, Any]]:
        """
        Load OCR output from a specific provider using thread-safe StageStorage.

        Args:
            storage: BookStorage instance
            provider_name: Provider name (e.g., "tesseract-psm3")
            page_num: Page number to load

        Returns:
            OCR output dict, or None if not found
        """
        stage_storage = storage.stage(self.stage_name)
        # Use subfolder parameter for provider subdirectory
        provider_file = stage_storage.output_page(page_num, extension="json", subfolder=provider_name)

        if not provider_file.exists():
            return None

        # Use thread-safe load_page method
        return stage_storage.load_page(page_num, subfolder=provider_name)

    def get_provider_dir(self, storage: BookStorage, provider_name: str) -> Path:
        """
        Get path to provider subdirectory using StageStorage.

        Args:
            storage: BookStorage instance
            provider_name: Provider name

        Returns:
            Path to provider directory
        """
        stage_storage = storage.stage(self.stage_name)
        return stage_storage.output_dir / provider_name

    def provider_page_exists(
        self,
        storage: BookStorage,
        provider_name: str,
        page_num: int
    ) -> bool:
        """
        Check if a provider has output for a page using StageStorage.

        Args:
            storage: BookStorage instance
            provider_name: Provider name
            page_num: Page number

        Returns:
            True if provider output exists
        """
        stage_storage = storage.stage(self.stage_name)
        provider_file = stage_storage.output_page(page_num, extension="json", subfolder=provider_name)
        return provider_file.exists()

    def save_provider_output(
        self,
        storage: BookStorage,
        page_num: int,
        provider_name: str,
        result,  # OCRResult from providers module
        output_schema,  # OCRPageOutput schema
    ):
        """
        Save OCR result to provider-specific subdirectory.

        Handles:
        - Creating provider directory structure
        - Extracting and saving detected images
        - Validating output against schema
        - Saving page JSON

        Args:
            storage: BookStorage instance
            page_num: Page number
            provider_name: Provider name (e.g., 'tesseract-psm3')
            result: OCRResult with blocks and metadata
            output_schema: Pydantic schema for validation (OCRPageOutput)
        """
        from PIL import Image
        import json

        # Create provider subdirectory
        provider_dir = self.get_provider_dir(storage, provider_name)
        provider_dir.mkdir(parents=True, exist_ok=True)

        # Save images first and get image metadata
        images_metadata = []
        if "confirmed_image_boxes" in result.metadata:
            confirmed_boxes = result.metadata["confirmed_image_boxes"]
            if confirmed_boxes:
                # Create provider images directory
                images_dir = provider_dir / "images"
                images_dir.mkdir(parents=True, exist_ok=True)

                # Load source image
                source_file = storage.stage("source").output_page(page_num, extension="png")
                pil_image = Image.open(source_file)

                # Save each image with new naming: page_{page:04d}_img_{img_id:03d}.png
                for img_id, img_box in enumerate(confirmed_boxes, 1):
                    x, y, w, h = img_box
                    cropped = pil_image.crop((x, y, x + w, y + h))

                    img_filename = f"page_{page_num:04d}_img_{img_id:03d}.png"
                    img_path = images_dir / img_filename

                    cropped.save(img_path)

                    # Build metadata with relative path from book root
                    relative_path = img_path.relative_to(storage.book_dir)
                    images_metadata.append({
                        "image_id": img_id,
                        "bbox": list(img_box),
                        "image_file": str(relative_path),
                        "ocr_attempted": True,
                        "ocr_text_recovered": None,
                    })

        # Build page output (matches OCR schema)
        page_data = {
            "page_number": page_num,
            "page_dimensions": result.metadata.get("page_dimensions", {}),
            "ocr_timestamp": result.metadata.get("ocr_timestamp"),
            "blocks": result.blocks,
            "images": images_metadata,
        }

        # Validate and save JSON
        output_file = provider_dir / f"page_{page_num:04d}.json"
        validated = output_schema(**page_data)
        with open(output_file, "w") as f:
            json.dump(validated.model_dump(), f, indent=2)
