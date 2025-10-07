#!/usr/bin/env python3
"""
Agent 4: Targeted fix agent for pages flagged by Agent 3.

This agent:
1. Reads pages from needs_review/
2. Takes Agent 3's specific feedback about missed corrections
3. Makes ONLY the targeted fixes Agent 3 identified
4. Outputs to agent4_final/ directory
5. Creates verification report

Strategy: Highly focused, surgical corrections based on explicit feedback.
"""

import os
import sys
import json
import threading
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from llm_client import LLMClient
from logger import create_logger
from checkpoint import CheckpointManager


class Agent4TargetedFix:
    """Agent 4: Make targeted fixes based on Agent 3 feedback."""

    def __init__(self, book_slug: str, max_workers: int = 15, enable_checkpoints: bool = True):
        self.book_slug = book_slug
        self.base_dir = Path.home() / "Documents" / "book_scans" / book_slug
        self.max_workers = max_workers
        self.enable_checkpoints = enable_checkpoints

        # Directories
        self.needs_review_dir = self.base_dir / "needs_review"
        self.corrected_dir = self.base_dir / "corrected"

        # Initialize logger
        logs_dir = self.base_dir / "logs"
        logs_dir.mkdir(exist_ok=True)
        self.logger = create_logger(book_slug, "fix", log_dir=logs_dir)

        # Initialize checkpoint manager
        if self.enable_checkpoints:
            self.checkpoint = CheckpointManager(
                scan_id=book_slug,
                stage="fix",
                storage_root=self.base_dir.parent,
                output_dir="corrected"
            )
        else:
            self.checkpoint = None

        # Load API key
        load_dotenv()

        self.model = "anthropic/claude-3.5-sonnet"

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Stats (thread-safe)
        self.stats_lock = threading.Lock()
        self.stats = {
            "pages_processed": 0,
            "pages_fixed": 0,
            "pages_failed": 0,
            "total_cost_usd": 0.0
        }

    def call_llm(self, system_prompt: str, user_prompt: str, temperature=0.0):
        """Make API call to OpenRouter with automatic retries."""
        # Use unified LLMClient (has built-in retry logic)
        response, usage, cost = self.llm_client.simple_call(
            self.model,
            system_prompt,
            user_prompt,
            temperature=temperature,
            timeout=120,
            max_retries=3
        )

        # Track cost
        with self.stats_lock:
            self.stats['total_cost_usd'] += cost

        return response, usage

    def agent4_targeted_fix(self, page_num: int, page_data: dict, corrected_text: str,
                            agent3_feedback: str, missed_corrections: list):
        """
        Agent 4: Make targeted fixes based on Agent 3's explicit feedback.

        This agent does NOT re-analyze the entire page. It ONLY fixes the
        specific issues that Agent 3 identified as missed.
        """
        self.logger.info("Applying targeted fixes", page=page_num, agent="agent4", missed_count=len(missed_corrections))

        system_prompt = """You are Agent 4, a precision correction specialist.

<task>
Fix ONLY the specific errors that Agent 3 identified as "missed" or "incorrectly applied".
</task>

<critical_rules>
1. Make ONLY the corrections explicitly mentioned in Agent 3's structured feedback
2. Do NOT re-analyze the text for new errors
3. Do NOT modify anything except the specific missed corrections
4. Preserve ALL existing [CORRECTED:id] markers
5. Add new corrections with format [FIXED:A4-id]
</critical_rules>

<output_format>
Return the complete corrected text with targeted fixes applied.
Your response must begin with the first word of the text.
</output_format>

<critical>
NO preambles or explanations.
NO JSON or code block wrappers.
Just return the corrected text starting with the first word.
</critical>"""

        # Format corrections as structured list
        corrections_list = []
        for i, corr in enumerate(missed_corrections, 1):
            if isinstance(corr, dict):
                # Check if this is an incorrectly applied correction (has 'was_changed_to')
                if 'was_changed_to' in corr:
                    corrections_list.append(
                        f"{i}. Revert '{corr.get('was_changed_to', '')}' back to '{corr.get('should_be', '')}' "
                        f"({corr.get('reason', 'incorrect change')})"
                    )
                else:
                    # Missed correction (has 'original_text')
                    corrections_list.append(
                        f"{i}. Change '{corr.get('original_text', '')}' to '{corr.get('should_be', '')}' "
                        f"({corr.get('location', 'unknown location')})"
                    )
            else:
                # Fallback for string corrections (backward compatibility)
                corrections_list.append(f"{i}. {corr}")

        user_prompt = f"""<page_number>{page_num}</page_number>

<missed_corrections>
{chr(10).join(corrections_list)}
</missed_corrections>

<current_text>
{corrected_text}
</current_text>

<instructions>
Apply ONLY the corrections listed in <missed_corrections>.
Mark new fixes with [FIXED:A4-id].
Return the complete corrected text.
</instructions>"""

        try:
            response, usage = self.call_llm(system_prompt, user_prompt, temperature=0.0)

            # Update the page_data with Agent 4's fixes
            if 'llm_processing' not in page_data:
                page_data['llm_processing'] = {}

            page_data['llm_processing']['agent4_fixes'] = {
                'timestamp': datetime.now().isoformat(),
                'missed_corrections': missed_corrections,
                'fixed_text': response,
                'agent3_feedback': agent3_feedback
            }

            # Apply fixes to regions (same as correction stage does)
            page_data = self.apply_fixes_to_regions(page_data, response, missed_corrections)

            # Save updated JSON back to corrected directory (overwrite)
            output_file = self.corrected_dir / f"page_{page_num:04d}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(page_data, f, indent=2, default=str)

            self.logger.info(f"Applied {len(missed_corrections)} targeted fixes", page=page_num, fixes_applied=len(missed_corrections))
            return response

        except Exception as e:
            self.logger.error("Agent 4 error", page=page_num, error=str(e))
            import traceback
            traceback.print_exc()

            # On error, save the Agent 2 version unchanged
            if 'llm_processing' not in page_data:
                page_data['llm_processing'] = {}

            page_data['llm_processing']['agent4_fixes'] = {
                'timestamp': datetime.now().isoformat(),
                'error': str(e),
                'status': 'failed'
            }

            output_file = self.corrected_dir / f"page_{page_num:04d}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(page_data, f, indent=2, default=str)

            return corrected_text

    def apply_fixes_to_regions(self, page_data, fixed_text, missed_corrections):
        """
        Apply Agent 4's fixes back to regions by parsing [FIXED:A4-id] markers.

        This maintains the same architecture as the correction stage - fixes are
        applied to individual regions so structure stage can extract clean body text.
        """
        import re

        regions = page_data.get('regions', [])
        if not regions or not missed_corrections:
            return page_data

        # Parse [FIXED:A4-id] markers from fixed_text
        # Similar to correction stage, but looking for [FIXED:A4-X] instead of [CORRECTED:X]
        marker_pattern = r'\[FIXED:A4-(\d+)\]'
        marker_positions = [(m.start(), int(m.group(1))) for m in re.finditer(marker_pattern, fixed_text)]

        # Build map of what each fix changed
        fixes_map = {}  # correction_id -> {original, fixed}

        for i, correction in enumerate(missed_corrections):
            correction_id = i + 1
            original = correction.get('original_text', '')
            should_be = correction.get('should_be', '')

            if original and should_be:
                fixes_map[correction_id] = {
                    'original': original,
                    'fixed': should_be
                }

        # Apply fixes to regions
        for region in regions:
            if region.get('type') not in ['header', 'body', 'caption', 'footnote']:
                continue

            region_text = region.get('text', '')
            updated_text = region_text

            # Apply each fix that appears in this region
            for fix_id, fix_data in fixes_map.items():
                original = fix_data['original']
                fixed = fix_data['fixed']

                # Check if this error's original text appears in this region
                if original in updated_text:
                    # Apply fix with marker
                    updated_text = updated_text.replace(
                        original,
                        f"{fixed}[FIXED:A4-{fix_id}]",
                        1  # Only first occurrence
                    )

            # Update region if fixes were applied
            if updated_text != region_text:
                region['text'] = updated_text
                region['fixed'] = True  # Mark that Agent 4 updated this region

        return page_data

    def parse_agent3_feedback(self, review_data: dict):
        """
        Extract missed corrections from Agent 3's structured feedback.

        Agent 3 now returns structured arrays in verification JSON:
        - missed_corrections: Array of {error_id, original_text, should_be, location}
        - incorrectly_applied: Array of {error_id, was_changed_to, should_be, reason}
        """
        verification = review_data.get("llm_processing", {}).get("verification", {})

        # Check if Agent 3 returned structured arrays (new format)
        has_structured_data = ("missed_corrections" in verification or
                              "incorrectly_applied" in verification)

        if has_structured_data:
            # Extract structured corrections from Agent 3 (new format)
            missed_corrections = verification.get("missed_corrections", [])
            incorrectly_applied = verification.get("incorrectly_applied", [])

            # Combine both types into a single list for Agent 4
            all_corrections = []

            # Add missed corrections
            for corr in missed_corrections:
                all_corrections.append(corr)

            # Add incorrectly applied corrections (need to revert)
            for corr in incorrectly_applied:
                all_corrections.append(corr)

            return all_corrections
        else:
            # Fallback: Use review_reason (old format, backward compatibility)
            review_reason = verification.get("review_reason", "")
            if review_reason:
                # Create a simple correction instruction from review_reason
                return [{
                    "original_text": "unknown",
                    "should_be": "unknown",
                    "location": "unknown",
                    "fallback_instruction": f"Review and fix based on: {review_reason[:200]}"
                }]
            else:
                # No corrections needed
                return []

    def process_flagged_page(self, review_file: Path) -> float:
        """
        Process a single flagged page.

        Returns:
            float: Cost in USD for processing this page
        """
        with open(review_file) as f:
            review_data = json.load(f)

        page_num = review_data.get("page_number")
        self.logger.info(f"Processing flagged page {page_num}", page=page_num)

        # Track cost for this specific page
        cost_before = self.stats['total_cost_usd']

        # Load corrected page from flat directory
        corrected_file = self.corrected_dir / f"page_{page_num:04d}.json"
        if corrected_file.exists():
            with open(corrected_file, 'r', encoding='utf-8') as f:
                corrected_data = json.load(f)
        else:
            corrected_data = None

        if not corrected_data:
            self.logger.error("Corrected JSON file not found", page=page_num)
            with self.stats_lock:
                self.stats['pages_failed'] += 1
            return 0.0  # No cost for missing files

        # Checkpoint: Check if this page was already processed by Agent 4
        llm_processing = corrected_data.get('llm_processing', {})
        if 'agent4_fixes' in llm_processing:
            self.logger.info("Already processed (checkpoint found), skipping", page=page_num)
            with self.stats_lock:
                self.stats['pages_processed'] += 1
                self.stats['pages_fixed'] += 1
            return 0.0  # No cost for skipped pages

        # Extract corrected text from llm_processing section
        corrected_text = llm_processing.get('corrected_text', '')

        if not corrected_text:
            self.logger.error("No corrected_text in JSON", page=page_num)
            with self.stats_lock:
                self.stats['pages_failed'] += 1
            return 0.0  # No cost for failed pages

        # Get Agent 3's feedback from the structured JSON
        llm_processing = review_data.get("llm_processing", {})
        verification = llm_processing.get("verification", {})
        agent3_feedback = verification.get("review_reason", "")
        confidence = verification.get("confidence_score", 0.0)

        self.logger.info(f"Agent 3 feedback", page=page_num, original_confidence=confidence, feedback_preview=agent3_feedback[:100])

        # Parse missed corrections
        missed_corrections = self.parse_agent3_feedback(review_data)
        self.logger.info(f"Identified {len(missed_corrections)} missed corrections", page=page_num, missed_count=len(missed_corrections))

        # Apply targeted fixes (pass corrected_data so we can update the full JSON)
        # Metadata is stored in the JSON's llm_processing.agent4_fixes section
        fixed_text = self.agent4_targeted_fix(
            page_num,
            corrected_data,  # Pass the full page data structure
            corrected_text,
            agent3_feedback,
            missed_corrections
        )

        with self.stats_lock:
            self.stats['pages_processed'] += 1
            self.stats['pages_fixed'] += 1
            # Calculate cost for this page
            page_cost = self.stats['total_cost_usd'] - cost_before

        return page_cost

    def process_all_flagged(self, resume: bool = False):
        """Process all flagged pages."""
        # Get all flagged pages
        flagged_files = sorted(self.needs_review_dir.glob("page_*.json"))

        # Extract page numbers and filter with checkpoint if resuming
        flagged_pages = []
        for f in flagged_files:
            # Extract page number from filename
            import re
            match = re.search(r'page_(\d+)\.json', f.name)
            if match:
                page_num = int(match.group(1))
                # Skip if checkpoint says already fixed
                if resume and self.checkpoint and self.checkpoint.validate_page_output(page_num):
                    continue
                flagged_pages.append((page_num, f))

        if not resume and self.checkpoint:
            self.checkpoint.reset()

        if len(flagged_pages) == 0:
            self.logger.info("All flagged pages already fixed")
            print("✅ All flagged pages already fixed!")
            return

        skipped = len(flagged_files) - len(flagged_pages)
        if skipped > 0:
            self.logger.info(f"Resuming: {skipped} pages already fixed", skipped=skipped, remaining=len(flagged_pages))
            print(f"✅ Resuming: {skipped} pages already fixed")

        self.logger.start_stage(
            flagged_pages=len(flagged_pages),
            max_workers=self.max_workers,
            model=self.model,
            resume=resume
        )

        # Also print for compatibility
        print("=" * 70)
        print("🔧 Agent 4: Targeted Fixes")
        print(f"   Book: {self.book_slug}")
        print("=" * 70)
        print(f"\n📋 Found {len(flagged_files)} pages flagged for review")
        print(f"⚙️  Processing with {self.max_workers} parallel workers\n")

        # Process pages in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_page = {
                executor.submit(self.process_flagged_page, review_file): (page_num, review_file)
                for page_num, review_file in flagged_pages
            }

            # Process completions as they finish
            completed = 0
            for future in as_completed(future_to_page):
                page_num, review_file = future_to_page[future]
                try:
                    page_cost = future.result()  # Get cost from process_flagged_page
                    completed += 1

                    # Mark page as completed in checkpoint
                    if self.checkpoint:
                        self.checkpoint.mark_completed(page_num)

                    self.logger.progress(
                        "Processing flagged pages",
                        current=completed,
                        total=len(flagged_pages),
                        page=page_num
                    )
                except Exception as e:
                    self.logger.error(f"Failed to process page", file=review_file.name, error=str(e))
                    with self.stats_lock:
                        self.stats['pages_failed'] += 1

        # Mark stage complete in checkpoint
        if self.checkpoint:
            self.checkpoint.mark_stage_complete(metadata={
                "pages_processed": self.stats['pages_processed'],
                "pages_fixed": self.stats['pages_fixed'],
                "total_cost_usd": self.stats['total_cost_usd']
            })

        # Log summary
        self.logger.info(
            "Agent 4 processing complete",
            pages_processed=self.stats['pages_processed'],
            pages_fixed=self.stats['pages_fixed'],
            pages_failed=self.stats['pages_failed'],
            total_cost_usd=self.stats['total_cost_usd']
        )

        # Print summary
        print("\n" + "=" * 70)
        print("✅ Agent 4 Processing Complete")
        print("=" * 70)
        print(f"\n📊 Summary:")
        print(f"   Pages processed: {self.stats['pages_processed']}")
        print(f"   Pages fixed: {self.stats['pages_fixed']}")
        print(f"   Pages failed: {self.stats['pages_failed']}")
        print(f"   Total cost: ${self.stats['total_cost_usd']:.4f}")
        print(f"\n📁 Output: {self.corrected_dir} (updated in place)")
        print()


def main():
    if len(sys.argv) != 2:
        print("Usage: python book_agent4_fix.py <book-slug>")
        print("Example: python book_agent4_fix.py The-Accidental-President")
        sys.exit(1)

    book_slug = sys.argv[1]

    agent4 = Agent4TargetedFix(book_slug)
    agent4.process_all_flagged()


if __name__ == "__main__":
    main()