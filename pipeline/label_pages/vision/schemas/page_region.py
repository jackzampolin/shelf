from enum import Enum


class PageRegion(str, Enum):
    """Page region classification based on position in book."""
    FRONT_MATTER = "front_matter"
    BODY = "body"
    BACK_MATTER = "back_matter"
    TOC_AREA = "toc_area"
    UNCERTAIN = "uncertain"
