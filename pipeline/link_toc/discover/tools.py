"""Tools for pattern entry finder agents."""

import json
from typing import Dict, List, Optional

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.agent import AgentTools

from ..find_entries.agent.tools import (
    get_heading_pages, grep_text, get_page_ocr,
    get_book_structure, is_in_back_matter
)
from ..schemas import ExcludedPageRange


class PatternEntryFinderTools(AgentTools):
    """Tools for finding a specific pattern entry (e.g., Chapter 14)."""

    def __init__(
        self,
        storage: BookStorage,
        entry: Dict,
        excluded_ranges: List[ExcludedPageRange],
        total_pages: int,
        logger: Optional[PipelineLogger] = None
    ):
        self.storage = storage
        self.entry = entry  # {identifier, level_name, level, search_range, file_key}
        self.excluded_ranges = excluded_ranges
        self.total_pages = total_pages
        self.logger = logger
        self._pending_result: Optional[Dict] = None
        self._current_images: Optional[List] = None
        self._book_structure = get_book_structure(storage, logger)

    def get_tools(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_heading_pages",
                    "description": "Returns pages where headings were detected. Use to find potential chapter/section starts.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_page": {"type": ["integer", "null"], "description": "Start of page range"},
                            "end_page": {"type": ["integer", "null"], "description": "End of page range"}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "grep_text",
                    "description": "Search book text for a pattern. Returns pages with match counts. Try different query variations: numeric ('chapter 5'), spelled out ('CHAPTER FIVE'), Roman ('CHAPTER V').",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Text to search for (supports regex)"}
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_page_ocr",
                    "description": "Get full OCR text for a page. Use to verify candidates before submitting.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {"type": "integer", "description": "Scan page number"}
                        },
                        "required": ["page_num"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "view_page_image",
                    "description": "View page image visually. Use when OCR is unclear or to verify heading formatting.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {"type": "integer", "description": "Page number to view"}
                        },
                        "required": ["page_num"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_result",
                    "description": "Submit your final result.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "scan_page": {"type": ["integer", "null"], "description": "Scan page where found (null if not found)"},
                            "reasoning": {"type": "string", "description": "How you found it or why not found"}
                        },
                        "required": ["scan_page", "reasoning"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, tool_input: Dict) -> str:
        if tool_name == "get_heading_pages":
            results = get_heading_pages(
                self.storage,
                tool_input.get("start_page"),
                tool_input.get("end_page"),
                self.logger
            )
            # Filter out excluded ranges
            results = [r for r in results if not self._is_excluded(r["scan_page"])]
            return json.dumps(results, indent=2)

        elif tool_name == "grep_text":
            results = grep_text(tool_input["query"], self.storage, self.logger)
            # Add back matter flag and filter excluded
            filtered = []
            for r in results:
                if self._is_excluded(r["scan_page"]):
                    continue
                r["in_back_matter"] = is_in_back_matter(r["scan_page"], self._book_structure)
                filtered.append(r)
            return json.dumps(filtered, indent=2)

        elif tool_name == "get_page_ocr":
            page_num = tool_input["page_num"]
            return json.dumps({
                "page_num": page_num,
                "ocr_text": get_page_ocr(page_num, self.storage, self.logger),
                "excluded": self._is_excluded(page_num),
            }, indent=2)

        elif tool_name == "view_page_image":
            return self._view_page_image(tool_input["page_num"])

        elif tool_name == "write_result":
            scan_page = tool_input["scan_page"]
            # Validate not in excluded range
            if scan_page and self._is_excluded(scan_page):
                return json.dumps({
                    "error": f"Page {scan_page} is in an excluded range (back matter). Please find the actual chapter location."
                })
            self._pending_result = {
                "scan_page": scan_page,
                "reasoning": tool_input["reasoning"],
            }
            return json.dumps({"status": "success"})

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _is_excluded(self, page_num: int) -> bool:
        """Check if page is in an excluded range."""
        for ex in self.excluded_ranges:
            if ex.start_page <= page_num <= ex.end_page:
                return True
        return False

    def _view_page_image(self, page_num: int) -> str:
        try:
            self._current_images = [self.storage.source().load_page_image(
                page_num=page_num,
                downsample=True,
                max_payload_kb=250
            )]
            return json.dumps({
                "success": True,
                "page": page_num,
                "excluded": self._is_excluded(page_num)
            })
        except Exception as e:
            return json.dumps({"error": str(e)})

    def is_complete(self) -> bool:
        return self._pending_result is not None

    def get_images(self) -> Optional[List]:
        return self._current_images
