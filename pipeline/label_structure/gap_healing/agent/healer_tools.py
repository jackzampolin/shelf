from typing import Dict, List, Optional
import json

from infra.pipeline.storage.book_storage import BookStorage
from infra.llm.agent import AgentTools


class GapHealingTools(AgentTools):

    def __init__(self, storage: BookStorage, cluster: Dict):
        self.storage = storage
        self.cluster = cluster
        self._pending_updates: List[Dict] = []
        self._current_page_num: Optional[int] = None
        self._page_observations: List[Dict[str, str]] = []
        self._current_images: Optional[List] = None
        self._pages_examined: List[int] = []

    def get_tools(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_page_metadata",
                    "description": "Read full page metadata (page_*.json) for pages OUTSIDE the cluster. Use to check context pages when needed. The cluster pages are already provided in your initial context.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {
                                "type": "integer",
                                "description": "Scan page number to read metadata for"
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
                    "description": "View page image visually (costs ~$0.001 per page). WORKFLOW: Document what you see on CURRENT page in 'current_page_observations', THEN specify next page number. One page at a time - previous page removed from context when you load next. Use when metadata is ambiguous.",
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
                    "name": "write_page_update",
                    "description": "Submit healing decision for ONE page. Call multiple times if you need to update multiple pages in the cluster. Each call records a decision file that will be applied later.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "scan_page": {
                                "type": "integer",
                                "description": "Scan page number to update"
                            },
                            "page_number_update": {
                                "type": "object",
                                "description": "Fields to update in page_number observation. Only include fields you want to change.",
                                "properties": {
                                    "present": {
                                        "type": "boolean",
                                        "description": "Is page number present?"
                                    },
                                    "number": {
                                        "type": "string",
                                        "description": "Corrected page number value"
                                    },
                                    "location": {
                                        "type": "string",
                                        "description": "Location: 'margin', 'header', 'footer'"
                                    },
                                    "confidence": {
                                        "type": "string",
                                        "description": "Confidence: 'high', 'medium', 'low'"
                                    },
                                    "source_provider": {
                                        "type": "string",
                                        "description": "Source provider (use 'agent_healed' for healed values)"
                                    }
                                }
                            },
                            "chapter_marker": {
                                "type": "object",
                                "description": "Optional: If this page is a chapter title page, extract chapter metadata",
                                "properties": {
                                    "chapter_num": {
                                        "type": "integer",
                                        "description": "Chapter number"
                                    },
                                    "chapter_title": {
                                        "type": "string",
                                        "description": "Chapter title text"
                                    },
                                    "confidence": {
                                        "type": "number",
                                        "description": "Confidence in chapter identification (0.0-1.0)"
                                    },
                                    "detected_from": {
                                        "type": "string",
                                        "description": "Source: 'heading', 'header', 'visual'"
                                    }
                                }
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Brief explanation of why you're making this update"
                            }
                        },
                        "required": ["scan_page", "reasoning"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, tool_input: Dict) -> str:
        if tool_name == "get_page_metadata":
            page_num = tool_input["page_num"]
            if page_num not in self._pages_examined:
                self._pages_examined.append(page_num)

            try:
                page_data = self.storage.stage("label-structure").load_file(
                    f"page_{page_num:04d}.json"
                )
                return json.dumps({
                    "page_num": page_num,
                    "metadata": page_data
                }, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Failed to load page {page_num}: {str(e)}"})

        elif tool_name == "view_page_image":
            page_num = tool_input["page_num"]
            current_page_observations = tool_input.get("current_page_observations")
            return self._view_page_image(page_num, current_page_observations)

        elif tool_name == "write_page_update":
            scan_page = tool_input["scan_page"]
            reasoning = tool_input["reasoning"]
            page_number_update = tool_input.get("page_number_update")
            chapter_marker = tool_input.get("chapter_marker")

            update = {
                "scan_page": scan_page,
                "cluster_id": self.cluster['cluster_id'],
                "cluster_type": self.cluster['type'],
                "reasoning": reasoning
            }

            if page_number_update:
                update["page_number_update"] = page_number_update

            if chapter_marker:
                update["chapter_marker"] = chapter_marker

            self._pending_updates.append(update)

            return json.dumps({
                "status": "success",
                "message": f"Page {scan_page} update recorded. Total updates: {len(self._pending_updates)}"
            })

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _view_page_image(self, page_num: int, current_page_observations: Optional[str] = None) -> str:
        try:
            if self._current_page_num is not None:
                if not current_page_observations:
                    return json.dumps({
                        "error": f"You are currently viewing page {self._current_page_num}. You must provide 'current_page_observations' documenting what you SEE on this page before loading page {page_num}."
                    })

                self._page_observations.append({
                    "page_num": self._current_page_num,
                    "observations": current_page_observations
                })

            downsampled_image = self.storage.source().load_page_image(
                page_num=page_num,
                downsample=True,
                max_payload_kb=250
            )

            self._current_images = [downsampled_image]

            if page_num not in self._pages_examined:
                self._pages_examined.append(page_num)

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
        return len(self._pending_updates) > 0

    def get_images(self) -> Optional[List]:
        return self._current_images

    def get_pending_updates(self) -> List[Dict]:
        return self._pending_updates

    def get_pages_examined(self) -> List[int]:
        return self._pages_examined

    def get_images_viewed(self) -> List[int]:
        return [obs["page_num"] for obs in self._page_observations]
