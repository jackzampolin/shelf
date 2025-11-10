from pydantic import BaseModel, Field
from typing import Dict, Any, Optional


class DoclingOcrPageOutput(BaseModel):
    """Output from Granite Docling MLX OCR stage.

    Stores the lossless JSON serialization of DoclingDocument, which preserves:
    - Complete hierarchical document structure
    - Layout detection and semantic elements
    - Tables, equations (LaTeX), code blocks
    - All metadata and provenance information
    """
    page_num: int = Field(..., ge=1, description="Page number in book")

    # Lossless JSON serialization of DoclingDocument
    # This is the complete document structure that can be round-tripped
    docling_json: Dict[str, Any] = Field(
        ...,
        description="Lossless JSON serialization of DoclingDocument (via save_as_json)"
    )

    # Convenience fields for quick access
    markdown: str = Field(..., description="Markdown representation of page content")
    char_count: int = Field(..., ge=0, description="Character count of markdown text")

    # Detected element flags
    has_tables: bool = Field(default=False, description="Whether page contains tables")
    has_equations: bool = Field(default=False, description="Whether page contains LaTeX equations")
    has_code: bool = Field(default=False, description="Whether page contains code blocks")

    # Processing metadata
    processing_time_seconds: Optional[float] = Field(
        None,
        description="Time taken to process this page"
    )
