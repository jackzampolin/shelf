"""
Tool implementations for ToC finder agent.
"""

import csv
import json
from pathlib import Path
from typing import List, Dict, Optional
from PIL import Image

from pydantic import BaseModel, Field

from infra.storage.book_storage import BookStorage
from infra.llm.client import LLMClient
from infra.config import Config
from pipeline.build_structure.schemas import PageRange


# Schemas for vision tool outputs
class TocCheckResult(BaseModel):
    """Result from vision-based ToC check."""
    is_toc: bool = Field(..., description="Whether page contains ToC content")
    confidence: float = Field(..., ge=0.0, le=1.0)
    visual_markers: List[str] = Field(
        ...,
        description="Visual cues observed (indentation, dots, page numbers)"
    )
    reasoning: str = Field(..., description="Brief explanation of decision")


class TocFinderResult(BaseModel):
    """Agent's final ToC search result."""
    toc_found: bool
    toc_page_range: Optional[Dict] = None  # {"start_page": int, "end_page": int}
    confidence: float = Field(..., ge=0.0, le=1.0)
    search_strategy_used: str  # e.g., "labels_report", "keyword_search", "vision_scan"
    pages_checked: int
    total_cost_usd: float
    reasoning: str


def extract_text_from_merged(merged_data: dict) -> str:
    """Extract all text from merged page data."""
    text_parts = []
    blocks = merged_data.get("blocks", [])
    for block in blocks:
        paragraphs = block.get("paragraphs", [])
        for para in paragraphs:
            text = para.get("text", "").strip()
            if text:
                text_parts.append(text)
    return " ".join(text_parts)


class TocFinderTools:
    """Tool suite for ToC finder agent."""

    def __init__(self, storage: BookStorage):
        self.storage = storage
        self.llm_client = LLMClient()
        self.total_vision_cost = 0.0
        self.pages_checked_with_vision = 0

        # For write_toc_result
        self._pending_result: Optional[TocFinderResult] = None

    def get_tools(self) -> List[Dict]:
        """Return tool definitions for LLM client."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "check_labels_report",
                    "description": "Check if labels stage already detected ToC pages (fast, free)",
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
                    "name": "get_front_matter_range",
                    "description": "Get front matter page range to constrain search",
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
                    "name": "keyword_search_pages",
                    "description": "Search merged text for ToC keywords in page range (fast, free)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keywords": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Keywords to search for (e.g., ['contents', 'table of contents'])"
                            },
                            "start_page": {
                                "type": "integer",
                                "description": "Start of search range"
                            },
                            "end_page": {
                                "type": "integer",
                                "description": "End of search range"
                            }
                        },
                        "required": ["keywords", "start_page", "end_page"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "vision_check_page",
                    "description": "Use vision model to check if page is ToC (costs ~$0.01)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {
                                "type": "integer",
                                "description": "Page number to check"
                            }
                        },
                        "required": ["page_num"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "expand_toc_range",
                    "description": "Expand bidirectionally from seed ToC page to find full range",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "seed_page": {
                                "type": "integer",
                                "description": "Confirmed ToC page to expand from"
                            }
                        },
                        "required": ["seed_page"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "sample_pages_vision",
                    "description": "Check multiple pages with vision (batch operation, costs ~$0.01 per page)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_nums": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "List of page numbers to check (max 10 to control cost)"
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
                    "description": "Write final ToC search result (terminates agent loop)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "toc_found": {
                                "type": "boolean",
                                "description": "Whether ToC was found"
                            },
                            "toc_page_range": {
                                "type": "object",
                                "description": "ToC page range with start_page and end_page (null if not found)",
                                "properties": {
                                    "start_page": {"type": "integer"},
                                    "end_page": {"type": "integer"}
                                }
                            },
                            "confidence": {
                                "type": "number",
                                "description": "Confidence level 0.0-1.0"
                            },
                            "search_strategy_used": {
                                "type": "string",
                                "description": "Strategy that succeeded (labels_report, keyword_search, vision_scan, not_found)"
                            },
                            "reasoning": {
                                "type": "string",
                                "description": "2-3 sentence explanation of decision"
                            }
                        },
                        "required": ["toc_found", "confidence", "search_strategy_used", "reasoning"]
                    }
                }
            }
        ]

    def check_labels_report(self) -> str:
        """Check if labels stage already detected ToC pages."""
        labels_report = self.storage.stage('labels').output_dir / 'report.csv'

        if not labels_report.exists():
            return json.dumps({
                "found": False,
                "reason": "Labels report not found"
            })

        toc_pages = []
        with open(labels_report) as f:
            for row in csv.DictReader(f):
                if row.get('page_region') == 'toc_area':
                    toc_pages.append(int(row['page_num']))

        if toc_pages:
            return json.dumps({
                "found": True,
                "page_range": {"start_page": min(toc_pages), "end_page": max(toc_pages)},
                "page_count": len(toc_pages)
            })
        else:
            return json.dumps({"found": False})

    def get_front_matter_range(self) -> str:
        """Get front matter range from labels report."""
        labels_report = self.storage.stage('labels').output_dir / 'report.csv'

        if not labels_report.exists():
            return json.dumps({
                "start_page": 1,
                "end_page": 30,
                "source": "default"
            })

        front_matter_pages = []
        body_starts = None

        with open(labels_report) as f:
            for row in csv.DictReader(f):
                page_num = int(row['page_num'])
                region = row.get('page_region', '')

                if region == 'front_matter':
                    front_matter_pages.append(page_num)
                elif region == 'body' and body_starts is None:
                    body_starts = page_num

        if front_matter_pages:
            end = max(front_matter_pages)
            source = "labels_report"
        elif body_starts:
            end = body_starts - 1
            source = "body_boundary"
        else:
            end = 30
            source = "default"

        return json.dumps({
            "start_page": 1,
            "end_page": end,
            "total_pages": end,
            "source": source
        })

    def keyword_search_pages(self, keywords: List[str], start_page: int, end_page: int) -> str:
        """Search merged text for ToC keywords in specified range."""
        matches = []
        merged_stage = self.storage.stage('merged')

        for page_num in range(start_page, end_page + 1):
            try:
                merged_data = merged_stage.load_page(page_num)
                text = extract_text_from_merged(merged_data)

                for keyword in keywords:
                    if keyword.lower() in text.lower():
                        # Extract context around match
                        idx = text.lower().find(keyword.lower())
                        context_start = max(0, idx - 50)
                        context_end = min(len(text), idx + len(keyword) + 50)
                        context = text[context_start:context_end]

                        matches.append({
                            'page_num': page_num,
                            'keyword': keyword,
                            'context': context
                        })
            except Exception:
                continue

        return json.dumps({
            'total_matches': len(matches),
            'matches': matches[:10],  # Limit to top 10
            'page_nums': sorted(list(set(m['page_num'] for m in matches)))
        })

    def vision_check_page(self, page_num: int) -> str:
        """Use vision model to check if page is ToC."""
        from .toc_finder_prompts import TOC_DETECTION_VISION_PROMPT

        try:
            # Load source image
            source_stage = self.storage.stage('source')
            page_image_path = source_stage.output_page(page_num, extension='png')

            if not page_image_path.exists():
                return json.dumps({
                    "error": f"Page {page_num} image not found"
                })

            # Load merged text for context
            merged_data = self.storage.stage('merged').load_page(page_num)
            text = extract_text_from_merged(merged_data)

            # Prepare messages
            messages = [
                {"role": "system", "content": TOC_DETECTION_VISION_PROMPT},
                {"role": "user", "content": f"Page {page_num} text excerpt:\n{text[:500]}..."}
            ]

            # Vision call with expensive model for accuracy
            # Note: OpenRouter doesn't support "strict": True
            response, usage, cost = self.llm_client.call(
                model=Config.vision_model_expensive,
                messages=messages,
                images=[str(page_image_path)],
                temperature=0.0,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "toc_check_result",
                        "schema": TocCheckResult.model_json_schema()
                    }
                }
            )

            # Track cost
            self.total_vision_cost += cost
            self.pages_checked_with_vision += 1

            # Parse result
            result = TocCheckResult.model_validate_json(response)

            return json.dumps({
                'page_num': page_num,
                'is_toc': result.is_toc,
                'confidence': result.confidence,
                'visual_markers': result.visual_markers,
                'reasoning': result.reasoning,
                'cost_usd': cost
            })

        except Exception as e:
            return json.dumps({
                "error": f"Vision check failed for page {page_num}: {str(e)}"
            })

    def expand_toc_range(self, seed_page: int) -> str:
        """Expand bidirectionally from seed page to find full ToC range."""
        metadata = self.storage.load_metadata()
        total_pages = metadata.get('total_pages', 500)

        start = seed_page
        end = seed_page

        # Check backwards (max 5 pages)
        for page_num in range(seed_page - 1, max(1, seed_page - 6), -1):
            result_str = self.vision_check_page(page_num)
            result = json.loads(result_str)

            if 'error' in result:
                break

            if result.get('is_toc') and result.get('confidence', 0) > 0.6:
                start = page_num
            else:
                break

        # Check forwards (max 5 pages)
        for page_num in range(seed_page + 1, min(seed_page + 6, total_pages + 1)):
            result_str = self.vision_check_page(page_num)
            result = json.loads(result_str)

            if 'error' in result:
                break

            if result.get('is_toc') and result.get('confidence', 0) > 0.6:
                end = page_num
            else:
                break

        return json.dumps({
            'seed_page': seed_page,
            'start_page': start,
            'end_page': end,
            'total_pages': end - start + 1,
            'pages_checked': abs(start - seed_page) + abs(end - seed_page)
        })

    def sample_pages_vision(self, page_nums: List[int]) -> str:
        """Check multiple pages with vision model."""
        # Limit to 10 pages to control cost
        page_nums = page_nums[:10]

        results = []
        for page_num in page_nums:
            result_str = self.vision_check_page(page_num)
            result = json.loads(result_str)
            if 'error' not in result:
                results.append(result)

        # Find high-confidence ToC pages
        toc_candidates = [
            r for r in results
            if r.get('is_toc') and r.get('confidence', 0) > 0.7
        ]

        return json.dumps({
            'total_checked': len(results),
            'toc_candidates': toc_candidates,
            'all_results': results
        })

    def write_toc_result(
        self,
        toc_found: bool,
        toc_page_range: Optional[Dict],
        confidence: float,
        search_strategy_used: str,
        reasoning: str
    ) -> str:
        """Write final ToC search result (terminates agent loop)."""
        self._pending_result = TocFinderResult(
            toc_found=toc_found,
            toc_page_range=toc_page_range,
            confidence=confidence,
            search_strategy_used=search_strategy_used,
            pages_checked=self.pages_checked_with_vision,
            total_cost_usd=self.total_vision_cost,
            reasoning=reasoning
        )

        return "✅ ToC search complete. Result written."

    def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool by name with arguments."""
        if tool_name == "check_labels_report":
            return self.check_labels_report()
        elif tool_name == "get_front_matter_range":
            return self.get_front_matter_range()
        elif tool_name == "keyword_search_pages":
            return self.keyword_search_pages(**arguments)
        elif tool_name == "vision_check_page":
            return self.vision_check_page(**arguments)
        elif tool_name == "expand_toc_range":
            return self.expand_toc_range(**arguments)
        elif tool_name == "sample_pages_vision":
            return self.sample_pages_vision(**arguments)
        elif tool_name == "write_toc_result":
            return self.write_toc_result(**arguments)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
