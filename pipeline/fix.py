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
import requests
import time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from pricing import CostCalculator


class Agent4TargetedFix:
    """Agent 4: Make targeted fixes based on Agent 3 feedback."""

    def __init__(self, book_slug: str, max_workers: int = 15):
        self.book_slug = book_slug
        self.base_dir = Path.home() / "Documents" / "book_scans" / book_slug
        self.max_workers = max_workers

        # Directories
        self.needs_review_dir = self.base_dir / "needs_review"
        self.corrected_dir = self.base_dir / "corrected"

        # Load API key
        load_dotenv()
        self.api_key = os.getenv('OPEN_ROUTER_API_KEY') or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("No OpenRouter API key found in environment")

        self.model = "anthropic/claude-3.5-sonnet"

        # Initialize cost calculator with dynamic pricing
        self.cost_calculator = CostCalculator()

        # Stats (thread-safe)
        import threading
        self.stats_lock = threading.Lock()
        self.stats = {
            "pages_processed": 0,
            "pages_fixed": 0,
            "pages_failed": 0,
            "total_cost_usd": 0.0
        }

    def call_llm(self, system_prompt: str, user_prompt: str, temperature=0.0):
        """Make API call to OpenRouter."""
        url = "https://openrouter.ai/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jackzampolin/ar-research",
            "X-Title": "AR Research Agent 4 Fixes"
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature
        }

        # Retry logic for transient errors
        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=120)
                response.raise_for_status()

                result = response.json()

                # Extract usage for cost tracking
                usage = result.get('usage', {})
                prompt_tokens = usage.get('prompt_tokens', 0)
                completion_tokens = usage.get('completion_tokens', 0)

                # Calculate cost using dynamic pricing from OpenRouter API
                cost = self.cost_calculator.calculate_cost(
                    self.model,
                    prompt_tokens,
                    completion_tokens
                )
                with self.stats_lock:
                    self.stats['total_cost_usd'] += cost

                return result['choices'][0]['message']['content'], usage

            except requests.exceptions.HTTPError as e:
                if e.response.status_code >= 500:
                    # Server error - retry with exponential backoff
                    if attempt < max_retries - 1:
                        wait_time = retry_delay * (2 ** attempt)
                        print(f"  ⚠️  Server error {e.response.status_code}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"  ❌ Server error after {max_retries} attempts, skipping this page")
                        raise
                else:
                    # Client error (4xx) - don't retry
                    raise
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                # Handle both Timeout and ConnectionError (which wraps ReadTimeoutError)
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)
                    error_type = "timeout" if isinstance(e, requests.exceptions.Timeout) else "connection error"
                    print(f"  ⚠️  Request {error_type}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  ❌ Request failed after {max_retries} attempts, skipping this page")
                    raise

    def agent4_targeted_fix(self, page_num: int, page_data: dict, corrected_text: str,
                            agent3_feedback: str, missed_corrections: list):
        """
        Agent 4: Make targeted fixes based on Agent 3's explicit feedback.

        This agent does NOT re-analyze the entire page. It ONLY fixes the
        specific issues that Agent 3 identified as missed.
        """
        print(f"  Agent 4: Applying targeted fixes...")

        system_prompt = """You are Agent 4, a precision correction specialist.

Your ONLY job is to fix the SPECIFIC errors that Agent 3 identified as "missed" or "incorrectly applied".

CRITICAL RULES:
1. Make ONLY the corrections explicitly mentioned in Agent 3's feedback
2. Do NOT re-analyze the text for new errors
3. Do NOT modify anything except the specific missed corrections
4. Preserve ALL existing [CORRECTED:id] markers
5. Add new corrections with format [FIXED:A4-id]
6. Return the complete corrected text

OUTPUT FORMAT:
Return the full corrected text with targeted fixes applied.
Do NOT wrap in JSON or code blocks - just return the text."""

        # Build detailed correction instructions
        correction_details = []
        for i, correction in enumerate(missed_corrections, 1):
            correction_details.append(f"{i}. {correction}")

        user_prompt = f"""Fix ONLY these specific missed/incorrect corrections on page {page_num}:

AGENT 3 FEEDBACK:
{agent3_feedback}

MISSED/INCORRECT CORRECTIONS TO APPLY:
{chr(10).join(correction_details)}

CURRENT TEXT (with existing corrections):
{corrected_text}

Apply ONLY the corrections listed above. Mark new fixes with [FIXED:A4-id].
Return the complete corrected text."""

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

            # Save updated JSON back to corrected directory (overwrite)
            output_file = self.corrected_dir / f"page_{page_num:04d}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(page_data, f, indent=2, default=str)

            print(f"    ✓ Applied {len(missed_corrections)} targeted fixes")
            return response

        except Exception as e:
            print(f"    ✗ Error in Agent 4: {e}")
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

    def parse_agent3_feedback(self, review_data: dict):
        """Extract missed corrections from Agent 3 feedback."""
        verification = review_data.get("llm_processing", {}).get("verification", {})
        review_reason = verification.get("review_reason", "")

        # Parse the review reason to extract specific corrections
        # This uses Agent 3's structured feedback which identifies specific issues
        missed = []

        # Pattern: Classification codes (Page 4)
        if "Lec" in review_reason and "LCC" in review_reason:
            missed.append("Change 'Lec' to 'LCC'")
        if "£814" in review_reason and "E814" in review_reason:
            missed.append("Change '£814' to 'E814'")
        if "pvc" in review_reason and "DDC" in review_reason:
            missed.append("Change 'pvc' to 'DDC'")

        # Pattern: Name corrections (Berenstein, Muehlebach, etc.)
        if "Berenstein" in review_reason and ("second" in review_reason or "following" in review_reason):
            missed.append("Change remaining instance(s) of 'Berenstein' to 'Bernstein'")

        if "Muehlbach" in review_reason and "Muehlebach" in review_reason:
            missed.append("Change 'Muehlbach' to 'Muehlebach'")

        if "Mamma" in review_reason and "Mama" in review_reason:
            missed.append("Change remaining instance(s) of 'Mamma' to 'Mama'")

        # Pattern: Contractions
        if "'ve'" in review_reason and "I've" in review_reason:
            missed.append("Change 've' to 'I've'")

        # Pattern: OCR artifacts
        if "'28'" in review_reason or "OCR artifact '28'" in review_reason:
            missed.append("Remove the OCR artifact '28' from the beginning")

        if "'Mf'" in review_reason:
            missed.append("Remove the OCR artifact 'Mf'")

        # Pattern: Offensive terms
        if "'Jap'" in review_reason and "Japanese" in review_reason:
            missed.append("Change remaining instance(s) of 'Jap' to 'Japanese'")

        # Pattern: Incorrect corrections that should be reverted
        if "incorrectly applied" in review_reason.lower():
            if "beggared" in review_reason and "beggarred" in review_reason:
                missed.append("Revert 'beggarred' back to 'beggared' (it was correct)")
            if "Messall" in review_reason and "Messali" in review_reason:
                missed.append("Revert 'Messali' back to 'Messall' (it was correct)")
            if "anyhow" in review_reason and "any how" in review_reason:
                missed.append("Revert 'any how' back to 'anyhow' (it was correct)")
            if "self-contained" in review_reason:
                missed.append("Revert 'selfcontained' back to 'self-contained' (hyphen is correct)")
            if "wardroom" in review_reason and "war room" in review_reason:
                missed.append("Revert 'war room' back to 'wardroom' (naval term)")
            if "been been" in review_reason or "duplicate 'been'" in review_reason:
                missed.append("Remove duplicate 'been' to fix grammar")

        # Pattern: Common OCR errors
        if "Tbid" in review_reason:
            missed.append("Change 'Tbid.' to 'Ibid.'")
        if "Zruman" in review_reason:
            missed.append("Change 'Zruman' to 'Truman'")
        if "70°" in review_reason and "degree symbol" in review_reason:
            missed.append("Remove degree symbol from '70°'")
        if "box g" in review_reason and "box 9" in review_reason:
            missed.append("Change remaining 'box g' to 'box 9'")

        # If we couldn't parse specific corrections, use the full reason
        if not missed:
            missed.append(f"Review and fix based on Agent 3 feedback: {review_reason[:200]}")

        return missed

    def process_flagged_page(self, review_file: Path):
        """Process a single flagged page."""
        with open(review_file) as f:
            review_data = json.load(f)

        page_num = review_data.get("page_number")
        print(f"\n📄 Processing page {page_num}...")

        # Load corrected page from flat directory
        corrected_file = self.corrected_dir / f"page_{page_num:04d}.json"
        if corrected_file.exists():
            with open(corrected_file, 'r', encoding='utf-8') as f:
                corrected_data = json.load(f)
        else:
            corrected_data = None

        if not corrected_data:
            print(f"  ✗ Corrected JSON file not found")
            with self.stats_lock:
                self.stats['pages_failed'] += 1
            return

        # Checkpoint: Check if this page was already processed by Agent 4
        llm_processing = corrected_data.get('llm_processing', {})
        if 'agent4_fixes' in llm_processing:
            print(f"  ✓ Already processed (checkpoint found), skipping")
            with self.stats_lock:
                self.stats['pages_processed'] += 1
                self.stats['pages_fixed'] += 1
            return

        # Extract corrected text from llm_processing section
        corrected_text = llm_processing.get('corrected_text', '')

        if not corrected_text:
            print(f"  ✗ No corrected_text in JSON")
            with self.stats_lock:
                self.stats['pages_failed'] += 1
            return

        # Get Agent 3's feedback from the structured JSON
        llm_processing = review_data.get("llm_processing", {})
        verification = llm_processing.get("verification", {})
        agent3_feedback = verification.get("review_reason", "")
        confidence = verification.get("confidence_score", 0.0)

        print(f"  Original confidence: {confidence:.2f}")
        print(f"  Agent 3 feedback: {agent3_feedback[:100]}...")

        # Parse missed corrections
        missed_corrections = self.parse_agent3_feedback(review_data)
        print(f"  Identified {len(missed_corrections)} missed corrections")

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

    def process_all_flagged(self):
        """Process all flagged pages."""
        print("=" * 70)
        print("🔧 Agent 4: Targeted Fixes")
        print(f"   Book: {self.book_slug}")
        print("=" * 70)

        # Get all flagged pages
        flagged_files = sorted(self.needs_review_dir.glob("page_*.json"))
        print(f"\n📋 Found {len(flagged_files)} pages flagged for review")
        print(f"⚙️  Processing with {self.max_workers} parallel workers\n")

        # Process pages in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_file = {
                executor.submit(self.process_flagged_page, review_file): review_file
                for review_file in flagged_files
            }

            # Process completions as they finish
            for future in as_completed(future_to_file):
                review_file = future_to_file[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"\n❌ Failed to process {review_file.name}: {e}")
                    with self.stats_lock:
                        self.stats['pages_failed'] += 1

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