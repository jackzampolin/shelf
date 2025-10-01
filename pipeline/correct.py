#!/usr/bin/env python3
"""
LLM Text Cleanup Pipeline - Structured JSON Processing
Processes structured OCR JSON through error detection, correction, and verification
with parallel processing and rate limiting
"""

import os
import sys
import json
import copy
import time
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

# Load environment variables
load_dotenv()


class RateLimiter:
    """Rate limiter for API calls"""
    def __init__(self, calls_per_minute=15):
        self.calls_per_minute = calls_per_minute
        self.min_interval = 60.0 / calls_per_minute
        self.last_call = 0
        self.lock = threading.Lock()

    def wait(self):
        """Wait if necessary to respect rate limit"""
        with self.lock:
            now = time.time()
            time_since_last = now - self.last_call
            if time_since_last < self.min_interval:
                sleep_time = self.min_interval - time_since_last
                time.sleep(sleep_time)
            self.last_call = time.time()


class StructuredPageCorrector:
    """
    Process structured OCR JSON through 3-agent LLM pipeline:
    - Agent 1: Detect OCR errors in body/caption regions
    - Agent 2: Apply corrections to those regions
    - Agent 3: Verify corrections
    """

    def __init__(self, book_title, storage_root=None, model="openai/gpt-4o-mini",
                 max_workers=30, calls_per_minute=150, enable_checkpoints=True):
        self.book_title = book_title
        self.storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
        self.book_dir = self.storage_root / book_title
        self.model = model
        self.max_workers = max_workers
        self.rate_limiter = RateLimiter(calls_per_minute)
        self.enable_checkpoints = enable_checkpoints

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Directories
        self.ocr_dir = self.book_dir / "ocr"
        self.corrected_dir = self.book_dir / "corrected"
        self.needs_review_dir = self.book_dir / "needs_review"
        self.logs_dir = self.book_dir / "logs"
        self.debug_dir = self.logs_dir / "debug"

        for dir_path in [self.corrected_dir, self.needs_review_dir, self.logs_dir, self.debug_dir]:
            dir_path.mkdir(exist_ok=True)

        # Initialize unified logger
        self.logger = create_logger(book_title, "correction", log_dir=self.logs_dir)

        # Initialize checkpoint manager
        if self.enable_checkpoints:
            self.checkpoint = CheckpointManager(
                scan_id=book_title,
                stage="correction",
                storage_root=self.storage_root,
                output_dir="corrected"
            )
        else:
            self.checkpoint = None

        # Thread-safe stats tracking
        self.stats = {
            "total_pages": 0,
            "processed_pages": 0,
            "skipped_pages": 0,  # No correctable content
            "total_errors_found": 0,
            "corrections_applied": 0,
            "pages_needing_review": 0,
            "total_cost_usd": 0.0
        }
        self.stats_lock = threading.Lock()
        self.progress_lock = threading.Lock()

    def extract_json(self, text, debug_label=""):
        """
        Extract JSON from LLM response with robust error handling.
        Uses multiple fallback strategies to handle common JSON issues.
        """
        import re

        original_text = text
        text = text.strip()

        # Remove markdown code blocks
        if '```json' in text or '```' in text:
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1).strip()
            else:
                text = text.replace('```json', '').replace('```', '').strip()

        # Find the first { and last } for JSON object
        first_brace = text.find('{')
        last_brace = text.rfind('}')

        if first_brace != -1 and last_brace != -1:
            text = text[first_brace:last_brace + 1]

        # Strategy 1: Try to parse as-is
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass  # Try fallback strategies

        # Strategy 2: Fix common JSON syntax errors
        fixed_text = text

        # Fix trailing commas before closing brackets
        fixed_text = re.sub(r',(\s*[}\]])', r'\1', fixed_text)

        # Fix missing commas between objects in arrays
        fixed_text = re.sub(r'}\s*{', '},{', fixed_text)

        # Fix missing commas between array elements
        fixed_text = re.sub(r'"\s*\n\s*"', '",\n"', fixed_text)

        last_error = None
        try:
            json.loads(fixed_text)
            return fixed_text
        except json.JSONDecodeError as e:
            # Capture error details before leaving except block
            last_error = {"msg": str(e), "lineno": e.lineno, "colno": e.colno}

        # Save debug info before raising
        if debug_label and last_error:
            debug_file = self.debug_dir / f"{debug_label}_json_error.txt"
            with open(debug_file, 'w', encoding='utf-8') as f:
                f.write(f"JSON Parse Error: {last_error['msg']}\n")
                f.write(f"Error at line {last_error['lineno']}, column {last_error['colno']}\n\n")
                f.write("=== ORIGINAL RESPONSE ===\n")
                f.write(original_text)
                f.write("\n\n=== EXTRACTED JSON ===\n")
                f.write(text)
                f.write("\n\n=== AFTER REGEX FIXES ===\n")
                f.write(fixed_text)

        raise json.JSONDecodeError(f"Could not parse JSON after all strategies", fixed_text, 0)

    def call_llm(self, system_prompt, user_prompt, temperature=0.1):
        """Make API call to OpenRouter with rate limiting"""
        self.rate_limiter.wait()

        # Use unified LLMClient
        response, usage, cost = self.llm_client.simple_call(
            self.model,
            system_prompt,
            user_prompt,
            temperature=temperature,
            timeout=60
        )

        # Track cost
        with self.stats_lock:
            self.stats['total_cost_usd'] += cost

        return response, usage

    def load_page_json(self, page_num):
        """Load structured JSON for a page"""
        # Find the page file across all batches
        # Load page from flat ocr/ directory
        page_file = self.ocr_dir / f"page_{page_num:04d}.json"
        if page_file.exists():
            with open(page_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def filter_correctable_regions(self, page_data):
        """
        Filter regions that need correction: headers, body, and captions.

        Note: We include headers because OCR sometimes misclassifies large text
        blocks as "header" when they're actually body text (especially on pages
        with chapter endings or photo captions that start at the top).

        Skip: footers, images
        """
        return [
            r for r in page_data.get('regions', [])
            if r['type'] in ['header', 'body', 'caption']
        ]

    def build_page_text(self, page_data, regions_subset=None):
        """
        Build text from page regions in reading order
        If regions_subset provided, only include those regions
        """
        regions = regions_subset if regions_subset else page_data.get('regions', [])
        sorted_regions = sorted(regions, key=lambda r: r.get('reading_order', 0))

        text_parts = []
        for region in sorted_regions:
            if region['type'] != 'image' and 'text' in region:
                text_parts.append(region['text'])

        return '\n\n'.join(text_parts)

    def get_page_context(self, page_num, total_pages):
        """
        Get 3-page context for body regions only
        Returns: (prev_text, current_page_data, next_text)
        """
        # Load current page (full data)
        current_data = self.load_page_json(page_num)
        if not current_data:
            return None, None, None

        # Load adjacent pages (text only from body regions)
        prev_text = None
        if page_num > 1:
            prev_data = self.load_page_json(page_num - 1)
            if prev_data:
                prev_body = [r for r in prev_data['regions'] if r['type'] == 'body']
                if prev_body:
                    prev_text = self.build_page_text(prev_data, prev_body)[-500:]  # Last 500 chars

        next_text = None
        if page_num < total_pages:
            next_data = self.load_page_json(page_num + 1)
            if next_data:
                next_body = [r for r in next_data['regions'] if r['type'] == 'body']
                if next_body:
                    next_text = self.build_page_text(next_data, next_body)[:500]  # First 500 chars

        return prev_text, current_data, next_text

    def agent1_detect_errors(self, page_num, prev_text, page_data, next_text, max_retries=2):
        """Agent 1: Detect OCR errors in body/caption regions with retry logic"""

        correctable_regions = self.filter_correctable_regions(page_data)
        if not correctable_regions:
            return {"page_number": page_num, "total_errors_found": 0, "errors": []}

        # Build target text from correctable regions only
        target_text = self.build_page_text(page_data, correctable_regions)

        system_prompt = """You are an OCR error detection specialist. Your job is to identify potential OCR errors in scanned book text.

RULES:
1. DO NOT fix or correct anything
2. ONLY identify and catalog potential errors
3. Focus ONLY on the specified target page text
4. Use adjacent pages for context but don't report errors from them
5. Report errors with high confidence (>0.7) only

ERROR TYPES TO DETECT:
- Character substitutions (rn→m, l→1, O→0, vv→w)
- Spacing errors (word run-together, extra spaces)
- Hyphenated line breaks that should be joined (e.g., "presi-\\ndent")
- OCR artifacts (|||, ___, etc. that aren't real text)
- Obvious typos from OCR confusion

OUTPUT FORMAT:
Return ONLY valid JSON. Do NOT include:
- Markdown code blocks (```json)
- Explanatory text before or after
- Commentary or analysis
Start your response with the opening brace {

CORRECT OUTPUT:
{"page_number": 1, "total_errors_found": 2, "errors": [...]}

WRONG OUTPUT:
Here's my analysis of page 1:
```json
{"page_number": 1, ...}
```

WRONG OUTPUT:
I found 2 errors. {"page_number": 1, ...}

JSON Structure:
{
  "page_number": N,
  "total_errors_found": X,
  "errors": [
    {
      "error_id": 1,
      "location": "paragraph 2",
      "original_text": "tbe",
      "error_type": "character_substitution",
      "confidence": 0.95,
      "suggested_correction": "the",
      "context_before": "walked into ",
      "context_after": " room"
    }
  ]
}"""

        # Build context
        context_parts = []
        if prev_text:
            context_parts.append(f"PREVIOUS PAGE (context only):\n...{prev_text}\n")

        context_parts.append(f"PAGE {page_num} (TARGET - ANALYZE THIS ONLY):\n{target_text}\n")

        if next_text:
            context_parts.append(f"NEXT PAGE (context only):\n{next_text}...")

        user_prompt = f"""Analyze PAGE {page_num} body text ONLY for OCR errors.

Use adjacent pages for sentence context, but ONLY report errors from page {page_num}.

{chr(10).join(context_parts)}

Return JSON error catalog for page {page_num} only."""

        # Retry logic for Agent 1
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response, usage = self.call_llm(system_prompt, user_prompt, temperature=0.1)
                json_text = self.extract_json(response, debug_label=f"page_{page_num:04d}_agent1")
                error_catalog = json.loads(json_text)
                error_catalog['processing_timestamp'] = datetime.now().isoformat()

                errors_found = error_catalog.get('total_errors_found', 0)
                with self.stats_lock:
                    self.stats['total_errors_found'] += errors_found

                # Success - log retry if it wasn't first attempt
                if attempt > 0:
                    self.logger.info(f"Agent 1 succeeded on retry {attempt}", page=page_num, agent="agent1", retry=attempt)

                return error_catalog

            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    self.logger.warning(f"Agent 1 retry {attempt + 1}/{max_retries}", page=page_num, agent="agent1", error=str(e), retry=attempt + 1)
                    time.sleep(0.5 * (attempt + 1))  # Brief exponential backoff
                else:
                    self.logger.error(f"Agent 1 failed after {max_retries} retries", page=page_num, agent="agent1", error=str(e), retries=max_retries)

        # All retries exhausted
        return {
            "page_number": page_num,
            "total_errors_found": 0,
            "errors": [],
            "error_message": str(last_error)
        }

    def agent2_correct(self, page_num, page_data, error_catalog):
        """Agent 2: Apply corrections to regions"""

        errors_count = error_catalog.get('total_errors_found', 0)
        correctable_regions = self.filter_correctable_regions(page_data)
        target_text = self.build_page_text(page_data, correctable_regions)

        if errors_count == 0:
            return target_text  # Return original text, not page_data object!

        system_prompt = """You are an OCR correction specialist. Apply ONLY the specific corrections provided in the error catalog.

RULES:
1. Apply ONLY the corrections listed in the error catalog
2. Do NOT make any other changes, improvements, or "fixes"
3. Preserve all formatting, paragraph breaks, and structure
4. If a correction seems wrong, apply it anyway (verification will catch it)
5. Do NOT rephrase or modernize language
6. Mark each correction with [CORRECTED:id] immediately after the fix

OUTPUT FORMAT:
Return ONLY the corrected text with inline [CORRECTED:id] markers.

WRONG - Do NOT include preambles:
"Here's the corrected text:
The president walked into the[CORRECTED:1] room."

WRONG - Do NOT include explanations:
"I've applied the corrections as requested. The president walked..."

CORRECT - Start immediately with content:
"The president walked into the[CORRECTED:1] room."

Your response must begin with the first word of the text, not with any explanation or introduction."""

        user_prompt = f"""Apply these specific corrections to page {page_num}.

ERROR CATALOG:
{json.dumps(error_catalog['errors'], indent=2)}

ORIGINAL TEXT (Page {page_num}):
{target_text}

Return the corrected text with [CORRECTED:id] markers after each fix."""

        try:
            response, usage = self.call_llm(system_prompt, user_prompt, temperature=0)
            corrected_text = response.strip()

            # Store corrected text (will be split back into regions later if needed)
            with self.stats_lock:
                self.stats['corrections_applied'] += errors_count

            return corrected_text

        except Exception as e:
            self.logger.error("Agent 2 error", page=page_num, agent="agent2", error=str(e))
            return target_text  # Return original on error

    def agent3_verify(self, page_num, page_data, error_catalog, corrected_text):
        """Agent 3: Verify corrections"""

        correctable_regions = self.filter_correctable_regions(page_data)
        original_text = self.build_page_text(page_data, correctable_regions)

        system_prompt = """You are a text verification specialist. Verify that corrections were applied correctly.

VERIFICATION CHECKLIST:
1. Were all identified errors corrected?
2. Were corrections applied accurately?
3. Were any unauthorized changes made?
4. Is document structure preserved?
5. Are there any new errors introduced?

CONFIDENCE SCORING:
- 1.0: Perfect, all corrections applied correctly
- 0.9: Minor issues, but acceptable
- 0.8: Some concerns, may need review
- <0.8: Significant issues, flag for human review

ADDITIONAL CHECKLIST:
6. Are [CORRECTED:id] markers present and correctly placed?
7. Do marker IDs match the error catalog?

OUTPUT FORMAT:
Return ONLY valid JSON, no additional text or commentary.
Do NOT include explanatory text before or after the JSON.
Start your response with the opening brace {

CORRECT OUTPUT:
{"page_number": 5, "all_corrections_applied": true, "confidence_score": 1.0, ...}

WRONG OUTPUT:
I have verified the corrections. Here are my findings:
{"page_number": 5, ...}

WRONG OUTPUT:
```json
{"page_number": 5, ...}
```

JSON Structure:
{
  "page_number": N,
  "all_corrections_applied": true/false,
  "corrections_verified": {
    "correctly_applied": X,
    "incorrectly_applied": Y,
    "missed": Z
  },
  "unauthorized_changes": [],
  "new_errors_introduced": [],
  "structure_preserved": true/false,
  "confidence_score": 0.0-1.0,
  "needs_human_review": true/false,
  "review_reason": "explanation if needed"
}"""

        user_prompt = f"""Verify corrections for page {page_num}.

ORIGINAL TEXT:
{original_text}

ERROR CATALOG (what should be fixed):
{json.dumps(error_catalog.get('errors', []), indent=2)}

CORRECTED TEXT (what Agent 2 produced):
{corrected_text}

Verify each correction and check for unauthorized changes."""

        try:
            response, usage = self.call_llm(system_prompt, user_prompt, temperature=0)
            json_text = self.extract_json(response, debug_label=f"page_{page_num:04d}_agent3")
            verification = json.loads(json_text)
            verification['verification_timestamp'] = datetime.now().isoformat()

            confidence = verification.get('confidence_score', 0)
            needs_review = verification.get('needs_human_review', False)

            if needs_review or confidence < 0.8:
                with self.stats_lock:
                    self.stats['pages_needing_review'] += 1

            return verification

        except Exception as e:
            self.logger.error("Agent 3 error", page=page_num, agent="agent3", error=str(e))
            return {
                "page_number": page_num,
                "confidence_score": 0.0,
                "needs_human_review": True,
                "review_reason": f"Verification failed: {str(e)}"
            }

    def process_single_page(self, page_num, total_pages):
        """Process a single page through the 3-agent pipeline"""
        try:
            # Load page with context
            prev_text, page_data, next_text = self.get_page_context(page_num, total_pages)

            if not page_data:
                return {'page': page_num, 'status': 'not_found'}

            # Make a deep copy to avoid circular reference issues
            page_data = copy.deepcopy(page_data)

            # Check if page has correctable content
            correctable_regions = self.filter_correctable_regions(page_data)
            if not correctable_regions:
                # Save original with skip marker
                page_data['llm_processing'] = {
                    'skipped': True,
                    'skip_reason': 'no_correctable_regions',
                    'timestamp': datetime.now().isoformat()
                }

                # Save to flat corrected directory
                output_file = self.corrected_dir / f"page_{page_num:04d}.json"
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(page_data, f, indent=2, default=str)

                with self.stats_lock:
                    self.stats['skipped_pages'] += 1

                return {'page': page_num, 'status': 'skipped'}

            # Agent 1: Detect errors
            error_catalog = self.agent1_detect_errors(page_num, prev_text, page_data, next_text)

            # Agent 2: Apply corrections
            corrected_text = self.agent2_correct(page_num, page_data, error_catalog)

            # Agent 3: Verify
            verification = self.agent3_verify(page_num, page_data, error_catalog, corrected_text)

            # Update page data with results
            page_data['llm_processing'] = {
                'timestamp': datetime.now().isoformat(),
                'model': self.model,
                'error_catalog': error_catalog,
                'corrected_text': corrected_text,
                'verification': verification
            }

            # Save corrected JSON to flat directory
            output_file = self.corrected_dir / f"page_{page_num:04d}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(page_data, f, indent=2, default=str)

            # Save to review if flagged
            if verification.get('needs_human_review') or verification.get('confidence_score', 1.0) < 0.8:
                review_file = self.needs_review_dir / f"page_{page_num:04d}.json"
                with open(review_file, 'w', encoding='utf-8') as f:
                    json.dump(page_data, f, indent=2, default=str)

            with self.stats_lock:
                self.stats['processed_pages'] += 1

            return {
                'page': page_num,
                'status': 'success',
                'errors_found': error_catalog.get('total_errors_found', 0),
                'confidence': verification.get('confidence_score', 0)
            }

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {'page': page_num, 'status': 'error', 'error': str(e)}

    def process_pages(self, start_page=1, end_page=None, total_pages=None, resume=False):
        """Process range of pages with parallel execution"""

        if total_pages is None:
            metadata_file = self.book_dir / "metadata.json"
            if metadata_file.exists():
                with open(metadata_file) as f:
                    metadata = json.load(f)
                    total_pages = metadata.get('total_pages', 447)
            else:
                total_pages = 447

        if end_page is None:
            end_page = total_pages

        # Use checkpoint system to determine which pages to process
        if self.checkpoint and resume:
            page_numbers = self.checkpoint.get_remaining_pages(
                total_pages=total_pages,
                resume=True,
                start_page=start_page,
                end_page=end_page
            )

            # Log resume information
            skipped = (end_page - start_page + 1) - len(page_numbers)
            if skipped > 0:
                cost_saved = self.checkpoint.estimate_cost_saved(avg_cost_per_page=0.022)
                self.logger.info(
                    f"Resuming from checkpoint: {skipped} pages already completed",
                    skipped_pages=skipped,
                    remaining_pages=len(page_numbers),
                    estimated_cost_saved=cost_saved
                )
                print(f"✅ Resuming: {skipped} pages already completed (saved ~${cost_saved:.2f})")
                print(f"⏳ Processing {len(page_numbers)} remaining pages...")
        elif self.checkpoint:
            # Start fresh - reset checkpoint
            self.checkpoint.reset()
            page_numbers = list(range(start_page, end_page + 1))
        else:
            # No checkpoint system
            page_numbers = list(range(start_page, end_page + 1))

        self.stats['total_pages'] = len(page_numbers)

        if len(page_numbers) == 0:
            self.logger.info("All pages already completed - nothing to process")
            print("✅ All pages already completed!")
            return

        # Log stage start with metadata
        self.logger.start_stage(
            start_page=start_page,
            end_page=end_page,
            total_pages=self.stats['total_pages'],
            model=self.model,
            max_workers=self.max_workers,
            rate_limit=self.rate_limiter.calls_per_minute,
            resume=resume
        )

        # Process in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_page = {
                executor.submit(self.process_single_page, page_num, total_pages): page_num
                for page_num in page_numbers
            }

            completed = 0
            for future in as_completed(future_to_page):
                page_num = future_to_page[future]
                result = future.result()

                completed += 1

                with self.progress_lock:
                    # Update checkpoint inside lock for consistency
                    if self.checkpoint and result['status'] in ['success', 'skipped']:
                        page_cost = result.get('cost_usd', 0.022)  # Estimate if not provided
                        self.checkpoint.mark_completed(page_num, cost_usd=page_cost)

                    # Log progress with detailed information
                    if result['status'] == 'success':
                        conf = result.get('confidence', 0)
                        errors = result.get('errors_found', 0)
                        self.logger.progress(
                            f"Page {page_num}: {errors} errors, confidence {conf:.2f}",
                            current=completed,
                            total=len(page_numbers),
                            page=page_num,
                            errors_found=errors,
                            confidence=conf,
                            status=result['status']
                        )
                    elif result['status'] == 'skipped':
                        self.logger.info(
                            f"Page {page_num}: skipped",
                            page=page_num,
                            status=result['status'],
                            progress_current=completed,
                            progress_total=len(page_numbers)
                        )
                    else:
                        self.logger.warning(
                            f"Page {page_num}: {result['status']}",
                            page=page_num,
                            status=result['status'],
                            error=result.get('error'),
                            progress_current=completed,
                            progress_total=len(page_numbers)
                        )

        self.print_summary()

        # Mark stage complete in checkpoint
        if self.checkpoint:
            self.checkpoint.mark_stage_complete(metadata={
                "model": self.model,
                "workers": self.max_workers,
                "total_cost_usd": self.stats['total_cost_usd']
            })

    def print_summary(self):
        """Print processing summary and log completion"""
        # Log summary to structured logs
        self.logger.info(
            "Processing complete",
            total_pages=self.stats['total_pages'],
            processed_pages=self.stats['processed_pages'],
            skipped_pages=self.stats['skipped_pages'],
            total_errors_found=self.stats['total_errors_found'],
            corrections_applied=self.stats['corrections_applied'],
            pages_needing_review=self.stats['pages_needing_review'],
            total_cost_usd=self.stats['total_cost_usd']
        )

        # Also print human-readable summary (old format for compatibility)
        print(f"\n{'='*60}")
        print("📊 Processing Complete")
        print(f"{'='*60}")
        print(f"Total pages: {self.stats['total_pages']}")
        print(f"  Processed: {self.stats['processed_pages']}")
        print(f"  Skipped: {self.stats['skipped_pages']} (no correctable content)")
        print(f"Total errors found: {self.stats['total_errors_found']}")
        print(f"Corrections applied: {self.stats['corrections_applied']}")
        print(f"Pages needing review: {self.stats['pages_needing_review']}")
        print(f"Total cost: ${self.stats['total_cost_usd']:.2f}")
        print(f"{'='*60}\n")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Process book OCR through 3-agent LLM correction pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process full book with default model (GPT-4o-mini)
  python pipeline/correct.py The-Accidental-President

  # Process pages 1-50
  python pipeline/correct.py The-Accidental-President --start 1 --end 50

  # Use different model
  python pipeline/correct.py The-Accidental-President --model anthropic/claude-3.5-haiku

  # Adjust concurrency
  python pipeline/correct.py The-Accidental-President --workers 30 --rate-limit 60

Default models and pricing (per 447-page book):
  - openai/gpt-4o-mini: ~$0.32 (default, excellent quality)
  - anthropic/claude-3-haiku: ~$0.61 (Claude family)
  - google/gemini-2.5-flash: ~$1.02 (fast, 1M context)
  - deepseek/deepseek-chat-v3.1: ~$0.43 (structured output)
        """
    )

    parser.add_argument('book_slug', help='Book slug (e.g., The-Accidental-President)')
    parser.add_argument('--start', type=int, default=1, help='Start page (default: 1)')
    parser.add_argument('--end', type=int, default=None, help='End page (default: all pages)')
    parser.add_argument('--model', default='openai/gpt-4o-mini',
                        help='OpenRouter model ID (default: openai/gpt-4o-mini)')
    parser.add_argument('--workers', type=int, default=30,
                        help='Max concurrent workers (default: 30)')
    parser.add_argument('--rate-limit', type=int, default=150,
                        help='API calls per minute (default: 150 for paid models)')
    parser.add_argument('--resume', action='store_true',
                        help='Resume from checkpoint (skip already-completed pages)')

    args = parser.parse_args()

    print(f"📊 Configuration:")
    print(f"   Model: {args.model}")
    print(f"   Workers: {args.workers}")
    print(f"   Rate limit: {args.rate_limit}/min")
    print(f"   Page range: {args.start}-{args.end or 'end'}")
    print(f"   Resume: {args.resume}")
    print()

    processor = StructuredPageCorrector(
        args.book_slug,
        model=args.model,
        max_workers=args.workers,
        calls_per_minute=args.rate_limit
    )
    processor.process_pages(args.start, args.end, resume=args.resume)


if __name__ == "__main__":
    main()