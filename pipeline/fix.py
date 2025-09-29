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
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv


class Agent4TargetedFix:
    """Agent 4: Make targeted fixes based on Agent 3 feedback."""

    def __init__(self, book_slug: str):
        self.book_slug = book_slug
        self.base_dir = Path.home() / "Documents" / "book_scans" / book_slug

        # Directories
        self.needs_review_dir = self.base_dir / "needs_review"
        self.corrected_dir = self.base_dir / "llm_agent2_corrected"
        self.final_dir = self.base_dir / "llm_agent4_final"
        self.final_dir.mkdir(exist_ok=True)

        # Load API key
        load_dotenv()
        self.api_key = os.getenv('OPEN_ROUTER_API_KEY') or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("No OpenRouter API key found in environment")

        self.model = "anthropic/claude-3.5-sonnet"

        # Stats
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

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()

        result = response.json()

        # Extract usage for cost tracking
        usage = result.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)

        # Cost: $3/M input, $15/M output
        cost = (prompt_tokens / 1_000_000 * 3.0) + (completion_tokens / 1_000_000 * 15.0)
        self.stats['total_cost_usd'] += cost

        return result['choices'][0]['message']['content'], usage

    def agent4_targeted_fix(self, page_num: int, corrected_text: str,
                            agent3_feedback: str, missed_corrections: list):
        """
        Agent 4: Make targeted fixes based on Agent 3's explicit feedback.

        This agent does NOT re-analyze the entire page. It ONLY fixes the
        specific issues that Agent 3 identified as missed.
        """
        print(f"  Agent 4: Applying targeted fixes...")

        system_prompt = """You are Agent 4, a precision correction specialist.

Your ONLY job is to fix the SPECIFIC errors that Agent 3 identified as "missed".

CRITICAL RULES:
1. Make ONLY the corrections explicitly mentioned in Agent 3's feedback
2. Do NOT re-analyze the text for new errors
3. Do NOT modify anything except the specific missed corrections
4. Preserve ALL existing [CORRECTED:id] markers
5. Add new corrections with format [FIXED:id]
6. Return the complete corrected text

OUTPUT FORMAT:
Return the full corrected text with targeted fixes applied.
Do NOT wrap in JSON or code blocks - just return the text."""

        # Build detailed correction instructions
        correction_details = []
        for i, correction in enumerate(missed_corrections, 1):
            correction_details.append(f"{i}. {correction}")

        user_prompt = f"""Fix ONLY these specific missed corrections on page {page_num}:

AGENT 3 FEEDBACK:
{agent3_feedback}

MISSED CORRECTIONS TO APPLY:
{chr(10).join(correction_details)}

CURRENT TEXT (with existing corrections):
{corrected_text}

Apply ONLY the missed corrections listed above. Mark new fixes with [FIXED:id].
Return the complete corrected text."""

        try:
            response, usage = self.call_llm(system_prompt, user_prompt, temperature=0.0)

            # Save fixed text
            output_file = self.final_dir / f"page_{page_num:04d}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Page {page_num}\n")
                f.write(f"# Fixed by Agent 4\n")
                f.write(f"# Based on Agent 3 feedback\n")
                f.write(f"# Targeted corrections: {len(missed_corrections)}\n\n")
                f.write(response)

            print(f"    ✓ Applied {len(missed_corrections)} targeted fixes")
            return response

        except Exception as e:
            print(f"    ✗ Error in Agent 4: {e}")
            # On error, save the Agent 2 version unchanged
            output_file = self.final_dir / f"page_{page_num:04d}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Page {page_num}\n")
                f.write(f"# Agent 4 FAILED - using Agent 2 output\n")
                f.write(f"# Error: {str(e)}\n\n")
                f.write(corrected_text)
            return corrected_text

    def parse_agent3_feedback(self, review_data: dict):
        """Extract missed corrections from Agent 3 feedback."""
        verification = review_data.get("verification", {})
        review_reason = verification.get("review_reason", "")

        # Parse the review reason to extract specific corrections
        # This is heuristic-based parsing of Agent 3's natural language feedback
        missed = []

        # Common patterns in Agent 3 feedback
        if "Lec £814" in review_reason:
            missed.append("Change 'Lec £814' to 'LCC E814'")
        if "pvc" in review_reason:
            missed.append("Change 'pvc' to 'DDC'")
        if "lecn" in review_reason:
            missed.append("Change 'lecn' to 'lccn'")

        if "Berenstein" in review_reason and "second instance" in review_reason:
            missed.append("Change the second instance of 'Berenstein' to 'Bernstein'")

        if "'ve' to 'I've'" in review_reason:
            missed.append("Change 've' to 'I've'")

        if "Muehlbach" in review_reason:
            missed.append("Change 'Muehlbach' to 'Muehlebach' in the first instance")

        # If we couldn't parse specific corrections, use the full reason
        if not missed:
            missed.append(f"Review and fix: {review_reason}")

        return missed

    def process_flagged_page(self, review_file: Path):
        """Process a single flagged page."""
        with open(review_file) as f:
            review_data = json.load(f)

        page_num = review_data.get("page_number")
        print(f"\n📄 Processing page {page_num}...")

        # Load Agent 2's corrected text
        corrected_file = self.corrected_dir / f"page_{page_num:04d}.txt"
        if not corrected_file.exists():
            print(f"  ✗ Agent 2 corrected file not found")
            self.stats['pages_failed'] += 1
            return

        with open(corrected_file, 'r', encoding='utf-8') as f:
            corrected_text = f.read()

        # Get Agent 3's feedback
        verification = review_data.get("verification", {})
        agent3_feedback = verification.get("review_reason", "")
        confidence = review_data.get("confidence_score", 0.0)

        print(f"  Original confidence: {confidence:.2f}")
        print(f"  Agent 3 feedback: {agent3_feedback[:100]}...")

        # Parse missed corrections
        missed_corrections = self.parse_agent3_feedback(review_data)
        print(f"  Identified {len(missed_corrections)} missed corrections")

        # Apply targeted fixes
        fixed_text = self.agent4_targeted_fix(
            page_num,
            corrected_text,
            agent3_feedback,
            missed_corrections
        )

        # Save metadata
        metadata_file = self.final_dir / f"page_{page_num:04d}_metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump({
                "page_number": page_num,
                "agent3_confidence": confidence,
                "agent3_feedback": agent3_feedback,
                "missed_corrections": missed_corrections,
                "agent4_timestamp": datetime.now().isoformat(),
                "processing_status": "fixed"
            }, f, indent=2)

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

        for review_file in flagged_files:
            try:
                self.process_flagged_page(review_file)
            except Exception as e:
                print(f"\n❌ Failed to process {review_file.name}: {e}")
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
        print(f"\n📁 Output: {self.final_dir}")
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