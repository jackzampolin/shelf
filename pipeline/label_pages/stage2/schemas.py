"""Stage 2 LLM Response Schema - Block-level classifications"""

import copy
from enum import Enum
from typing import List, Dict, Any
from pydantic import BaseModel, Field


class BlockType(str, Enum):
    # Front matter
    TITLE_PAGE = "TITLE_PAGE"
    COPYRIGHT = "COPYRIGHT"
    DEDICATION = "DEDICATION"
    TABLE_OF_CONTENTS = "TABLE_OF_CONTENTS"
    PREFACE = "PREFACE"
    FOREWORD = "FOREWORD"
    INTRODUCTION = "INTRODUCTION"

    # Main content structure
    PART_HEADING = "PART_HEADING"
    CHAPTER_HEADING = "CHAPTER_HEADING"
    SECTION_HEADING = "SECTION_HEADING"
    SUBSECTION_HEADING = "SUBSECTION_HEADING"
    SUBSUBSECTION_HEADING = "SUBSUBSECTION_HEADING"
    BODY = "BODY"
    QUOTE = "QUOTE"
    EPIGRAPH = "EPIGRAPH"

    # Notes and references
    FOOTNOTE = "FOOTNOTE"
    ENDNOTES = "ENDNOTES"
    BIBLIOGRAPHY = "BIBLIOGRAPHY"
    REFERENCES = "REFERENCES"
    INDEX = "INDEX"

    # Back matter
    EPILOGUE = "EPILOGUE"
    APPENDIX = "APPENDIX"
    GLOSSARY = "GLOSSARY"
    ACKNOWLEDGMENTS = "ACKNOWLEDGMENTS"

    # Metadata/navigation
    HEADER = "HEADER"
    FOOTER = "FOOTER"
    PAGE_NUMBER = "PAGE_NUMBER"

    # Special
    ILLUSTRATION_CAPTION = "ILLUSTRATION_CAPTION"
    CAPTION = "CAPTION"
    TABLE = "TABLE"
    MAP_LABEL = "MAP_LABEL"
    DIAGRAM_LABEL = "DIAGRAM_LABEL"
    PHOTO_CREDIT = "PHOTO_CREDIT"
    OCR_ARTIFACT = "OCR_ARTIFACT"
    OTHER = "OTHER"


class BlockClassification(BaseModel):
    block_num: int = Field(..., ge=1, description="Block number (matches OCR)")
    classification: BlockType = Field(..., description="Classified content type")
    classification_confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in classification")


class Stage2LLMResponse(BaseModel):
    """
    Stage 2 LLM Response: Block-level classifications only.

    Page-level metadata (page numbers, page regions, structural boundaries)
    comes from Stage 1's 3-image context analysis. Stage 2 focuses solely on
    classifying OCR blocks using Stage 1 context as guidance.

    This separation ensures:
    - Clear responsibility: Stage 1 = page-level, Stage 2 = block-level
    - Single source of truth: No conflicting page-level data
    - Cost efficiency: Stage 2 doesn't re-extract what Stage 1 already found
    """
    blocks: List[BlockClassification] = Field(
        ...,
        description="Block-level classifications for all OCR blocks on this page"
    )


def build_page_specific_schema(ocr_page) -> Dict[str, Any]:
    """Build page-specific schema with exact block count from OCR."""
    from pipeline.ocr.schemas import OCRPageOutput

    base_schema = Stage2LLMResponse.model_json_schema()
    schema = copy.deepcopy(base_schema)

    num_blocks = len(ocr_page.blocks)
    schema['properties']['blocks']['minItems'] = num_blocks
    schema['properties']['blocks']['maxItems'] = num_blocks

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "page_labeling",
            "strict": True,
            "schema": schema
        }
    }
