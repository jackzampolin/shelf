"""Helper utilities for loading and working with stored DoclingDocuments."""

from typing import Optional
from pathlib import Path

from infra.pipeline.storage.book_storage import BookStorage
from ..schemas import DoclingOcrPageOutput


def load_docling_document(storage: BookStorage, page_num: int):
    """Load a DoclingDocument from storage.

    Args:
        storage: Book storage
        page_num: Page number to load

    Returns:
        DoclingDocument instance (requires docling_core)

    Raises:
        ImportError: If docling_core not installed
        FileNotFoundError: If page not found
    """
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError as e:
        raise ImportError(
            "docling_core not installed. Install with: pip install docling-core"
        ) from e

    stage_storage = storage.stage("docling-ocr")
    page_data = stage_storage.load_page(page_num, schema=DoclingOcrPageOutput)

    if not page_data:
        raise FileNotFoundError(f"Page {page_num} not found in docling-ocr stage")

    # Reconstruct DoclingDocument from lossless JSON
    return DoclingDocument.model_validate(page_data.docling_json)


def export_page_to_format(
    storage: BookStorage,
    page_num: int,
    format: str = "markdown",
    output_path: Optional[Path] = None
) -> str:
    """Export a page to a specific format.

    Args:
        storage: Book storage
        page_num: Page number
        format: Export format - "markdown", "html", "doctags"
        output_path: Optional path to save output (if None, returns string)

    Returns:
        Exported content as string

    Raises:
        ValueError: If format not supported
    """
    doc = load_docling_document(storage, page_num)

    # Export to requested format
    if format == "markdown":
        content = doc.export_to_markdown()
    elif format == "html":
        content = doc.export_to_html()
    elif format == "doctags":
        # DocTags is a token-based format
        if output_path:
            doc.save_as_doctags(output_path)
            with open(output_path, 'r') as f:
                content = f.read()
        else:
            # Need temp file for doctags
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                doc.save_as_doctags(tmp_path)
                with open(tmp_path, 'r') as f:
                    content = f.read()
            finally:
                tmp_path.unlink()
    else:
        raise ValueError(f"Unsupported format: {format}. Use 'markdown', 'html', or 'doctags'")

    # Save to file if requested
    if output_path and format != "doctags":  # doctags already saved
        output_path.write_text(content)

    return content


def get_page_tables(storage: BookStorage, page_num: int):
    """Extract all tables from a page.

    Args:
        storage: Book storage
        page_num: Page number

    Returns:
        List of table elements from the document
    """
    doc = load_docling_document(storage, page_num)

    tables = []
    if hasattr(doc, 'body') and hasattr(doc.body, 'elements'):
        for element in doc.body.elements:
            element_type = getattr(element, 'type', None)
            if element_type and 'table' in str(element_type).lower():
                tables.append(element)

    return tables


def get_page_equations(storage: BookStorage, page_num: int):
    """Extract all equations from a page.

    Args:
        storage: Book storage
        page_num: Page number

    Returns:
        List of equation elements from the document
    """
    doc = load_docling_document(storage, page_num)

    equations = []
    if hasattr(doc, 'body') and hasattr(doc.body, 'elements'):
        for element in doc.body.elements:
            element_type = getattr(element, 'type', None)
            if element_type and ('equation' in str(element_type).lower() or 'formula' in str(element_type).lower()):
                equations.append(element)

    return equations
