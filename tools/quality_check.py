#!/usr/bin/env python3
"""
Quality assessment tool for processed books.

Analyzes OCR quality, correction accuracy, and structural completeness.
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from config import Config


class QualityAssessment:
    """Assess quality of processed book data."""

    def __init__(self, scan_id: str):
        self.scan_id = scan_id
        self.book_dir = Config.BOOK_STORAGE_ROOT / scan_id
        self.results = {}

    def run_full_assessment(self) -> Dict[str, Any]:
        """Run all quality checks and return comprehensive report."""
        print(f"🔍 Quality Assessment: {self.scan_id}")
        print("=" * 70)

        self.results = {
            "scan_id": self.scan_id,
            "checks": {
                "ocr": self._check_ocr_quality(),
                "correction": self._check_correction_quality(),
                "structure": self._check_structure_quality()
            }
        }

        # Calculate overall score
        self.results["overall_score"] = self._calculate_overall_score()
        self.results["quality_grade"] = self._get_quality_grade()

        return self.results

    def _check_ocr_quality(self) -> Dict[str, Any]:
        """Check OCR output quality."""
        print("\n📄 Checking OCR Quality...")

        ocr_dir = self.book_dir / "ocr"
        if not ocr_dir.exists():
            return {"status": "not_found", "score": 0}

        ocr_files = list(ocr_dir.glob("page_*.json"))
        if not ocr_files:
            return {"status": "empty", "score": 0}

        # Sample checks
        total_pages = len(ocr_files)
        contaminated_pages = 0
        low_confidence_pages = 0
        total_confidence = 0.0

        for ocr_file in ocr_files:
            try:
                with open(ocr_file) as f:
                    data = json.load(f)

                # Check for TSV contamination
                for region in data.get("regions", []):
                    if '\t' in region.get("text", ""):
                        contaminated_pages += 1
                        break

                # Check confidence
                avg_confidence = sum(
                    r.get("confidence", 0) for r in data.get("regions", [])
                ) / max(len(data.get("regions", [])), 1)

                total_confidence += avg_confidence
                if avg_confidence < 0.85:
                    low_confidence_pages += 1

            except (json.JSONDecodeError, KeyError):
                continue

        avg_confidence = total_confidence / total_pages if total_pages > 0 else 0

        result = {
            "status": "complete",
            "total_pages": total_pages,
            "contaminated_pages": contaminated_pages,
            "low_confidence_pages": low_confidence_pages,
            "average_confidence": round(avg_confidence, 3),
            "contamination_rate": round(100 * contaminated_pages / total_pages, 1) if total_pages > 0 else 0,
            "score": self._score_ocr(contaminated_pages, low_confidence_pages, total_pages, avg_confidence)
        }

        print(f"   ✓ {total_pages} pages processed")
        print(f"   ✓ Avg confidence: {result['average_confidence']:.1%}")
        print(f"   ✓ Contamination: {result['contamination_rate']:.1f}%")

        return result

    def _check_correction_quality(self) -> Dict[str, Any]:
        """Check correction stage quality."""
        print("\n🔧 Checking Correction Quality...")

        corrected_dir = self.book_dir / "corrected"
        if not corrected_dir.exists():
            return {"status": "not_found", "score": 0}

        corrected_files = list(corrected_dir.glob("page_*.json"))
        if not corrected_files:
            return {"status": "empty", "score": 0}

        total_pages = len(corrected_files)
        total_errors_found = 0
        total_errors_fixed = 0
        low_confidence_corrections = 0
        verification_failures = 0

        for corr_file in corrected_files:
            try:
                with open(corr_file) as f:
                    data = json.load(f)

                llm_proc = data.get("llm_processing", {})
                catalog = llm_proc.get("error_catalog", {})
                verification = llm_proc.get("verification", {})

                # Count errors
                errors_found = catalog.get("total_errors_found", 0)
                total_errors_found += errors_found

                # Check verification
                if verification:
                    correctly_applied = verification.get("corrections_verified", {}).get("correctly_applied", 0)
                    total_errors_fixed += correctly_applied

                    if not verification.get("all_corrections_applied", True):
                        verification_failures += 1

                # Check confidence
                for error in catalog.get("errors", []):
                    if error.get("confidence", 1.0) < 0.8:
                        low_confidence_corrections += 1

            except (json.JSONDecodeError, KeyError):
                continue

        fix_rate = (total_errors_fixed / total_errors_found * 100) if total_errors_found > 0 else 0

        result = {
            "status": "complete",
            "total_pages": total_pages,
            "total_errors_found": total_errors_found,
            "total_errors_fixed": total_errors_fixed,
            "fix_rate": round(fix_rate, 1),
            "verification_failures": verification_failures,
            "low_confidence_corrections": low_confidence_corrections,
            "avg_errors_per_page": round(total_errors_found / total_pages, 1) if total_pages > 0 else 0,
            "score": self._score_corrections(fix_rate, verification_failures, total_pages)
        }

        print(f"   ✓ {total_errors_found} errors found across {total_pages} pages")
        print(f"   ✓ {total_errors_fixed} errors fixed ({result['fix_rate']:.1f}%)")
        print(f"   ✓ {verification_failures} verification failures")

        return result

    def _check_structure_quality(self) -> Dict[str, Any]:
        """Check structured output quality."""
        print("\n📚 Checking Structure Quality...")

        structured_dir = self.book_dir / "structured"
        if not structured_dir.exists():
            return {"status": "not_found", "score": 0}

        metadata_file = structured_dir / "metadata.json"
        if not metadata_file.exists():
            return {"status": "incomplete", "score": 0}

        try:
            with open(metadata_file) as f:
                metadata = json.load(f)

            chapters_dir = structured_dir / "chapters"
            chunks_dir = structured_dir / "chunks"

            chapter_count = len(list(chapters_dir.glob("chapter_*.json"))) if chapters_dir.exists() else 0
            chunk_count = len(list(chunks_dir.glob("chunk_*.json"))) if chunks_dir.exists() else 0

            book_info = metadata.get("book_info", {})
            total_pages = book_info.get("total_pages", 0)

            result = {
                "status": "complete",
                "chapter_count": chapter_count,
                "chunk_count": chunk_count,
                "total_pages": total_pages,
                "pages_per_chapter": round(total_pages / chapter_count, 1) if chapter_count > 0 else 0,
                "pages_per_chunk": round(total_pages / chunk_count, 1) if chunk_count > 0 else 0,
                "has_full_markdown": (structured_dir / "full_book.md").exists(),
                "score": self._score_structure(chapter_count, chunk_count, total_pages)
            }

            print(f"   ✓ {chapter_count} chapters, {chunk_count} chunks")
            print(f"   ✓ {total_pages} pages total")
            print(f"   ✓ Full markdown: {'Yes' if result['has_full_markdown'] else 'No'}")

            return result

        except (json.JSONDecodeError, KeyError) as e:
            return {"status": "error", "error": str(e), "score": 0}

    def _score_ocr(self, contaminated: int, low_conf: int, total: int, avg_conf: float) -> float:
        """Score OCR quality (0-100)."""
        if total == 0:
            return 0

        # Penalize contamination heavily
        contamination_penalty = (contaminated / total) * 50
        # Penalize low confidence pages
        confidence_penalty = (low_conf / total) * 30
        # Reward high average confidence
        confidence_bonus = avg_conf * 20

        score = 100 - contamination_penalty - confidence_penalty + confidence_bonus
        return max(0, min(100, score))

    def _score_corrections(self, fix_rate: float, failures: int, total: int) -> float:
        """Score correction quality (0-100)."""
        if total == 0:
            return 0

        # Base score from fix rate
        base_score = fix_rate

        # Penalize verification failures
        failure_penalty = (failures / total) * 30

        score = base_score - failure_penalty
        return max(0, min(100, score))

    def _score_structure(self, chapters: int, chunks: int, pages: int) -> float:
        """Score structure quality (0-100)."""
        if pages == 0:
            return 0

        score = 0

        # Has chapters
        if chapters > 0:
            score += 40
            # Reasonable chapter breakdown (5-30 pages per chapter)
            pages_per_chapter = pages / chapters
            if 5 <= pages_per_chapter <= 30:
                score += 20

        # Has chunks
        if chunks > 0:
            score += 30
            # Reasonable chunk size (~5 pages)
            pages_per_chunk = pages / chunks
            if 3 <= pages_per_chunk <= 7:
                score += 10

        return score

    def _calculate_overall_score(self) -> float:
        """Calculate weighted overall score."""
        weights = {
            "ocr": 0.3,
            "correction": 0.4,
            "structure": 0.3
        }

        total_score = 0
        for stage, weight in weights.items():
            stage_score = self.results["checks"][stage].get("score", 0)
            total_score += stage_score * weight

        return round(total_score, 1)

    def _get_quality_grade(self) -> str:
        """Get letter grade based on overall score."""
        score = self.results["overall_score"]
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"

    def print_report(self):
        """Print formatted quality report."""
        print("\n" + "=" * 70)
        print("📊 QUALITY ASSESSMENT REPORT")
        print("=" * 70)
        print(f"\nScan ID: {self.scan_id}")
        print(f"Overall Score: {self.results['overall_score']}/100")
        print(f"Quality Grade: {self.results['quality_grade']}")

        print("\n📄 OCR Quality:")
        ocr = self.results["checks"]["ocr"]
        print(f"   Score: {ocr.get('score', 0):.1f}/100")
        print(f"   Status: {ocr.get('status')}")
        if ocr.get("status") == "complete":
            print(f"   Pages: {ocr.get('total_pages')}")
            print(f"   Avg Confidence: {ocr.get('average_confidence', 0):.1%}")
            print(f"   Contamination: {ocr.get('contamination_rate', 0):.1f}%")

        print("\n🔧 Correction Quality:")
        corr = self.results["checks"]["correction"]
        print(f"   Score: {corr.get('score', 0):.1f}/100")
        print(f"   Status: {corr.get('status')}")
        if corr.get("status") == "complete":
            print(f"   Errors Found: {corr.get('total_errors_found')}")
            print(f"   Errors Fixed: {corr.get('total_errors_fixed')} ({corr.get('fix_rate')}%)")
            print(f"   Avg Errors/Page: {corr.get('avg_errors_per_page')}")

        print("\n📚 Structure Quality:")
        struct = self.results["checks"]["structure"]
        print(f"   Score: {struct.get('score', 0):.1f}/100")
        print(f"   Status: {struct.get('status')}")
        if struct.get("status") == "complete":
            print(f"   Chapters: {struct.get('chapter_count')}")
            print(f"   Chunks: {struct.get('chunk_count')}")
            print(f"   Pages: {struct.get('total_pages')}")

        print("\n" + "=" * 70)


def main():
    """Run quality assessment from command line."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: quality_check.py <scan_id>")
        sys.exit(1)

    scan_id = sys.argv[1]
    qa = QualityAssessment(scan_id)
    qa.run_full_assessment()
    qa.print_report()


if __name__ == "__main__":
    main()
