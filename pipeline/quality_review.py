#!/usr/bin/env python3
"""
Quality Review Pipeline Stage

LLM-based quality assessment of structured books.
Focuses on artifact detection and research-readiness of final output.
"""

import sys
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Tuple
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from llm_client import LLMClient

from config import Config


class QualityReview:
    """Research-readiness quality assessment for final structured books."""

    def __init__(self, scan_id: str):
        self.scan_id = scan_id
        self.book_dir = Config.BOOK_STORAGE_ROOT / scan_id
        self.structured_dir = self.book_dir / "structured"
        self.model = "anthropic/claude-sonnet-4.5"

        # Initialize LLM client
        self.llm_client = LLMClient()

        # Cost tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0

    def run(self) -> Dict[str, Any]:
        """Run complete quality review focused on research readiness."""
        print("=" * 70)
        print("📊 Research-Readiness Quality Review")
        print(f"   Book: {self.scan_id}")
        print(f"   Model: {self.model}")
        print("=" * 70)
        print()

        # Load final structured book
        print("=" * 70)
        print("📖 Loading Final Structured Output")
        print("=" * 70)

        full_book_path = self.structured_dir / "full_book.md"
        if not full_book_path.exists():
            raise FileNotFoundError(f"No structured book found: {full_book_path}")

        with open(full_book_path) as f:
            full_book = f.read()

        print(f"  ✓ Loaded full book: {len(full_book):,} characters")
        print()

        # Step 1: Regex-based artifact detection (fast, deterministic)
        print("=" * 70)
        print("🔍 Step 1: Artifact Detection (Regex)")
        print("=" * 70)

        artifact_analysis = self._detect_artifacts(full_book)
        self._print_artifact_summary(artifact_analysis)
        print()

        # Step 2: LLM-based quality assessment (deep, contextual)
        print("=" * 70)
        print("🤖 Step 2: LLM Quality Analysis")
        print("=" * 70)

        llm_analysis = self._llm_quality_check(full_book, artifact_analysis)
        print()

        # Step 3: Calculate final scores and grade
        print("=" * 70)
        print("📊 Step 3: Final Scoring")
        print("=" * 70)

        report = self._compile_report(artifact_analysis, llm_analysis, full_book)
        self._print_final_summary(report)
        print()

        # Save report
        report_path = self.book_dir / "quality_report.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"📁 Report saved: {report_path}")
        print("=" * 70)
        print()

        return report

    def _detect_artifacts(self, text: str) -> Dict[str, Any]:
        """Use regex to detect common artifacts in structured text."""

        artifacts = {
            "isbns": [],
            "dois": [],
            "copyright_notices": [],
            "library_catalog": [],
            "publisher_metadata": [],
            "page_numbers": [],
            "printing_codes": [],
            "urls": []
        }

        # ISBN patterns
        isbn_pattern = r'ISBN[:\s-]*(?:\d{1,5}[- ]?\d{1,7}[- ]?\d{1,7}[- ]?[\dX]|\d{13})'
        artifacts["isbns"] = re.findall(isbn_pattern, text, re.IGNORECASE)

        # DOI patterns
        doi_pattern = r'(?:doi|DOI)[:\s]*10\.\d{4,}/[^\s]+'
        artifacts["dois"] = re.findall(doi_pattern, text)

        # Copyright notices
        copyright_pattern = r'Copyright\s*©?\s*\d{4}.*?(?:\.|rights reserved)'
        artifacts["copyright_notices"] = re.findall(copyright_pattern, text, re.IGNORECASE)

        # Library catalog numbers
        catalog_patterns = [
            r'(?:LC|Lccn)[:\s]+[A-Z]*\d+',
            r'Dewey\s+Decimal[:\s]+[\d\.]+',
            r'(?:LC record|Library of Congress)'
        ]
        for pattern in catalog_patterns:
            artifacts["library_catalog"].extend(re.findall(pattern, text, re.IGNORECASE))

        # Publisher metadata
        publisher_patterns = [
            r'(?:HarperCollins|Penguin|Random House|Simon & Schuster|Macmillan)\s+Publishers?',
            r'(?:First|Second|Third)\s+(?:edition|printing)',
            r'Printed\s+in\s+(?:the\s+)?(?:United States|USA|America)'
        ]
        for pattern in publisher_patterns:
            artifacts["publisher_metadata"].extend(re.findall(pattern, text, re.IGNORECASE))

        # Printing codes (e.g., "25 26 27 28 29 LBC 23 22 21 20 19")
        printing_code_pattern = r'\b\d{2}\s+\d{2}\s+\d{2}\s+\d{2}\s+\d{2}\s+[A-Z]{2,4}\s+\d{2}'
        artifacts["printing_codes"] = re.findall(printing_code_pattern, text)

        # Standalone page numbers (likely artifacts)
        # Look for isolated numbers at start of lines or surrounded by whitespace
        page_num_pattern = r'(?:^|\n)\s*\d{1,3}\s*(?:\n|$)'
        artifacts["page_numbers"] = re.findall(page_num_pattern, text)

        # URLs
        url_pattern = r'https?://[^\s]+'
        artifacts["urls"] = re.findall(url_pattern, text)

        # Calculate totals
        total_artifacts = sum(len(v) if isinstance(v, list) else 0 for v in artifacts.values())

        # Estimate contaminated character count
        contaminated_chars = 0
        for key, items in artifacts.items():
            if isinstance(items, list):
                contaminated_chars += sum(len(str(item)) for item in items)

        clean_percentage = max(0, 100 - (contaminated_chars / len(text) * 100)) if text else 0

        return {
            "artifacts": artifacts,
            "total_count": total_artifacts,
            "contaminated_chars": contaminated_chars,
            "total_chars": len(text),
            "clean_percentage": round(clean_percentage, 2)
        }

    def _print_artifact_summary(self, analysis: Dict[str, Any]):
        """Print artifact detection results."""
        artifacts = analysis["artifacts"]

        print(f"  📏 Total characters: {analysis['total_chars']:,}")
        print(f"  🧹 Clean text: {analysis['clean_percentage']:.1f}%")
        print(f"  ⚠️  Artifacts found: {analysis['total_count']}")
        print()

        if artifacts["isbns"]:
            print(f"  📚 ISBNs: {len(artifacts['isbns'])} found")
            for isbn in artifacts["isbns"][:3]:
                print(f"     • {isbn}")
            if len(artifacts["isbns"]) > 3:
                print(f"     ... and {len(artifacts['isbns']) - 3} more")

        if artifacts["copyright_notices"]:
            print(f"  ©️  Copyright notices: {len(artifacts['copyright_notices'])}")

        if artifacts["library_catalog"]:
            print(f"  📖 Library catalog data: {len(artifacts['library_catalog'])}")
            for cat in artifacts["library_catalog"][:3]:
                print(f"     • {cat}")

        if artifacts["publisher_metadata"]:
            print(f"  🏢 Publisher metadata: {len(artifacts['publisher_metadata'])}")

        if artifacts["printing_codes"]:
            print(f"  🖨️  Printing codes: {len(artifacts['printing_codes'])}")

        if artifacts["page_numbers"]:
            print(f"  #️⃣  Isolated page numbers: {len(artifacts['page_numbers'])}")

    def _llm_quality_check(self, full_book: str, artifact_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Use LLM to assess research readiness and find subtle issues."""

        # Sample the text strategically (beginning, middle, end)
        text_len = len(full_book)
        sample_size = 30000  # characters per sample

        samples = []
        # Beginning
        samples.append(("beginning", full_book[:sample_size]))
        # Middle
        mid_start = (text_len // 2) - (sample_size // 2)
        samples.append(("middle", full_book[mid_start:mid_start + sample_size]))
        # End
        samples.append(("end", full_book[-sample_size:]))

        prompt = f"""You are reviewing a digitized book for RESEARCH READINESS. This text will be used in RAG systems and cited in academic work.

The book has already been processed through OCR → Correction → Structure stages.

REGEX ARTIFACT DETECTION RESULTS:
- ISBNs found: {len(artifact_analysis['artifacts']['isbns'])}
- Copyright notices: {len(artifact_analysis['artifacts']['copyright_notices'])}
- Library catalog data: {len(artifact_analysis['artifacts']['library_catalog'])}
- Publisher metadata: {len(artifact_analysis['artifacts']['publisher_metadata'])}
- Clean text percentage: {artifact_analysis['clean_percentage']}%

YOUR TASK: Review these text samples and assess RESEARCH READINESS:

SAMPLE 1 (Beginning):
{samples[0][1][:15000]}

SAMPLE 2 (Middle):
{samples[1][1][:15000]}

SAMPLE 3 (End):
{samples[2][1][:15000]}

ASSESSMENT CRITERIA:
1. **Artifact Contamination**: Beyond regex detection, are there subtle artifacts? (Headers, footers, page breaks, table formatting)
2. **Text Coherence**: Does the narrative flow properly? Are sentences complete?
3. **Research Usability**: Can this be cited and quoted reliably? Any garbled sections?
4. **OCR Quality**: Remaining errors that would confuse semantic search?

CRITICAL QUESTION: If a researcher used this text RIGHT NOW in their work, would they encounter problems?

Respond ONLY with JSON:
{{
  "research_ready": <true/false>,
  "confidence": <0.0-1.0>,
  "critical_issues": ["list of issues that BLOCK research use"],
  "minor_issues": ["issues that are annoying but don't block research"],
  "artifact_examples": ["specific artifact quotes with context"],
  "recommended_action": "PASS/WARN/FAIL with reasoning",
  "overall_assessment": "2-3 sentences on research readiness"
}}
"""

        response_text = self._call_llm(prompt)

        # Parse JSON
        try:
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            return json.loads(response_text)
        except json.JSONDecodeError as e:
            print(f"  ⚠️  Warning: Could not parse LLM response: {e}")
            return {
                "research_ready": False,
                "confidence": 0.0,
                "critical_issues": ["LLM analysis failed"],
                "minor_issues": [],
                "artifact_examples": [],
                "recommended_action": "FAIL - Analysis error",
                "overall_assessment": "Quality analysis failed to complete"
            }

    def _compile_report(self, artifact_analysis: Dict[str, Any],
                       llm_analysis: Dict[str, Any], full_text: str) -> Dict[str, Any]:
        """Compile final quality report with clear pass/fail."""

        # Calculate scores
        artifact_score = artifact_analysis["clean_percentage"]
        llm_confidence = llm_analysis.get("confidence", 0) * 100

        # Weighted average: 60% artifacts, 40% LLM assessment
        overall_score = (artifact_score * 0.6) + (llm_confidence * 0.4)

        # Determine grade and research readiness
        if overall_score >= 95 and llm_analysis.get("research_ready", False):
            grade = "A"
            status = "PASS"
            recommendation = "✅ Research-ready. Can be used immediately for citations and RAG."
        elif overall_score >= 90:
            grade = "B"
            status = "PASS"
            recommendation = "✅ Research-ready with minor caveats. Generally safe for use."
        elif overall_score >= 80:
            grade = "C"
            status = "WARN"
            recommendation = "⚠️  Usable with caution. Manual spot-checks recommended before citing."
        elif overall_score >= 70:
            grade = "D"
            status = "WARN"
            recommendation = "⚠️  Needs review. Not recommended for direct citation without verification."
        else:
            grade = "F"
            status = "FAIL"
            recommendation = "❌ NOT research-ready. Requires fixes before use."

        return {
            "scan_id": self.scan_id,
            "timestamp": datetime.now().isoformat(),
            "model": self.model,
            "research_ready_status": status,
            "overall_score": round(overall_score, 1),
            "overall_grade": grade,
            "recommendation": recommendation,
            "artifact_detection": {
                "clean_percentage": artifact_analysis["clean_percentage"],
                "total_artifacts": artifact_analysis["total_count"],
                "contaminated_chars": artifact_analysis["contaminated_chars"],
                "total_chars": artifact_analysis["total_chars"],
                "artifacts_by_type": {
                    k: len(v) if isinstance(v, list) else 0
                    for k, v in artifact_analysis["artifacts"].items()
                }
            },
            "llm_assessment": llm_analysis,
            "cost_tracking": {
                "input_tokens": self.total_input_tokens,
                "output_tokens": self.total_output_tokens,
                "total_cost_usd": round(self.total_cost_usd, 2)
            }
        }

    def _print_final_summary(self, report: Dict[str, Any]):
        """Print final quality summary."""
        print(f"  🎯 Research-Ready Status: {report['research_ready_status']}")
        print(f"  📊 Overall Score: {report['overall_score']}/100")
        print(f"  🏆 Grade: {report['overall_grade']}")
        print()
        print(f"  📝 Recommendation:")
        print(f"     {report['recommendation']}")
        print()

        llm = report['llm_assessment']
        if llm.get('critical_issues'):
            print(f"  🚨 Critical Issues:")
            for issue in llm['critical_issues']:
                print(f"     • {issue}")
            print()

        if llm.get('minor_issues'):
            print(f"  ⚠️  Minor Issues:")
            for issue in llm['minor_issues'][:5]:
                print(f"     • {issue}")
            if len(llm['minor_issues']) > 5:
                print(f"     ... and {len(llm['minor_issues']) - 5} more")
            print()

        print(f"  💰 Cost: ${report['cost_tracking']['total_cost_usd']}")

    def _call_llm(self, prompt: str) -> str:
        """Call LLM API for quality assessment."""
        # Use unified LLMClient
        messages = [{"role": "user", "content": prompt}]

        response, usage, cost = self.llm_client.call(
            self.model,
            messages,
            temperature=0.3,
            timeout=300
        )

        # Track costs
        self.total_input_tokens += usage.get('prompt_tokens', 0)
        self.total_output_tokens += usage.get('completion_tokens', 0)
        self.total_cost_usd += cost

        return response


def main():
    """Run quality review from command line."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: quality_review.py <scan_id>")
        sys.exit(1)

    scan_id = sys.argv[1]
    reviewer = QualityReview(scan_id)
    reviewer.run()


if __name__ == "__main__":
    main()
