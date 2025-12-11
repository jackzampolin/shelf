"""Tools for the gap investigator agent."""

import json
from typing import Dict, List, Optional

from infra.pipeline.storage.book_storage import BookStorage
from infra.pipeline.logger import PipelineLogger
from infra.llm.agent import AgentTools

from ...schemas import PageGap, EnrichedToCEntry, LinkedToCEntry
from pipeline.link_toc.find_entries.agent.tools import grep_text, get_page_ocr


class GapInvestigatorTools(AgentTools):
    """Tools for investigating and fixing page coverage gaps."""

    def __init__(
        self,
        storage: BookStorage,
        gap: PageGap,
        enriched_entries: List[EnrichedToCEntry],
        original_toc_entries: List[LinkedToCEntry],
        body_range: tuple,
        logger: Optional[PipelineLogger] = None
    ):
        self.storage = storage
        self.gap = gap
        self.enriched_entries = enriched_entries
        self.original_toc_entries = original_toc_entries
        self.body_range = body_range
        self.logger = logger

        self._pending_result: Optional[Dict] = None
        self._current_images: Optional[List] = None
        self._pages_viewed: List[int] = []

    def get_tools(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_gap_context",
                    "description": "Get detailed context about the gap: entries before/after, ToC entries in range, and pattern info.",
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
                    "name": "get_page_ocr",
                    "description": "Get OCR text for a specific page in the gap range.",
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
                    "description": "View the scanned page image to see actual headings.",
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
                    "name": "get_all_toc_entries",
                    "description": "Get all original ToC entries for cross-reference.",
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
                    "description": "Search for text pattern in the book. Returns pages with matches.",
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
                    "name": "add_entry",
                    "description": "Add a missing entry to fix the gap.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Entry title"},
                            "scan_page": {"type": "integer", "description": "Scan page where entry starts"},
                            "level": {"type": "integer", "description": "Hierarchy level (1=part, 2=chapter, etc.)"},
                            "entry_number": {"type": ["string", "null"], "description": "Entry number if applicable (e.g., '16', 'III')"},
                            "reasoning": {"type": "string", "description": "Why you're adding this entry"}
                        },
                        "required": ["title", "scan_page", "level", "reasoning"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "correct_entry",
                    "description": "Correct an existing entry's page number or other field.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "entry_index": {"type": "integer", "description": "Index of entry to correct"},
                            "field": {"type": "string", "enum": ["scan_page", "title", "level"], "description": "Field to correct"},
                            "new_value": {"type": ["string", "integer"], "description": "New value for the field"},
                            "reasoning": {"type": "string", "description": "Why you're making this correction"}
                        },
                        "required": ["entry_index", "field", "new_value", "reasoning"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "no_fix_needed",
                    "description": "Report that this gap doesn't need a fix (e.g., it's expected back matter).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reasoning": {"type": "string", "description": "Why no fix is needed"}
                        },
                        "required": ["reasoning"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "flag_for_review",
                    "description": "Flag this gap for manual review when you're unsure.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "issue_description": {"type": "string", "description": "Describe what you found and why you're unsure"}
                        },
                        "required": ["issue_description"]
                    }
                }
            }
        ]

    def execute_tool(self, tool_name: str, tool_input: Dict) -> str:
        if tool_name == "get_gap_context":
            return self._get_gap_context()
        elif tool_name == "get_page_ocr":
            return self._get_page_ocr(tool_input["page_num"])
        elif tool_name == "view_page_image":
            return self._view_page_image(tool_input["page_num"])
        elif tool_name == "get_all_toc_entries":
            return self._get_all_toc_entries()
        elif tool_name == "grep_text":
            return self._grep_text(tool_input["query"])
        elif tool_name == "add_entry":
            return self._add_entry(tool_input)
        elif tool_name == "correct_entry":
            return self._correct_entry(tool_input)
        elif tool_name == "no_fix_needed":
            return self._no_fix_needed(tool_input["reasoning"])
        elif tool_name == "flag_for_review":
            return self._flag_for_review(tool_input["issue_description"])
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    def _get_gap_context(self) -> str:
        """Get detailed context about the gap."""
        # Find entries around the gap
        sorted_entries = sorted(self.enriched_entries, key=lambda e: e.scan_page)

        entry_before = None
        entry_after = None
        for i, entry in enumerate(sorted_entries):
            if entry.scan_page < self.gap.start_page:
                entry_before = entry
            elif entry.scan_page > self.gap.end_page and entry_after is None:
                entry_after = entry

        # Find original ToC entries in the gap range
        toc_in_range = [
            {"title": e.title, "scan_page": e.scan_page, "level": e.level, "entry_number": e.entry_number}
            for e in self.original_toc_entries
            if e.scan_page and self.gap.start_page <= e.scan_page <= self.gap.end_page
        ]

        context = {
            "gap": {
                "start_page": self.gap.start_page,
                "end_page": self.gap.end_page,
                "size": self.gap.size,
            },
            "body_range": self.body_range,
            "entry_before": {
                "title": entry_before.title if entry_before else None,
                "scan_page": entry_before.scan_page if entry_before else None,
                "level": entry_before.level if entry_before else None,
                "entry_number": entry_before.entry_number if entry_before else None,
            } if entry_before else None,
            "entry_after": {
                "title": entry_after.title if entry_after else None,
                "scan_page": entry_after.scan_page if entry_after else None,
                "level": entry_after.level if entry_after else None,
                "entry_number": entry_after.entry_number if entry_after else None,
            } if entry_after else None,
            "original_toc_entries_in_range": toc_in_range,
            "hint": self._generate_hint(entry_before, entry_after, toc_in_range),
        }

        return json.dumps(context, indent=2)

    def _generate_hint(self, entry_before, entry_after, toc_in_range) -> str:
        """Generate a hint about what might be wrong."""
        hints = []

        # Check if there's a ToC entry that should be in this range
        if toc_in_range:
            titles = [e["title"] for e in toc_in_range]
            hints.append(f"Original ToC has entries here: {titles}. These may have wrong page numbers.")

        # Check for sequential gap (e.g., Chapter 15 -> Chapter 17)
        if entry_before and entry_after:
            before_num = entry_before.entry_number
            after_num = entry_after.entry_number
            if before_num and after_num:
                try:
                    b = int(before_num)
                    a = int(after_num)
                    if a - b > 1:
                        missing = [str(i) for i in range(b + 1, a)]
                        hints.append(f"Sequential gap detected: entries {', '.join(missing)} are missing between {before_num} and {after_num}.")
                except ValueError:
                    pass

        if not hints:
            hints.append("Check page images to see if there's a chapter heading that OCR missed.")

        return " ".join(hints)

    def _get_page_ocr(self, page_num: int) -> str:
        """Get OCR text for a page."""
        # Allow some buffer around the gap
        buffer = 5
        if page_num < self.gap.start_page - buffer or page_num > self.gap.end_page + buffer:
            return json.dumps({"error": f"Page {page_num} is outside gap range ({self.gap.start_page}-{self.gap.end_page})"})

        ocr_text = get_page_ocr(page_num, self.storage, self.logger)
        return json.dumps({
            "page_num": page_num,
            "ocr_text": ocr_text,
            "char_count": len(ocr_text) if ocr_text else 0,
        }, indent=2)

    def _view_page_image(self, page_num: int) -> str:
        """View page image."""
        buffer = 5
        if page_num < self.gap.start_page - buffer or page_num > self.gap.end_page + buffer:
            return json.dumps({"error": f"Page {page_num} is outside gap range"})

        try:
            self._current_images = [self.storage.source().load_page_image(
                page_num=page_num,
                downsample=True,
                max_payload_kb=1000
            )]
            self._pages_viewed.append(page_num)
            return json.dumps({"success": True, "page": page_num})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _get_all_toc_entries(self) -> str:
        """Get all original ToC entries."""
        entries = [
            {
                "title": e.title,
                "scan_page": e.scan_page,
                "level": e.level,
                "entry_number": e.entry_number,
            }
            for e in self.original_toc_entries
            if e.scan_page  # Only linked entries
        ]
        return json.dumps({"toc_entries": entries, "count": len(entries)}, indent=2)

    def _grep_text(self, query: str) -> str:
        """Search for text in the book."""
        all_results = grep_text(query, self.storage, self.logger)
        # Filter to gap range with buffer
        buffer = 10
        filtered = [
            r for r in all_results
            if self.gap.start_page - buffer <= r["scan_page"] <= self.gap.end_page + buffer
        ]
        return json.dumps({"matches": filtered, "search_range": f"{self.gap.start_page}-{self.gap.end_page}"}, indent=2)

    def _add_entry(self, params: Dict) -> str:
        """Add a missing entry."""
        self._pending_result = {
            "fix_type": "add_entry",
            "fix_details": {
                "title": params["title"],
                "scan_page": params["scan_page"],
                "level": params["level"],
                "entry_number": params.get("entry_number"),
            },
            "reasoning": params["reasoning"],
        }
        return json.dumps({"status": "success", "action": "add_entry"})

    def _correct_entry(self, params: Dict) -> str:
        """Correct an existing entry."""
        self._pending_result = {
            "fix_type": "correct_entry",
            "fix_details": {
                "entry_index": params["entry_index"],
                "field": params["field"],
                "new_value": params["new_value"],
            },
            "reasoning": params["reasoning"],
        }
        return json.dumps({"status": "success", "action": "correct_entry"})

    def _no_fix_needed(self, reasoning: str) -> str:
        """Report no fix needed."""
        self._pending_result = {
            "fix_type": "no_fix_needed",
            "fix_details": None,
            "reasoning": reasoning,
        }
        return json.dumps({"status": "success", "action": "no_fix_needed"})

    def _flag_for_review(self, issue_description: str) -> str:
        """Flag for manual review."""
        self._pending_result = {
            "fix_type": "flagged",
            "fix_details": None,
            "reasoning": issue_description,
            "flagged_for_review": True,
        }
        return json.dumps({"status": "success", "action": "flagged_for_review"})

    def is_complete(self) -> bool:
        return self._pending_result is not None

    def get_images(self) -> Optional[List]:
        return self._current_images

    def get_result(self) -> Optional[Dict]:
        return self._pending_result
