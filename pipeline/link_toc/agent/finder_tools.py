from typing import Dict, List, Optional
from PIL import Image

from infra.storage.book_storage import BookStorage
from infra.llm.agent import AgentTools
from infra.utils.pdf import downsample_for_vision

from .tools import list_boundaries, grep_text, get_page_ocr


class TocEntryFinderTools(AgentTools):

    def __init__(self, storage: BookStorage, toc_entry: Dict, total_pages: int):
        self.storage = storage
        self.toc_entry = toc_entry
        self.total_pages = total_pages
        self._pending_result: Optional[Dict] = None
        self._candidates_checked: List[int] = []
        self._current_page_num: Optional[int] = None
        self._page_observations: List[Dict[str, str]] = []

    def get_tools(self) -> List[Dict]:
        """Return tool definitions for OpenRouter function calling."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_boundaries",
                    "description": "List boundary pages from label-pages with heading previews. Returns ALL boundaries by default (50-200 items). Use start_page/end_page to narrow search if needed (calculate from total_pages context).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_page": {
                                "type": ["integer", "null"],
                                "description": "Optional: Start of page range to filter boundaries"
                            },
                            "end_page": {
                                "type": ["integer", "null"],
                                "description": "Optional: End of page range to filter boundaries"
                            }
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "grep_text",
                    "description": "Search entire book's OCR for text pattern (creates 'heatmap'). CRITICAL: Running headers create DENSITY - dense regions show chapter extent, first page in dense region is the boundary. Returns pages with match_count and context_snippets.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Text to search for (supports regex)"
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
                    "description": "Get full OCR text for a specific page. ALWAYS use this to confirm candidates before deciding. OCR is FREE and prevents mistakes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {
                                "type": "integer",
                                "description": "Scan page number to read"
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
                    "description": "View page image visually (costs ~$0.001 but worth it for accuracy). WORKFLOW: Document what you see in CURRENT page, THEN specify next page. One page at a time - previous page removed from context when you load next. This forces structured reasoning. Use liberally when OCR unclear.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {
                                "type": "integer",
                                "description": "Page number to load NEXT"
                            },
                            "current_page_observations": {
                                "type": "string",
                                "description": "What do you see on the CURRENTLY loaded page? REQUIRED if a page is already in context. Document findings before moving to next page."
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
                    "description": "Submit final search result and complete the task. Call this when you've found the ToC entry or exhausted all search strategies.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "found": {
                                "type": "boolean",
                                "description": "Did you find the ToC entry?"
                            },
                            "scan_page": {
                                "type": ["integer", "null"],
                                "description": "Scan page number where found (null if not found)"
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confidence in the match (0.0-1.0)",
                                "minimum": 0.0,
                                "maximum": 1.0
                            },
                            "search_strategy": {
                                "type": "string",
                                "description": "Strategy used: 'boundary_match' | 'grep_crosscheck' | 'visual_verify' | 'not_found'"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Brief explanation of how you found it or why you couldn't"
                            }
                        },
                        "required": ["found", "scan_page", "confidence", "search_strategy", "reasoning"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, tool_input: Dict) -> str:
        """Execute a tool and return result as JSON string."""
        import json

        if tool_name == "list_boundaries":
            start_page = tool_input.get("start_page")
            end_page = tool_input.get("end_page")
            results = list_boundaries(self.storage, start_page, end_page)
            return json.dumps(results, indent=2)

        elif tool_name == "grep_text":
            query = tool_input["query"]
            results = grep_text(query, self.storage)
            return json.dumps(results, indent=2)

        elif tool_name == "get_page_ocr":
            page_num = tool_input["page_num"]
            if page_num not in self._candidates_checked:
                self._candidates_checked.append(page_num)
            ocr_text = get_page_ocr(page_num, self.storage)
            # Truncate for context window
            truncated = ocr_text[:2000] if len(ocr_text) > 2000 else ocr_text
            return json.dumps({
                "page_num": page_num,
                "ocr_text": truncated,
                "truncated": len(ocr_text) > 2000
            }, indent=2)

        elif tool_name == "view_page_image":
            page_num = tool_input["page_num"]
            current_page_observations = tool_input.get("current_page_observations")
            return self._view_page_image(page_num, current_page_observations)

        elif tool_name == "write_result":
            # Store result for retrieval
            self._pending_result = {
                "found": tool_input["found"],
                "scan_page": tool_input["scan_page"],
                "confidence": tool_input["confidence"],
                "search_strategy": tool_input["search_strategy"],
                "reasoning": tool_input["reasoning"],
            }
            return json.dumps({"status": "success", "message": "Result recorded"})

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _view_page_image(self, page_num: int, current_page_observations: Optional[str] = None) -> str:
        """Load page image with forced observation pattern."""
        import json

        try:
            # Enforce observation requirement
            if self._current_page_num is not None:
                if not current_page_observations:
                    return json.dumps({
                        "error": f"You are currently viewing page {self._current_page_num}. You must provide 'current_page_observations' documenting what you SEE on this page before loading page {page_num}."
                    })

                # Record observations
                self._page_observations.append({
                    "page_num": self._current_page_num,
                    "observations": current_page_observations
                })

            # Load page image
            source_stage = self.storage.stage('source')
            page_image_path = source_stage.output_page(page_num, extension='png')

            if not page_image_path.exists():
                return json.dumps({
                    "error": f"Page {page_num} image not found at {page_image_path}"
                })

            image = Image.open(page_image_path)
            downsampled_image = downsample_for_vision(image, max_payload_kb=250)

            # Replace current image in context
            self.agent_client.images = [downsampled_image]

            # Track page
            if page_num not in self._candidates_checked:
                self._candidates_checked.append(page_num)

            previous_page = self._current_page_num
            self._current_page_num = page_num

            message_parts = [f"Now viewing page {page_num}."]
            if previous_page is not None:
                message_parts.append(f"Page {previous_page} observations recorded and removed from context.")

            return json.dumps({
                "success": True,
                "current_page": page_num,
                "previous_page": previous_page,
                "observations_count": len(self._page_observations),
                "message": " ".join(message_parts)
            })

        except Exception as e:
            return json.dumps({"error": f"Failed to load page image: {str(e)}"})

    def is_complete(self) -> bool:
        return self._pending_result is not None
