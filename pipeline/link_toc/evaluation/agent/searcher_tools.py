import json
from typing import Dict, List, Optional

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.agent import AgentTools

from ...schemas import MissingCandidateHeading
from pipeline.link_toc.find_entries.agent.tools import grep_text, get_page_ocr


class MissingHeadingSearchTools(AgentTools):
    """Tools for an agent searching for a predicted missing heading."""

    def __init__(
        self,
        storage: BookStorage,
        missing_candidate: MissingCandidateHeading,
        excluded_pages: List[int] = None,
        logger: Optional[PipelineLogger] = None
    ):
        self.storage = storage
        self.missing_candidate = missing_candidate
        self.excluded_pages = excluded_pages or []
        self.logger = logger

        self._pending_result: Optional[Dict] = None
        self._current_page_num: Optional[int] = None
        self._current_images: Optional[List] = None
        self._pages_checked: List[int] = []

    def get_tools(self) -> List[Dict]:
        """Return tool definitions for OpenRouter function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "grep_text",
                    "description": "Search OCR text across the book for a pattern. Returns pages with matches and context snippets. Use this FIRST to find candidate pages - search for the chapter number, title, or variations.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Text to search for (supports regex). Try: chapter number, 'Chapter X', 'CHAPTER X', roman numerals, etc."
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_page_ocr",
                    "description": "Get full OCR text for a specific page. Use to examine a page's content in detail.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {
                                "type": "integer",
                                "description": "Page number to read OCR from"
                            }
                        },
                        "required": ["page_num"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "view_page_image",
                    "description": "View a page image visually. Use when OCR is unclear or you need to confirm a heading's visual appearance.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {
                                "type": "integer",
                                "description": "Page number to view"
                            }
                        },
                        "required": ["page_num"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_result",
                    "description": "Report search results. Call when you've found the heading OR exhausted search options.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "found": {
                                "type": "boolean",
                                "description": "True if heading was found"
                            },
                            "scan_page": {
                                "type": ["integer", "null"],
                                "description": "Page number where heading was found (null if not found)"
                            },
                            "heading_text": {
                                "type": ["string", "null"],
                                "description": "Exact heading text as it appears (null if not found)"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Explanation of what you found or why you couldn't find it"
                            }
                        },
                        "required": ["found", "reasoning"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, tool_input: Dict) -> str:
        """Execute a tool and return result as JSON string."""
        if tool_name == "grep_text":
            return self._grep_text(tool_input["query"])

        elif tool_name == "get_page_ocr":
            return self._get_page_ocr(tool_input["page_num"])

        elif tool_name == "view_page_image":
            return self._view_page_image(tool_input["page_num"])

        elif tool_name == "write_result":
            self._pending_result = {
                "found": tool_input["found"],
                "scan_page": tool_input.get("scan_page"),
                "heading_text": tool_input.get("heading_text"),
                "reasoning": tool_input["reasoning"],
            }
            return json.dumps({"status": "success", "message": "Result recorded"})

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _grep_text(self, query: str) -> str:
        """Search OCR text for a pattern, filtered to predicted range."""
        start_page, end_page = self.missing_candidate.predicted_page_range

        # Get all matches
        all_results = grep_text(query, self.storage, self.logger)

        # Filter to predicted range (with some buffer)
        buffer = 5
        filtered = [
            r for r in all_results
            if (start_page - buffer) <= r["scan_page"] <= (end_page + buffer)
            and r["scan_page"] not in self.excluded_pages
        ]

        if not filtered:
            return json.dumps({
                "matches": [],
                "message": f"No matches for '{query}' in pages {start_page}-{end_page}"
            })

        return json.dumps({
            "matches": filtered,
            "total_in_range": len(filtered),
            "search_range": f"{start_page}-{end_page}"
        }, indent=2)

    def _get_page_ocr(self, page_num: int) -> str:
        """Get OCR text for a page."""
        start_page, end_page = self.missing_candidate.predicted_page_range

        # Allow some buffer outside the range
        buffer = 5
        if page_num < (start_page - buffer) or page_num > (end_page + buffer):
            return json.dumps({
                "error": f"Page {page_num} is outside the search range ({start_page}-{end_page})"
            })

        if page_num in self.excluded_pages:
            return json.dumps({
                "error": f"Page {page_num} is excluded from search."
            })

        ocr_text = get_page_ocr(page_num, self.storage, self.logger)

        if page_num not in self._pages_checked:
            self._pages_checked.append(page_num)

        # Truncate for context window
        truncated = ocr_text[:3000] if len(ocr_text) > 3000 else ocr_text

        return json.dumps({
            "page_num": page_num,
            "ocr_text": truncated,
            "truncated": len(ocr_text) > 3000
        }, indent=2)

    def _view_page_image(self, page_num: int) -> str:
        """Load page image for visual inspection."""
        start_page, end_page = self.missing_candidate.predicted_page_range

        # Allow some buffer
        buffer = 5
        if page_num < (start_page - buffer) or page_num > (end_page + buffer):
            return json.dumps({
                "error": f"Page {page_num} is outside the search range ({start_page}-{end_page})"
            })

        if page_num in self.excluded_pages:
            return json.dumps({
                "error": f"Page {page_num} is excluded from search."
            })

        try:
            downsampled_image = self.storage.source().load_page_image(
                page_num=page_num,
                downsample=True,
                max_payload_kb=400
            )

            self._current_images = [downsampled_image]
            self._current_page_num = page_num

            if page_num not in self._pages_checked:
                self._pages_checked.append(page_num)

            return json.dumps({
                "success": True,
                "current_page": page_num,
                "pages_checked": len(self._pages_checked),
                "message": f"Now viewing page {page_num}. Look for heading '{self.missing_candidate.identifier}' or variations."
            })

        except Exception as e:
            return json.dumps({"error": f"Failed to load page image: {str(e)}"})

    def is_complete(self) -> bool:
        return self._pending_result is not None

    def get_images(self) -> Optional[List]:
        return self._current_images
