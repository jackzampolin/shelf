"""
Simplified ToC finder tools for vision-capable agent.

The agent sees page images directly and reasons about them.
Tools only provide data access, no nested LLM calls.
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from PIL import Image

from pydantic import BaseModel, Field

from infra.storage.book_storage import BookStorage
from infra.llm.agent_client import AgentClient
from infra.utils.pdf import downsample_for_vision
from pipeline.build_structure.schemas import PageRange


class TocFinderResult(BaseModel):
    """Result from ToC finder agent."""
    toc_found: bool
    toc_page_range: Optional[PageRange] = None
    confidence: float = Field(ge=0.0, le=1.0)
    search_strategy_used: str
    reasoning: str


class TocFinderTools:
    """Minimal tool suite for vision-capable ToC finder agent."""

    def __init__(self, storage: BookStorage, agent_client: AgentClient):
        """
        Initialize tools.

        Args:
            storage: BookStorage instance for accessing book data
            agent_client: AgentClient instance (for accessing images list)
        """
        self.storage = storage
        self.agent_client = agent_client  # Access to agent_client.images
        self._pending_result: Optional[TocFinderResult] = None

    def get_tools(self) -> List[Dict]:
        """Return tool definitions for LLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_toc_label_pages",
                    "description": "Get pages where label stage detected TABLE_OF_CONTENTS blocks. Returns list of page numbers. Free, no cost.",
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
                    "name": "add_page_images_to_context",
                    "description": "Load page images and add them to conversation context so you can see them. Images are downsampled for vision API. Use this to visually inspect pages.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_nums": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "List of page numbers to load (e.g., [4, 5, 6])"
                            }
                        },
                        "required": ["page_nums"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_toc_result",
                    "description": "Write final ToC search result and complete the task. Call this when you've determined the ToC location or confirmed none exists.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "toc_found": {
                                "type": "boolean",
                                "description": "Whether ToC was found"
                            },
                            "toc_page_range": {
                                "type": "object",
                                "description": "ToC page range (null if not found)",
                                "properties": {
                                    "start_page": {"type": "integer"},
                                    "end_page": {"type": "integer"}
                                },
                                "required": ["start_page", "end_page"]
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confidence score 0.0-1.0",
                                "minimum": 0.0,
                                "maximum": 1.0
                            },
                            "search_strategy_used": {
                                "type": "string",
                                "description": "Strategy used: labels_report, vision_scan, or not_found"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "1-2 sentence explanation of how you found (or didn't find) the ToC"
                            }
                        },
                        "required": ["toc_found", "confidence", "search_strategy_used", "reasoning"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, arguments: Dict) -> str:
        """Execute a tool and return result string."""
        if tool_name == "get_toc_label_pages":
            return self.get_toc_label_pages()
        elif tool_name == "add_page_images_to_context":
            return self.add_page_images_to_context(arguments["page_nums"])
        elif tool_name == "write_toc_result":
            return self.write_toc_result(
                toc_found=arguments["toc_found"],
                toc_page_range=arguments.get("toc_page_range"),
                confidence=arguments["confidence"],
                search_strategy_used=arguments["search_strategy_used"],
                reasoning=arguments["reasoning"]
            )
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def get_toc_label_pages(self) -> str:
        """
        Get pages where labels detected TABLE_OF_CONTENTS blocks.

        Returns:
            JSON with pages list: {"found": true, "pages": [4, 5], "method": "block_classification"}
        """
        try:
            labels_stage = self.storage.stage('labels')
            label_page_paths = labels_stage.list_output_pages()

            toc_pages = []
            for page_path in label_page_paths:
                page_num = int(page_path.stem.split('_')[1])
                label_data = labels_stage.load_page(page_num)

                # Check for TABLE_OF_CONTENTS blocks (most accurate)
                blocks = label_data.get('blocks', [])
                toc_blocks = [b for b in blocks if b.get('classification') == 'TABLE_OF_CONTENTS']

                if toc_blocks:
                    toc_pages.append(page_num)

            if toc_pages:
                return json.dumps({
                    "found": True,
                    "pages": sorted(toc_pages),
                    "detection_method": "block_classification"
                })
            else:
                return json.dumps({
                    "found": False,
                    "detection_method": "block_classification"
                })

        except Exception as e:
            return json.dumps({"error": f"Failed to check labels: {str(e)}"})

    def add_page_images_to_context(self, page_nums: List[int]) -> str:
        """
        Load page images and add them to agent context.

        The images will be visible in your next LLM call.

        Args:
            page_nums: List of page numbers to load

        Returns:
            JSON confirmation: {"added": [4, 5, 6], "total_images_in_context": 3}
        """
        try:
            source_stage = self.storage.stage('source')
            added_pages = []

            for page_num in page_nums:
                page_image_path = source_stage.output_page(page_num, extension='png')

                if not page_image_path.exists():
                    continue

                # Load and downsample image (avoid 413 Payload Too Large)
                image = Image.open(page_image_path)
                downsampled_image = downsample_for_vision(image, max_payload_kb=800)

                # Add to agent's images context
                self.agent_client.images.append(downsampled_image)
                added_pages.append(page_num)

            return json.dumps({
                "added": added_pages,
                "total_images_in_context": len(self.agent_client.images),
                "message": f"Added {len(added_pages)} images. You can now see pages {added_pages} in this conversation."
            })

        except Exception as e:
            return json.dumps({"error": f"Failed to load images: {str(e)}"})

    def write_toc_result(
        self,
        toc_found: bool,
        toc_page_range: Optional[Dict],
        confidence: float,
        search_strategy_used: str,
        reasoning: str
    ) -> str:
        """
        Write final ToC search result.

        This completes the agent task.

        Args:
            toc_found: Whether ToC was found
            toc_page_range: Dict with start_page and end_page (or None)
            confidence: Confidence score 0.0-1.0
            search_strategy_used: Strategy used
            reasoning: Explanation

        Returns:
            JSON confirmation
        """
        try:
            # Convert dict to PageRange if provided
            page_range = None
            if toc_page_range:
                page_range = PageRange(
                    start_page=toc_page_range["start_page"],
                    end_page=toc_page_range["end_page"]
                )

            # Create result
            self._pending_result = TocFinderResult(
                toc_found=toc_found,
                toc_page_range=page_range,
                confidence=confidence,
                search_strategy_used=search_strategy_used,
                reasoning=reasoning
            )

            return json.dumps({
                "success": True,
                "message": "ToC search complete",
                "result": {
                    "toc_found": toc_found,
                    "toc_page_range": f"{page_range.start_page}-{page_range.end_page}" if page_range else None,
                    "confidence": confidence
                }
            })

        except Exception as e:
            return json.dumps({"error": f"Failed to write result: {str(e)}"})

    def get_pending_result(self) -> Optional[TocFinderResult]:
        """Get the pending result (set by write_toc_result)."""
        return self._pending_result
