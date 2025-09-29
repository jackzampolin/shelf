#!/usr/bin/env python3
"""
Handle pages flagged for review in the LLM processing pipeline.

Workflow:
1. Load all pages from needs_review/
2. Categorize by issue type (low confidence, incomplete corrections, JSON errors)
3. Provide tools for:
   - Viewing flagged pages side-by-side with originals
   - Re-running Agent 1 with enhanced prompts
   - Generating review reports
   - Accepting pages as-is with metadata flags
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple


class ReviewHandler:
    """Handle review of flagged pages."""

    def __init__(self, book_slug: str):
        self.book_slug = book_slug
        self.base_dir = Path.home() / "Documents" / "book_scans" / book_slug
        self.needs_review_dir = self.base_dir / "needs_review"
        self.reviewed_dir = self.base_dir / "reviewed"
        self.reviewed_dir.mkdir(exist_ok=True)

    def load_flagged_pages(self) -> List[Dict]:
        """Load all pages flagged for review."""
        flagged = []

        for review_file in sorted(self.needs_review_dir.glob("page_*.json")):
            with open(review_file) as f:
                data = json.load(f)
                flagged.append(data)

        return flagged

    def categorize_issues(self, flagged_pages: List[Dict]) -> Dict[str, List[Dict]]:
        """Categorize flagged pages by issue type."""
        categories = {
            "low_confidence": [],
            "incomplete_corrections": [],
            "json_errors": [],
            "other": []
        }

        for page in flagged_pages:
            page_num = page.get("page_number")
            confidence = page.get("confidence_score", 1.0)
            verification = page.get("verification", {})
            error_type = page.get("error_type", "")

            if error_type == "json_parse_error":
                categories["json_errors"].append(page)
            elif confidence < 0.8:
                categories["low_confidence"].append(page)
            elif not verification.get("all_corrections_applied", True):
                categories["incomplete_corrections"].append(page)
            else:
                categories["other"].append(page)

        return categories

    def generate_review_report(self) -> str:
        """Generate human-readable review report."""
        flagged = self.load_flagged_pages()
        categories = self.categorize_issues(flagged)

        report = []
        report.append("=" * 70)
        report.append("📋 PAGES FLAGGED FOR REVIEW")
        report.append("=" * 70)
        report.append(f"\nTotal flagged pages: {len(flagged)}")
        report.append(f"Book: {self.book_slug}")
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        # Summary by category
        report.append("\n📊 Issues by Category:")
        report.append(f"   Low confidence (< 0.8):      {len(categories['low_confidence'])}")
        report.append(f"   Incomplete corrections:      {len(categories['incomplete_corrections'])}")
        report.append(f"   JSON parse errors:           {len(categories['json_errors'])}")
        report.append(f"   Other:                       {len(categories['other'])}")

        # Detailed breakdown
        for category_name, pages in categories.items():
            if not pages:
                continue

            report.append(f"\n\n{'=' * 70}")
            report.append(f"Category: {category_name.replace('_', ' ').title()}")
            report.append("=" * 70)

            for page in pages:
                page_num = page.get("page_number")
                confidence = page.get("confidence_score", 1.0)
                verification = page.get("verification", {})
                review_reason = verification.get("review_reason", "No reason provided")

                report.append(f"\n📄 Page {page_num}")
                report.append(f"   Confidence: {confidence:.2f}")
                report.append(f"   Reason: {review_reason}")

                # Show correction stats if available
                corr_verified = verification.get("corrections_verified", {})
                if corr_verified:
                    correct = corr_verified.get("correctly_applied", 0)
                    incorrect = corr_verified.get("incorrectly_applied", 0)
                    missed = corr_verified.get("missed", 0)
                    report.append(f"   Corrections: {correct} applied, {missed} missed, {incorrect} incorrect")

                report.append(f"   File: needs_review/page_{page_num:04d}.json")

        report.append("\n\n" + "=" * 70)
        report.append("📝 Recommended Actions:")
        report.append("=" * 70)
        report.append("\n1. Review low confidence pages manually against physical book")
        report.append("2. Re-run Agent 1 on incomplete correction pages")
        report.append("3. Inspect JSON error pages for systematic issues")
        report.append("4. Accept remaining pages with metadata flags")
        report.append("\nUse book_review_handler.py to process flagged pages.")
        report.append("")

        return "\n".join(report)

    def export_review_list_for_manual_review(self) -> str:
        """Export simple checklist for manual review."""
        flagged = self.load_flagged_pages()

        checklist = []
        checklist.append("# Manual Review Checklist")
        checklist.append(f"# Book: {self.book_slug}")
        checklist.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d')}")
        checklist.append("")
        checklist.append("Review each page against the physical book and mark status.")
        checklist.append("")

        for page in sorted(flagged, key=lambda p: p.get("page_number", 0)):
            page_num = page.get("page_number")
            confidence = page.get("confidence_score", 1.0)
            verification = page.get("verification", {})
            reason = verification.get("review_reason", "Needs review")

            # Truncate reason for checklist
            reason_short = (reason[:70] + "...") if len(reason) > 70 else reason

            checklist.append(f"## Page {page_num} (confidence: {confidence:.2f})")
            checklist.append(f"**Issue**: {reason_short}")
            checklist.append("")
            checklist.append("- [ ] Reviewed against physical book")
            checklist.append("- [ ] Corrections verified")
            checklist.append("- [ ] Notes: _________________________")
            checklist.append("")

        return "\n".join(checklist)

    def mark_page_accepted(self, page_num: int, notes: str = ""):
        """Mark a page as accepted with optional notes."""
        review_file = self.needs_review_dir / f"page_{page_num:04d}.json"

        if not review_file.exists():
            print(f"❌ Page {page_num} not in review queue")
            return False

        with open(review_file) as f:
            data = json.load(f)

        # Add acceptance metadata
        data["review_status"] = "accepted"
        data["review_timestamp"] = datetime.now().isoformat()
        data["review_notes"] = notes

        # Save to reviewed directory
        output_file = self.reviewed_dir / f"page_{page_num:04d}.json"
        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"✅ Page {page_num} marked as accepted")
        return True

    def accept_all_with_metadata(self):
        """Accept all flagged pages, keeping metadata flags."""
        flagged = self.load_flagged_pages()

        print(f"Accepting {len(flagged)} flagged pages with metadata...")

        for page in flagged:
            page_num = page.get("page_number")
            reason = page.get("verification", {}).get("review_reason", "Flagged")
            self.mark_page_accepted(page_num, f"Auto-accepted: {reason}")

        print(f"\n✅ All {len(flagged)} pages accepted with metadata flags")
        print(f"   Files saved to: {self.reviewed_dir}")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python book_review_handler.py <book-slug> report")
        print("  python book_review_handler.py <book-slug> checklist")
        print("  python book_review_handler.py <book-slug> accept-all")
        print("  python book_review_handler.py <book-slug> accept <page_num> [notes]")
        print("\nExamples:")
        print("  python book_review_handler.py The-Accidental-President report")
        print("  python book_review_handler.py The-Accidental-President checklist > review.md")
        print("  python book_review_handler.py The-Accidental-President accept-all")
        print("  python book_review_handler.py The-Accidental-President accept 4 'Verified against book'")
        sys.exit(1)

    book_slug = sys.argv[1]
    command = sys.argv[2] if len(sys.argv) > 2 else "report"

    handler = ReviewHandler(book_slug)

    if command == "report":
        print(handler.generate_review_report())

    elif command == "checklist":
        print(handler.export_review_list_for_manual_review())

    elif command == "accept-all":
        handler.accept_all_with_metadata()

    elif command == "accept":
        if len(sys.argv) < 4:
            print("Error: page number required")
            sys.exit(1)
        page_num = int(sys.argv[3])
        notes = sys.argv[4] if len(sys.argv) > 4 else ""
        handler.mark_page_accepted(page_num, notes)

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()