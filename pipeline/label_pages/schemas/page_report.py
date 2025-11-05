from pydantic import BaseModel, Field


class LabelPagesPageReport(BaseModel):
    """Report schema for label-pages output - human-readable summary for CSV."""

    page_num: int = Field(..., ge=1, description="Scan page number")

    # BOUNDARY DETECTION
    is_boundary: bool = Field(..., description="Is this a structural boundary?")
    boundary_conf: float = Field(..., ge=0.0, le=1.0, description="Boundary confidence")
    boundary_position: str = Field(..., description="Position: top/middle/bottom/none")

    # VISUAL SIGNALS
    whitespace: str = Field(..., description="Whitespace amount at top (minimal/moderate/extensive)")
    page_density: str = Field(..., description="Overall density (sparse/moderate/dense)")

    # TEXTUAL SIGNALS
    starts_mid_sentence: bool = Field(..., description="Starts mid-sentence (clear continuation)?")
    appears_to_continue: bool = Field(..., description="Text continues from previous page?")
    has_boundary_marker: bool = Field(..., description="Has chapter/section number or marker?")
    boundary_marker_text: str = Field(default="", description="The marker text if present")
