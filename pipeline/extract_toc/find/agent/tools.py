import json
from pathlib import Path
from typing import List, Dict, Optional

from pydantic import BaseModel, Field

from infra.pipeline.storage.book_storage import BookStorage
from infra.llm.agent import AgentTools
from ..schemas import PageRange, StructureSummary
from ..tools.grep_report import generate_grep_report, summarize_grep_report


class TocFinderResult(BaseModel):
    toc_found: bool
    toc_page_range: Optional[PageRange] = None
    confidence: float = Field(ge=0.0, le=1.0)
    search_strategy_used: str
    pages_checked: int = 0
    total_cost_usd: float = 0.0
    execution_time_seconds: float = 0.0
    iterations: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_reasoning_tokens: int = 0
    reasoning: str
    structure_notes: Optional[Dict[int, str]] = None
    structure_summary: Optional[StructureSummary] = None


class TocFinderTools(AgentTools):

    def __init__(self, storage: BookStorage):
        self.storage = storage
        self._pending_result: Optional[TocFinderResult] = None
        self._grep_report_cache: Optional[Dict] = None
        self._current_page_num: Optional[int] = None
        self._page_observations: List[Dict[str, str]] = []
        self._current_images: Optional[List] = None

    def get_tools(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_frontmatter_grep_report",
                    "description": "Get keyword search report showing categorized keyword matches in front matter. FREE operation (no LLM cost). Returns categorized_pages (pages grouped by keyword type: toc, structure, front_matter, back_matter) and page_details (which keywords appear on each page). Summary includes clustering analysis.",
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
                    "name": "load_page_image",
                    "description": "Load a SINGLE page image to see it visually. WORKFLOW: Document what you see in the CURRENT page, THEN specify which page to load next. One page at a time - when you load a new page, the previous page is automatically removed from context. This forces you to record findings before moving on. First call doesn't need observations (nothing loaded yet).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "page_num": {
                                "type": "integer",
                                "description": "Page number to load NEXT (e.g., 6)"
                            },
                            "current_page_observations": {
                                "type": "string",
                                "description": "What do you see on the page that's CURRENTLY loaded in context? REQUIRED if a page is already in context. Document: Is it ToC? Part of ToC? Not ToC? What visual markers? Be specific about what you SEE right now before swapping to the next page."
                            }
                        },
                        "required": ["page_num"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "load_ocr_text",
                    "description": "Load OCR text (both Mistral and OLM) for the CURRENTLY loaded page. Use this AFTER load_page_image to see clean text extraction. This helps analyze structure accurately (indentation levels, numbering patterns, entry hierarchy). Only works if a page is currently loaded.",
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
                    "name": "write_toc_result",
                    "description": "Write final ToC search result and complete the task. IMPORTANT: If toc_found=false, set toc_page_range to null (not a dummy range). Your page observations will be automatically compiled into structure_notes. If ToC found, provide structure_summary with global hierarchy analysis.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "toc_found": {
                                "type": "boolean",
                                "description": "Whether ToC was found"
                            },
                            "toc_page_range": {
                                "anyOf": [
                                    {
                                        "type": "object",
                                        "properties": {
                                            "start_page": {"type": "integer", "minimum": 1},
                                            "end_page": {"type": "integer", "minimum": 1}
                                        },
                                        "required": ["start_page", "end_page"]
                                    },
                                    {
                                        "type": "null"
                                    }
                                ],
                                "description": "ToC page range with start_page and end_page (both >= 1), or null if ToC not found"
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
                            },
                            "structure_summary": {
                                "type": "object",
                                "description": "Global structure analysis (REQUIRED if toc_found=true, null otherwise)",
                                "properties": {
                                    "total_levels": {
                                        "type": "integer",
                                        "description": "Total hierarchy levels (1, 2, or 3)",
                                        "minimum": 1,
                                        "maximum": 3
                                    },
                                    "level_patterns": {
                                        "type": "object",
                                        "description": "Visual/structural patterns for each level (keys: '1', '2', '3')",
                                        "additionalProperties": {
                                            "type": "object",
                                            "properties": {
                                                "visual": {"type": "string", "description": "Visual characteristics (indentation, styling)"},
                                                "numbering": {"type": "string", "description": "Numbering scheme (Roman, Arabic, decimal, letters, or null)"},
                                                "has_page_numbers": {"type": "boolean", "description": "Whether entries at this level have page numbers"},
                                                "semantic_type": {"type": "string", "description": "Semantic type: volume, book, part, unit, chapter, section, subsection, act, scene, appendix, or null"}
                                            },
                                            "required": ["visual", "has_page_numbers"]
                                        }
                                    },
                                    "consistency_notes": {
                                        "type": "array",
                                        "description": "Notes about structural consistency or variations",
                                        "items": {"type": "string"}
                                    }
                                },
                                "required": ["total_levels", "level_patterns"]
                            }
                        },
                        "required": ["toc_found", "confidence", "search_strategy_used", "reasoning"]
                    }
                }
            }
        ]

    def execute_tool(self, name: str, arguments: Dict) -> str:
        tool_name = name
        if tool_name == "get_frontmatter_grep_report":
            return self.get_frontmatter_grep_report()
        elif tool_name == "load_page_image":
            return self.load_page_image(
                page_num=arguments["page_num"],
                current_page_observations=arguments.get("current_page_observations")
            )
        elif tool_name == "load_ocr_text":
            return self.load_ocr_text()
        elif tool_name == "write_toc_result":
            return self.write_toc_result(
                toc_found=arguments["toc_found"],
                toc_page_range=arguments.get("toc_page_range"),
                confidence=arguments["confidence"],
                search_strategy_used=arguments["search_strategy_used"],
                reasoning=arguments["reasoning"],
                structure_summary=arguments.get("structure_summary")
            )
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def get_frontmatter_grep_report(self) -> str:
        try:
            if self._grep_report_cache is None:
                self._grep_report_cache = generate_grep_report(self.storage, max_pages=50)
                # Save grep report
                stage_storage = self.storage.stage('extract-toc')
                stage_storage.save_file("grep_report.json", self._grep_report_cache)

            report = self._grep_report_cache
            summary = summarize_grep_report(report)

            return json.dumps({
                "success": True,
                "report": report,
                "summary": summary,
                "message": "Grep report generated. Check 'categorized_pages' for keyword groupings and 'summary' for actionable recommendations."
            }, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Failed to generate grep report: {str(e)}"})

    def load_page_image(self, page_num: int, current_page_observations: Optional[str] = None) -> str:
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

    def load_ocr_text(self) -> str:
        """Load OCR text (both Mistral and OLM) for the currently loaded page."""
        try:
            if self._current_page_num is None:
                return json.dumps({
                    "error": "No page currently loaded. Call load_page_image first."
                })

            page_num = self._current_page_num

            # Load Mistral OCR
            mistral_ocr = None
            try:
                mistral_data = self.storage.stage('ocr-pages').load_page(page_num, subdir="mistral")
                mistral_ocr = mistral_data.get('markdown', '')
            except FileNotFoundError:
                pass

            # Load OLM OCR
            olm_ocr = None
            try:
                olm_data = self.storage.stage('ocr-pages').load_page(page_num, subdir="olm")
                olm_ocr = olm_data.get('text', '') or olm_data.get('markdown', '')
            except FileNotFoundError:
                pass

            if not mistral_ocr and not olm_ocr:
                return json.dumps({
                    "error": f"No OCR data found for page {page_num}. Ensure ocr-pages stage has run."
                })

            response = {
                "success": True,
                "page_num": page_num,
                "message": f"OCR text loaded for page {page_num}"
            }

            if mistral_ocr:
                response["mistral_ocr"] = mistral_ocr
                response["mistral_char_count"] = len(mistral_ocr)

            if olm_ocr:
                response["olm_ocr"] = olm_ocr
                response["olm_char_count"] = len(olm_ocr)

            return json.dumps(response, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Failed to load OCR text: {str(e)}"})

    def write_toc_result(
        self,
        toc_found: bool,
        toc_page_range: Optional[Dict],
        confidence: float,
        search_strategy_used: str,
        reasoning: str,
        structure_summary: Optional[Dict] = None
    ) -> str:
        try:
            structure_notes = None
            if toc_found and self._page_observations:
                structure_notes = {
                    obs['page_num']: obs['observations']
                    for obs in self._page_observations
                }

            page_range = None
            if toc_page_range:
                page_range = PageRange(
                    start_page=toc_page_range["start_page"],
                    end_page=toc_page_range["end_page"]
                )

            # Validate and construct structure_summary if provided
            from ..schemas import StructureSummary, LevelPattern
            structure_summary_obj = None
            if structure_summary:
                try:
                    # Convert level_patterns dict with string keys to proper structure
                    level_patterns_dict = {}
                    for level_key, pattern_data in structure_summary.get("level_patterns", {}).items():
                        level_patterns_dict[int(level_key)] = LevelPattern(**pattern_data)

                    structure_summary_obj = StructureSummary(
                        total_levels=structure_summary["total_levels"],
                        level_patterns=level_patterns_dict,
                        consistency_notes=structure_summary.get("consistency_notes", [])
                    )
                except Exception as e:
                    return json.dumps({
                        "error": f"Invalid structure_summary format: {str(e)}. Please provide total_levels, level_patterns with visual, has_page_numbers, and optional numbering/semantic_type for each level."
                    })

            self._pending_result = TocFinderResult(
                toc_found=toc_found,
                toc_page_range=page_range,
                confidence=confidence,
                search_strategy_used=search_strategy_used,
                reasoning=reasoning,
                structure_notes=structure_notes,
                structure_summary=structure_summary_obj
            )

            result_summary = {
                "toc_found": toc_found,
                "toc_page_range": f"{page_range.start_page}-{page_range.end_page}" if page_range else None,
                "confidence": confidence
            }

            if structure_notes:
                result_summary["structure_notes_compiled"] = f"from {len(self._page_observations)} page observations"

            if structure_summary_obj:
                result_summary["structure_summary_compiled"] = f"{structure_summary_obj.total_levels} levels analyzed"

            return json.dumps({
                "success": True,
                "message": "ToC search complete",
                "result": result_summary
            })

        except Exception as e:
            return json.dumps({"error": f"Failed to write result: {str(e)}"})

    def get_pending_result(self) -> Optional[TocFinderResult]:
        return self._pending_result

    def is_complete(self) -> bool:
        return self._pending_result is not None

    def get_images(self) -> Optional[List]:
        return self._current_images
