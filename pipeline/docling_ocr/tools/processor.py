import time
from typing import Dict, Any, List
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.pipeline.rich_progress import RichProgressBar

from ..schemas import DoclingOcrPageOutput


def _initialize_docling_converter(use_mlx: bool):
    """Initialize Docling converter with MLX backend if available.

    Configuration notes:
    - temperature=0.0: Deterministic output (already set in model spec)
    - max_new_tokens=8192: Maximum output tokens (already set in model spec)
    - images_scale=1.0: Don't upscale images (reduces processing time)
    - generate_page_images=False: Don't embed images in output (saves space)
    """
    import logging

    # Suppress verbose Docling logging
    logging.getLogger('docling').setLevel(logging.WARNING)
    logging.getLogger('docling_core').setLevel(logging.WARNING)

    try:
        from docling.datamodel import vlm_model_specs
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import VlmPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.pipeline.vlm_pipeline import VlmPipeline
    except ImportError as e:
        raise ImportError(
            "Docling library not installed. Install with: pip install docling"
        ) from e

    # Configure VLM options
    if use_mlx:
        vlm_options = vlm_model_specs.GRANITEDOCLING_MLX
    else:
        vlm_options = vlm_model_specs.GRANITEDOCLING

    pipeline_options = VlmPipelineOptions(
        vlm_options=vlm_options,
        images_scale=1.0,  # Don't upscale (default is 1.0, but making explicit)
        generate_page_images=False,  # Don't embed images (we strip them anyway)
    )

    # Create converter (for images, not PDFs)
    converter = DocumentConverter(
        format_options={
            InputFormat.IMAGE: PdfFormatOption(  # Uses same options for images
                pipeline_cls=VlmPipeline,
                pipeline_options=pipeline_options,
            ),
        }
    )

    return converter


def _process_single_page(
    page_num: int,
    source_file: Path,
    converter,
    logger: PipelineLogger
) -> Dict[str, Any]:
    """Process a single page with Docling.

    Args:
        page_num: Page number
        source_file: Path to source image
        converter: Docling DocumentConverter instance
        logger: Pipeline logger

    Returns:
        Dict with page_num, docling_json (lossless), markdown, and metadata
    """
    import json
    import tempfile

    start_time = time.time()

    try:
        # Convert image to DoclingDocument
        result = converter.convert(source=str(source_file))
        doc = result.document

        # Export to markdown
        markdown = doc.export_to_markdown()

        # Get lossless JSON serialization
        # DoclingDocument.save_as_json() writes to file, so use temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            doc.save_as_json(tmp_path)
            with open(tmp_path, 'r') as f:
                docling_json = json.load(f)

            # Strip embedded images to reduce file size (base64 PNGs can be 5MB+ per page)
            # The images are already stored in source/ directory, no need to duplicate them
            if 'pages' in docling_json:
                for page_key in docling_json['pages']:
                    if 'image' in docling_json['pages'][page_key]:
                        if 'uri' in docling_json['pages'][page_key]['image']:
                            # Replace data URI with reference to source file
                            docling_json['pages'][page_key]['image']['uri'] = f"file://page_{page_num:04d}.png"
        finally:
            tmp_path.unlink()  # Clean up temp file

        # Detect special elements from the document structure
        # Check doc.body for element types
        has_tables = False
        has_equations = False
        has_code = False

        if hasattr(doc, 'body') and hasattr(doc.body, 'elements'):
            for element in doc.body.elements:
                element_type = getattr(element, 'type', None)
                if element_type:
                    if 'table' in str(element_type).lower():
                        has_tables = True
                    if 'equation' in str(element_type).lower() or 'formula' in str(element_type).lower():
                        has_equations = True
                    if 'code' in str(element_type).lower():
                        has_code = True

        # Also check markdown for equation markers
        if not has_equations and ('$$' in markdown or '\\(' in markdown):
            has_equations = True

        processing_time = time.time() - start_time

        return {
            "page_num": page_num,
            "docling_json": docling_json,
            "markdown": markdown,
            "char_count": len(markdown),
            "has_tables": has_tables,
            "has_equations": has_equations,
            "has_code": has_code,
            "processing_time_seconds": processing_time
        }

    except Exception as e:
        logger.error(f"  Page {page_num}: Docling processing failed: {str(e)}")
        raise


def process_batch(
    storage: BookStorage,
    logger: PipelineLogger,
    remaining_pages: List[int],
    max_workers: int,
    use_mlx: bool = True
) -> Dict[str, Any]:
    logger.info(
        f"Processing {len(remaining_pages)} pages with Granite Docling "
        f"({'MLX' if use_mlx else 'standard'} backend)"
    )

    # Initialize converter
    logger.info("Loading Granite Docling model...")
    converter = _initialize_docling_converter(use_mlx)

    source_storage = storage.stage("source")
    stage_storage = storage.stage("docling-ocr")

    pages_processed = 0
    total_time = 0.0
    start_time = time.time()

    def process_page_wrapper(page_num: int):
        """Wrapper for processing a single page."""
        nonlocal pages_processed, total_time

        source_file = source_storage.output_dir / f"page_{page_num:04d}.png"

        if not source_file.exists():
            logger.error(f"  Page {page_num}: Source image not found: {source_file}")
            return None

        try:
            page_data = _process_single_page(
                page_num=page_num,
                source_file=source_file,
                converter=converter,
                logger=logger
            )

            # Save validated output
            stage_storage.save_page(
                page_num,
                page_data,
                schema=DoclingOcrPageOutput
            )

            # Record metrics
            stage_storage.metrics_manager.record(
                key=f"page_{page_num:04d}",
                cost_usd=0.0,  # Local processing, no API cost
                time_seconds=page_data["processing_time_seconds"],
                custom_metrics={
                    "page": page_num,
                    "char_count": page_data["char_count"],
                    "has_tables": page_data["has_tables"],
                    "has_equations": page_data["has_equations"],
                    "has_code": page_data["has_code"],
                }
            )

            pages_processed += 1
            total_time += page_data["processing_time_seconds"]

            return page_data

        except Exception as e:
            logger.error(f"  ✗ Page {page_num}: {str(e)}")
            return None

    # Process pages in parallel with progress bar
    # Note: Processing sequentially to avoid memory leaks from Docling's internal state
    # The DocumentConverter is not thread-safe and creates MLX resources per instance
    with RichProgressBar(
        total=len(remaining_pages),
        prefix="   ",
        unit="pages"
    ) as progress:
        for page_num in remaining_pages:
            result = process_page_wrapper(page_num)

            # Update progress bar
            elapsed = time.time() - start_time
            avg_time = total_time / pages_processed if pages_processed > 0 else 0
            suffix = f"{pages_processed}/{len(remaining_pages)} • {avg_time:.1f}s/page"
            progress.update(pages_processed, suffix=suffix)

    avg_time = total_time / pages_processed if pages_processed > 0 else 0

    logger.info(
        "Docling OCR complete",
        pages_processed=pages_processed,
        avg_time_per_page=f"{avg_time:.1f}s",
        total_time=f"{total_time:.1f}s"
    )

    return {
        "status": "success",
        "pages_processed": pages_processed,
        "total_time_seconds": total_time,
        "avg_time_per_page": avg_time
    }
