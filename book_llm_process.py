#!/usr/bin/env python3
"""
LLM Text Cleanup Pipeline - 3-Agent Per-Page Processing
Processes OCR text through error detection, correction, and verification
"""

import os
import json
import requests
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class LLMBookProcessor:
    """
    Process book pages through 3-agent LLM pipeline:
    - Agent 1: Detect OCR errors
    - Agent 2: Apply corrections
    - Agent 3: Verify corrections
    """

    def __init__(self, book_title, storage_root=None, model="anthropic/claude-3.5-sonnet"):
        self.book_title = book_title
        self.storage_root = Path(storage_root or "~/Documents/book_scans").expanduser()
        self.book_dir = self.storage_root / book_title
        self.model = model

        # Get API key (support both naming conventions)
        self.api_key = os.getenv('OPEN_ROUTER_API_KEY') or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise ValueError("OPEN_ROUTER_API_KEY not found in environment")

        # Create output directories
        self.ocr_dir = self.book_dir / "ocr_text"
        self.errors_dir = self.book_dir / "llm_agent1_errors"
        self.corrected_dir = self.book_dir / "llm_agent2_corrected"
        self.verification_dir = self.book_dir / "llm_agent3_verification"
        self.needs_review_dir = self.book_dir / "needs_review"

        for dir_path in [self.errors_dir, self.corrected_dir, self.verification_dir, self.needs_review_dir]:
            dir_path.mkdir(exist_ok=True)

        # Stats tracking
        self.stats = {
            "total_pages": 0,
            "processed_pages": 0,
            "total_errors_found": 0,
            "corrections_applied": 0,
            "pages_needing_review": 0,
            "total_cost_usd": 0.0
        }

    def extract_json(self, text):
        """
        Extract JSON from LLM response, handling markdown code blocks and extra text
        """
        text = text.strip()

        # Remove markdown code blocks
        if '```json' in text or '```' in text:
            # Find the JSON content between ```json and ``` or between ``` and ```
            import re
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
            if json_match:
                text = json_match.group(1).strip()
            else:
                # Just remove all ``` markers
                text = text.replace('```json', '').replace('```', '').strip()

        # Find the first { and last } for JSON object
        first_brace = text.find('{')
        last_brace = text.rfind('}')

        if first_brace != -1 and last_brace != -1:
            text = text[first_brace:last_brace + 1]

        return text

    def call_llm(self, system_prompt, user_prompt, temperature=0.1):
        """
        Make API call to OpenRouter
        """
        url = "https://openrouter.ai/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/jackzampolin/ar-research",
            "X-Title": "AR Research OCR Cleanup"
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

        # Extract usage info for cost tracking
        usage = result.get('usage', {})
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)

        # Rough cost estimate for Claude 3.5 Sonnet via OpenRouter
        # $3/M input, $15/M output
        cost = (prompt_tokens / 1_000_000 * 3.0) + (completion_tokens / 1_000_000 * 15.0)
        self.stats['total_cost_usd'] += cost

        return result['choices'][0]['message']['content'], usage

    def load_page(self, page_num):
        """Load page text from OCR output"""
        # Find the page file across all batches
        for batch_dir in sorted(self.ocr_dir.glob("batch_*")):
            page_file = batch_dir / f"page_{page_num:04d}.txt"
            if page_file.exists():
                with open(page_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Remove the OCR metadata headers
                lines = content.split('\n')
                # Skip first 3 lines (# Page N, # Batch N, # OCR Date)
                text = '\n'.join(lines[3:]) if len(lines) > 3 else content
                return text.strip()
        return None

    def get_page_context(self, page_num, total_pages):
        """
        Get 3-page context: previous, current, next
        Returns: (prev_text, current_text, next_text)
        """
        prev_page = self.load_page(page_num - 1) if page_num > 1 else None
        current_page = self.load_page(page_num)
        next_page = self.load_page(page_num + 1) if page_num < total_pages else None

        return prev_page, current_page, next_page

    def agent1_detect_errors(self, page_num, prev_page, current_page, next_page):
        """
        Agent 1: Detect OCR errors on target page using 3-page context
        """
        print(f"  Agent 1: Detecting errors on page {page_num}...")

        system_prompt = """You are an OCR error detection specialist. Your job is to identify potential OCR errors in scanned book text.

RULES:
1. DO NOT fix or correct anything
2. ONLY identify and catalog potential errors
3. Focus ONLY on the specified target page
4. Use adjacent pages for context but don't report errors from them
5. Report errors with high confidence (>0.7) only

ERROR TYPES TO DETECT:
- Character substitutions (rn→m, l→1, O→0, vv→w)
- Spacing errors (word run-together, extra spaces)
- Hyphenated line breaks that should be joined (e.g., "presi-\\ndent")
- OCR artifacts (|||, ___, etc. that aren't real text)
- Obvious typos from OCR confusion

OUTPUT FORMAT:
Return valid JSON only, no additional text or markdown formatting:
{
  "page_number": N,
  "total_errors_found": X,
  "errors": [
    {
      "error_id": 1,
      "location": "line 5",
      "original_text": "tbe",
      "error_type": "character_substitution",
      "confidence": 0.95,
      "suggested_correction": "the",
      "context_before": "walked into ",
      "context_after": " room"
    }
  ]
}"""

        # Build context description
        context_parts = []
        if prev_page:
            context_parts.append(f"PAGE {page_num-1} (context only, do not analyze):\n{prev_page[:500]}...\n")

        context_parts.append(f"PAGE {page_num} (TARGET - ANALYZE THIS PAGE ONLY):\n{current_page}\n")

        if next_page:
            context_parts.append(f"PAGE {page_num+1} (context only, do not analyze):\n{next_page[:500]}...")

        user_prompt = f"""Analyze PAGE {page_num} ONLY for OCR errors.

Use adjacent pages for sentence context, but ONLY report errors from page {page_num}.

{chr(10).join(context_parts)}

Return JSON error catalog for page {page_num} only."""

        try:
            response, usage = self.call_llm(system_prompt, user_prompt, temperature=0.1)

            # Extract JSON robustly
            json_text = self.extract_json(response)
            error_catalog = json.loads(json_text)

            # Save error catalog
            output_file = self.errors_dir / f"page_{page_num:04d}.json"
            error_catalog['processing_timestamp'] = datetime.now().isoformat()
            error_catalog['agent_metadata'] = {
                'model': self.model,
                'tokens_used': usage.get('total_tokens', 0)
            }

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(error_catalog, f, indent=2)

            errors_found = error_catalog.get('total_errors_found', 0)
            self.stats['total_errors_found'] += errors_found

            print(f"    ✓ Found {errors_found} errors")
            return error_catalog

        except Exception as e:
            print(f"    ✗ Error in Agent 1: {e}")
            # Return empty error catalog
            return {
                "page_number": page_num,
                "total_errors_found": 0,
                "errors": [],
                "error_message": str(e)
            }

    def agent2_correct(self, page_num, original_text, error_catalog):
        """
        Agent 2: Apply corrections from error catalog
        """
        errors_count = error_catalog.get('total_errors_found', 0)
        print(f"  Agent 2: Applying {errors_count} corrections...")

        if errors_count == 0:
            print(f"    ✓ No corrections needed")
            # Save original text as corrected
            output_file = self.corrected_dir / f"page_{page_num:04d}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Page {page_num}\n")
                f.write(f"# No corrections needed\n\n")
                f.write(original_text)
            return original_text

        system_prompt = """You are an OCR correction specialist. Apply ONLY the specific corrections provided in the error catalog.

RULES:
1. Apply ONLY the corrections listed in the error catalog
2. Do NOT make any other changes, improvements, or "fixes"
3. Preserve all formatting, paragraph breaks, and structure
4. If a correction seems wrong, apply it anyway (verification will catch it)
5. Do NOT rephrase or modernize language
6. Mark each correction with [CORRECTED:id] immediately after the fix

OUTPUT FORMAT:
Return the corrected text with inline [CORRECTED:id] markers."""

        user_prompt = f"""Apply these specific corrections to page {page_num}.

ERROR CATALOG:
{json.dumps(error_catalog['errors'], indent=2)}

ORIGINAL TEXT (Page {page_num}):
{original_text}

Return the corrected text with [CORRECTED:id] markers after each fix."""

        try:
            response, usage = self.call_llm(system_prompt, user_prompt, temperature=0)

            corrected_text = response.strip()

            # Save corrected text
            output_file = self.corrected_dir / f"page_{page_num:04d}.txt"
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(f"# Page {page_num}\n")
                f.write(f"# Corrected by Agent 2\n")
                f.write(f"# Original errors: {errors_count}\n\n")
                f.write(corrected_text)

            self.stats['corrections_applied'] += errors_count
            print(f"    ✓ Applied {errors_count} corrections")
            return corrected_text

        except Exception as e:
            print(f"    ✗ Error in Agent 2: {e}")
            return original_text

    def agent3_verify(self, page_num, original_text, error_catalog, corrected_text):
        """
        Agent 3: Verify corrections were applied correctly
        """
        print(f"  Agent 3: Verifying corrections...")

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

OUTPUT FORMAT:
Return valid JSON only:
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

            # Extract JSON robustly
            json_text = self.extract_json(response)
            verification = json.loads(json_text)

            # Add metadata
            verification['verification_timestamp'] = datetime.now().isoformat()
            verification['agent_metadata'] = {
                'model': self.model,
                'tokens_used': usage.get('total_tokens', 0)
            }

            # Save verification report
            output_file = self.verification_dir / f"page_{page_num:04d}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(verification, f, indent=2)

            confidence = verification.get('confidence_score', 0)
            needs_review = verification.get('needs_human_review', False)

            if needs_review or confidence < 0.8:
                # Copy to needs_review directory
                review_file = self.needs_review_dir / f"page_{page_num:04d}.json"
                with open(review_file, 'w', encoding='utf-8') as f:
                    json.dump({
                        'page_number': page_num,
                        'confidence_score': confidence,
                        'verification': verification,
                        'original_text': original_text,
                        'corrected_text': corrected_text
                    }, f, indent=2)
                self.stats['pages_needing_review'] += 1
                print(f"    ⚠️  Confidence: {confidence:.2f} - FLAGGED FOR REVIEW")
            else:
                print(f"    ✓ Confidence: {confidence:.2f}")

            return verification

        except Exception as e:
            print(f"    ✗ Error in Agent 3: {e}")
            return {
                "page_number": page_num,
                "confidence_score": 0.0,
                "needs_human_review": True,
                "review_reason": f"Verification failed: {str(e)}"
            }

    def process_page(self, page_num, total_pages):
        """
        Process single page through 3-agent pipeline
        """
        print(f"\n📄 Processing page {page_num}/{total_pages}...")

        # Load 3-page context
        prev_page, current_page, next_page = self.get_page_context(page_num, total_pages)

        if not current_page:
            print(f"  ✗ Page {page_num} not found")
            return None

        # Agent 1: Detect errors
        error_catalog = self.agent1_detect_errors(page_num, prev_page, current_page, next_page)

        # Agent 2: Apply corrections
        corrected_text = self.agent2_correct(page_num, current_page, error_catalog)

        # Agent 3: Verify corrections
        verification = self.agent3_verify(page_num, current_page, error_catalog, corrected_text)

        self.stats['processed_pages'] += 1

        return verification

    def process_pages(self, start_page=1, end_page=None, total_pages=None):
        """
        Process range of pages
        """
        if total_pages is None:
            # Try to determine total pages from metadata
            metadata_file = self.book_dir / "metadata.json"
            if metadata_file.exists():
                with open(metadata_file) as f:
                    metadata = json.load(f)
                    total_pages = metadata.get('total_pages', 447)
            else:
                total_pages = 447  # Default

        if end_page is None:
            end_page = total_pages

        self.stats['total_pages'] = end_page - start_page + 1

        print(f"\n{'='*60}")
        print(f"🚀 Starting LLM processing: Pages {start_page}-{end_page}")
        print(f"   Model: {self.model}")
        print(f"{'='*60}")

        for page_num in range(start_page, end_page + 1):
            self.process_page(page_num, total_pages)

        self.print_summary()

    def print_summary(self):
        """Print processing summary"""
        print(f"\n{'='*60}")
        print("📊 Processing Summary")
        print(f"{'='*60}")
        print(f"Pages processed: {self.stats['processed_pages']}/{self.stats['total_pages']}")
        print(f"Total errors found: {self.stats['total_errors_found']}")
        print(f"Corrections applied: {self.stats['corrections_applied']}")
        print(f"Pages needing review: {self.stats['pages_needing_review']}")
        print(f"Total cost: ${self.stats['total_cost_usd']:.2f}")
        print(f"{'='*60}\n")


def main():
    """Main entry point"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python book_llm_process.py <book-safe-title> [start_page] [end_page]")
        print("Example: python book_llm_process.py The-Accidental-President 1 10")
        sys.exit(1)

    book_title = sys.argv[1]
    start_page = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    end_page = int(sys.argv[3]) if len(sys.argv) > 3 else 10  # Default to first 10 pages

    processor = LLMBookProcessor(book_title)
    processor.process_pages(start_page, end_page)


if __name__ == "__main__":
    main()