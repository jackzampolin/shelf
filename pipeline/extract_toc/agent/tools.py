"""
Tools for grep-informed ToC finder agent.

Provides grep report + vision verification for efficient ToC discovery.
"""

import json
from pathlib import Path
from typing import List, Dict, Optional
from PIL import Image

from pydantic import BaseModel, Field

from infra.storage.book_storage import BookStorage
from infra.llm.agent_client import AgentClient
from infra.utils.pdf import downsample_for_vision
from ..schemas import PageRange
from ..tools.grep_report import generate_grep_report, summarize_grep_report


class TocFinderResult(BaseModel):
    """Result from ToC finder agent."""
    toc_found: bool
    toc_page_range: Optional[PageRange] = None
    confidence: float = Field(ge=0.0, le=1.0)
    search_strategy_used: str
    pages_checked: int = 0  # Number of pages examined (populated by agent)
    total_cost_usd: float = 0.0  # Total cost (populated by agent)
    reasoning: str


class TocFinderTools:
    """Tool suite for grep-informed ToC finder agent."""

    def __init__(self, storage: BookStorage, agent_client: AgentClient):
        """
        Initialize tools.

        Args:
            storage: BookStorage instance for accessing book data
            agent_client: AgentClient instance (for accessing images list)
        """
        self.storage = storage
        self.agent_client = agent_client
        self._pending_result: Optional[TocFinderResult] = None
        self._grep_report_cache: Optional[Dict] = None

    def get_tools(self) -> List[Dict]:
        """Return tool definitions for LLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_frontmatter_grep_report",
                    "description": "Get keyword search report showing pages with ToC keywords, front matter markers, and structure patterns. FREE operation (no LLM cost). Returns JSON with toc_candidates (pages with ToC keywords), front_matter (preface/intro pages), structure (chapter/part mentions), and back_matter (index/appendix pages).",
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
                    "description": "Load page images to see them visually. REPLACES any previously loaded images (doesn't accumulate). Load 1-2 pages at a time to avoid payload limits. Images are downsampled for efficient transmission.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_nums": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "List of page numbers to load (e.g., [4, 5]). IMPORTANT: Limit to 1-2 pages max to avoid 422/413 errors."
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
                                "description": "Strategy used: grep_report, grep_with_scan, or not_found"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "1-2 sentence explanation of grep hints + what you saw in images"
                            }
                        },
                        "required": ["toc_found", "confidence", "search_strategy_used", "reasoning"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, arguments: Dict) -> str:
        """Execute a tool and return result string."""
        if tool_name == "get_frontmatter_grep_report":
            return self.get_frontmatter_grep_report()
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

    def get_frontmatter_grep_report(self) -> str:
        """
        Get keyword search report for ToC and front matter.

        Returns:
            JSON with grep report + human-readable summary
        """
        try:
            # Generate report (cache it)
            if self._grep_report_cache is None:
                self._grep_report_cache = generate_grep_report(self.storage, max_pages=50)

            report = self._grep_report_cache
            summary = summarize_grep_report(report)

            return json.dumps({
                "success": True,
                "report": report,
                "summary": summary,
                "message": "Grep report generated. Use 'toc_candidates' to find pages with ToC keywords."
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Failed to generate grep report: {str(e)}"})

    def add_page_images_to_context(self, page_nums: List[int]) -> str:
        """
        Load page images and REPLACE current images in context.

        This replaces any previously loaded images. The images will be visible in your next LLM call.

        Args:
            page_nums: List of page numbers to load

        Returns:
            JSON confirmation: {"loaded": [4, 5], "message": "Now viewing 2 pages"}
        """
        try:
            source_stage = self.storage.stage('source')
            loaded_pages = []
            new_images = []

            for page_num in page_nums:
                page_image_path = source_stage.output_page(page_num, extension='png')

                if not page_image_path.exists():
                    continue

                # Load and downsample image (avoid 413 Payload Too Large)
                image = Image.open(page_image_path)
                downsampled_image = downsample_for_vision(image, max_payload_kb=400)

                new_images.append(downsampled_image)
                loaded_pages.append(page_num)

            # REPLACE images (don't accumulate) to avoid 413 Payload Too Large
            self.agent_client.images = new_images

            return json.dumps({
                "loaded": loaded_pages,
                "count": len(loaded_pages),
                "message": f"Now viewing pages {loaded_pages}. Previous images were cleared."
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
