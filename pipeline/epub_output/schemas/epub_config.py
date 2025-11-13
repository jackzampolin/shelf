from typing import Literal, Optional
from pydantic import BaseModel, Field


class EpubConfig(BaseModel):
    footnote_placement: Literal["end_of_chapter", "end_of_book", "popup"] = "end_of_chapter"
    include_headers_footers: bool = False
    css_theme: Literal["serif", "sans-serif", "custom"] = "serif"
    image_quality: Literal["original", "compressed"] = "original"
    ocr_source: Literal["olm-ocr", "mistral-ocr", "paddle-ocr"] = "mistral-ocr"
    epub_version: Literal["2.0", "3.0"] = "3.0"
    generate_page_list: bool = True
    validate_output: bool = True
