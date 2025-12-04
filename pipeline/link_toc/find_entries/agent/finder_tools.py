from typing import Dict, List, Optional

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.agent import AgentTools

from .tools import get_heading_pages, grep_text, get_page_ocr


class TocEntryFinderTools(AgentTools):

    def __init__(self, storage: BookStorage, toc_entry: Dict, total_pages: int, logger: Optional[PipelineLogger] = None):
        self.storage = storage
        self.toc_entry = toc_entry
        self.total_pages = total_pages
        self.logger = logger
        self._pending_result: Optional[Dict] = None
        self._candidates_checked: List[int] = []
        self._current_page_num: Optional[int] = None
        self._page_observations: List[Dict[str, str]] = []
        self._current_images: Optional[List] = None

    def get_tools(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_heading_pages",
                    "description": "Returns pages where headings were detected. May include running headers but detection is inconsistent. Use grep_text to see the full density pattern and find the true chapter start.",
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
                    "description": "Search book text for a pattern. Returns pages with match counts. Running headers create clusters of consecutive matches. The first page in a cluster is the chapter start.",
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
                    "description": "View page image visually. Use when OCR is unclear or to verify heading formatting. One page at a time in context.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {"type": "integer", "description": "Page number to view"},
                            "observations": {"type": "string", "description": "Observations about previous page (optional)"}
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
                            "reasoning": {"type": "string", "description": "How you found it or why you couldn't"}
                        },
                        "required": ["scan_page", "reasoning"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, tool_input: Dict) -> str:
        import json

        if tool_name == "get_heading_pages":
            results = get_heading_pages(
                self.storage,
                tool_input.get("start_page"),
                tool_input.get("end_page"),
                self.logger
            )
            return json.dumps(results, indent=2)

        elif tool_name == "grep_text":
            results = grep_text(tool_input["query"], self.storage, self.logger)
            return json.dumps(results, indent=2)

        elif tool_name == "get_page_ocr":
            page_num = tool_input["page_num"]
            if page_num not in self._candidates_checked:
                self._candidates_checked.append(page_num)
            return json.dumps({
                "page_num": page_num,
                "ocr_text": get_page_ocr(page_num, self.storage, self.logger),
            }, indent=2)

        elif tool_name == "view_page_image":
            return self._view_page_image(tool_input["page_num"], tool_input.get("observations"))

        elif tool_name == "write_result":
            self._pending_result = {
                "scan_page": tool_input["scan_page"],
                "reasoning": tool_input["reasoning"],
            }
            return json.dumps({"status": "success"})

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _view_page_image(self, page_num: int, observations: Optional[str] = None) -> str:
        import json

        try:
            if observations and self._current_page_num is not None:
                self._page_observations.append({
                    "page_num": self._current_page_num,
                    "observations": observations
                })

            self._current_images = [self.storage.source().load_page_image(
                page_num=page_num,
                downsample=True,
                max_payload_kb=250
            )]

            if page_num not in self._candidates_checked:
                self._candidates_checked.append(page_num)

            previous_page = self._current_page_num
            self._current_page_num = page_num

            return json.dumps({"success": True, "page": page_num, "previous_page": previous_page})

        except Exception as e:
            return json.dumps({"error": str(e)})

    def is_complete(self) -> bool:
        return self._pending_result is not None

    def get_images(self) -> Optional[List]:
        return self._current_images
