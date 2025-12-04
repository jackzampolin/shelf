import json
from typing import Dict, List, Optional

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.agent import AgentTools

from ...schemas import MissingCandidateHeading
from pipeline.link_toc.find_entries.agent.tools import grep_text, get_page_ocr, get_heading_pages


class MissingHeadingSearchTools(AgentTools):

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
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_heading_pages",
                    "description": "Returns pages where headings were detected in the search range.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "grep_text",
                    "description": "Search book text for a pattern. Returns pages with match counts in the search range.",
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
                    "description": "Get full OCR text for a page. Use to verify candidates.",
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
                    "description": "View page image. Use when OCR is unclear.",
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
                    "name": "write_result",
                    "description": "Submit your final result.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "found": {"type": "boolean", "description": "True if heading was found"},
                            "scan_page": {"type": ["integer", "null"], "description": "Page where found (null if not found)"},
                            "heading_text": {"type": ["string", "null"], "description": "Exact heading text (null if not found)"},
                            "reasoning": {"type": "string", "description": "How you found it or why not"}
                        },
                        "required": ["found", "reasoning"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, tool_input: Dict) -> str:
        if tool_name == "get_heading_pages":
            return self._get_heading_pages()
        elif tool_name == "grep_text":
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
            return json.dumps({"status": "success"})
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _get_heading_pages(self) -> str:
        start_page, end_page = self.missing_candidate.predicted_page_range
        buffer = 5
        all_results = get_heading_pages(self.storage, start_page - buffer, end_page + buffer, self.logger)
        filtered = [r for r in all_results if r["scan_page"] not in self.excluded_pages]
        return json.dumps(filtered, indent=2)

    def _grep_text(self, query: str) -> str:
        start_page, end_page = self.missing_candidate.predicted_page_range
        buffer = 5
        all_results = grep_text(query, self.storage, self.logger)
        filtered = [
            r for r in all_results
            if (start_page - buffer) <= r["scan_page"] <= (end_page + buffer)
            and r["scan_page"] not in self.excluded_pages
        ]
        if not filtered:
            return json.dumps({"matches": [], "message": f"No matches in pages {start_page}-{end_page}"})
        return json.dumps({"matches": filtered, "search_range": f"{start_page}-{end_page}"}, indent=2)

    def _get_page_ocr(self, page_num: int) -> str:
        start_page, end_page = self.missing_candidate.predicted_page_range
        buffer = 5
        if page_num < (start_page - buffer) or page_num > (end_page + buffer):
            return json.dumps({"error": f"Page {page_num} outside search range ({start_page}-{end_page})"})
        if page_num in self.excluded_pages:
            return json.dumps({"error": f"Page {page_num} is excluded"})

        if page_num not in self._pages_checked:
            self._pages_checked.append(page_num)

        return json.dumps({
            "page_num": page_num,
            "ocr_text": get_page_ocr(page_num, self.storage, self.logger),
        }, indent=2)

    def _view_page_image(self, page_num: int) -> str:
        start_page, end_page = self.missing_candidate.predicted_page_range
        buffer = 5
        if page_num < (start_page - buffer) or page_num > (end_page + buffer):
            return json.dumps({"error": f"Page {page_num} outside search range ({start_page}-{end_page})"})
        if page_num in self.excluded_pages:
            return json.dumps({"error": f"Page {page_num} is excluded"})

        try:
            self._current_images = [self.storage.source().load_page_image(
                page_num=page_num,
                downsample=True,
                max_payload_kb=400
            )]
            self._current_page_num = page_num
            if page_num not in self._pages_checked:
                self._pages_checked.append(page_num)
            return json.dumps({"success": True, "page": page_num})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def is_complete(self) -> bool:
        return self._pending_result is not None

    def get_images(self) -> Optional[List]:
        return self._current_images
