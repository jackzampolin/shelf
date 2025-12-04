from typing import Dict, List, Optional
import json

from infra.pipeline.storage.book_storage import BookStorage
from infra.llm.agent import AgentTools
from ...merge import get_gap_analysis_merged_page


class GapHealingTools(AgentTools):

    def __init__(self, storage: BookStorage, cluster: Dict):
        self.storage = storage
        self.cluster = cluster
        self.cluster_id = cluster['cluster_id']
        self.agent_id = f"heal_{self.cluster_id}"
        self.healing_dir = storage.stage("label-structure").output_dir / "agent_healing"
        self.healing_dir.mkdir(parents=True, exist_ok=True)
        self._current_page_num: Optional[int] = None
        self._page_observations: List[Dict[str, str]] = []
        self._current_images: Optional[List] = None
        self._pages_examined: List[int] = []
        self._pages_healed: List[int] = []

    def get_tools(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_page_metadata",
                    "description": "Read full page metadata for any page. Cluster pages are already in your initial context, but use this to check surrounding pages.",
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
                    "name": "heal_page",
                    "description": "Heal ONE specific page by updating its page number. Call this multiple times to heal multiple pages in a gap. You must call finish_cluster when done.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "scan_page": {
                                "type": "integer",
                                "description": "Scan page number to heal"
                            },
                            "page_number": {
                                "type": "object",
                                "description": "Corrected page number fields",
                                "properties": {
                                    "number": {
                                        "type": "string",
                                        "description": "Corrected page number value"
                                    },
                                    "location": {
                                        "type": "string",
                                        "description": "Location: 'header', 'footer', 'margin'"
                                    },
                                    "source_provider": {
                                        "type": "string",
                                        "description": "Always use 'agent_healed'"
                                    }
                                },
                                "required": ["number", "source_provider"]
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "Why are you healing this specific page?"
                            }
                        },
                        "required": ["scan_page", "page_number", "reasoning"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "finish_cluster",
                    "description": "Mark this cluster as complete. Call this AFTER you've healed all pages that need healing (or determined no healing is needed). Required to complete the cluster.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": "Summary of what you did: how many pages healed, what issues were fixed, or why no healing was needed"
                            },
                            "pages_healed": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "List of page numbers you healed (empty if none)"
                            }
                        },
                        "required": ["summary", "pages_healed"]
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
                page_output = get_gap_analysis_merged_page(self.storage, page_num)
                return json.dumps({
                    "page_num": page_num,
                    "metadata": page_output.model_dump()
                }, indent=2)
            except Exception as e:
                return json.dumps({"error": f"Failed to load page {page_num}: {str(e)}"})

        elif tool_name == "view_page_image":
            page_num = tool_input["page_num"]
            current_page_observations = tool_input.get("current_page_observations")
            return self._view_page_image(page_num, current_page_observations)

        elif tool_name == "heal_page":
            scan_page = tool_input["scan_page"]
            page_number = tool_input["page_number"]
            page_number["reasoning"] = tool_input["reasoning"]

            patch = {
                "agent_id": self.agent_id,
                "page_number": page_number
            }

            decision_path = self.healing_dir / f"page_{scan_page:04d}.json"
            with open(decision_path, 'w') as f:
                json.dump(patch, f, indent=2)

            self._pages_healed.append(scan_page)

            return json.dumps({
                "status": "success",
                "message": f"✓ Page {scan_page} healed and saved. Total pages healed so far: {len(self._pages_healed)}"
            })

        elif tool_name == "finish_cluster":
            summary = tool_input["summary"]
            pages_healed = tool_input["pages_healed"]

            if set(pages_healed) != set(self._pages_healed):
                return json.dumps({
                    "error": f"Mismatch: you said you healed {pages_healed} but heal_page was called for {self._pages_healed}"
                })

            marker = {
                "cluster_id": self.cluster_id,
                "agent_id": self.agent_id,
                "summary": summary,
                "pages_healed": pages_healed,
                "pages_examined": self._pages_examined,
                "images_viewed": self.get_images_viewed()
            }
            marker_path = self.healing_dir / f"cluster_{self.cluster_id}.json"
            with open(marker_path, 'w') as f:
                json.dump(marker, f, indent=2)

            return json.dumps({
                "status": "complete",
                "message": f"✓ Cluster marked complete. {len(pages_healed)} pages healed. Cluster processing finished."
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
        marker_path = self.healing_dir / f"cluster_{self.cluster_id}.json"
        return marker_path.exists()

    def get_images(self) -> Optional[List]:
        return self._current_images

    def get_pages_healed(self) -> List[int]:
        return self._pages_healed

    def get_pages_examined(self) -> List[int]:
        return self._pages_examined

    def get_images_viewed(self) -> List[int]:
        return [obs["page_num"] for obs in self._page_observations]
