"""
Pytest configuration for project root.

Ensures project modules can be imported in tests.
Provides global fixtures for Roosevelt test data.
"""

import sys
import pytest
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


# ============================================================================
# ROOSEVELT FIXTURES - Committed test data
# ============================================================================

@pytest.fixture(scope="session")
def roosevelt_fixtures():
    """Path to committed Roosevelt test fixtures.

    Contains 5 sample pages (10, 50, 100, 200, 500) with:
    - OCR JSON
    - Corrected JSON
    - Structured output metadata

    Size: ~50KB (committed to git)
    """
    fixture_dir = project_root / "tests" / "fixtures" / "roosevelt"
    assert fixture_dir.exists(), (
        f"Roosevelt fixtures not found at {fixture_dir}\n"
        f"Run: uv run python tests/fixtures/extract_roosevelt_fixtures.py"
    )
    return fixture_dir


@pytest.fixture(scope="session")
def roosevelt_full_book():
    """Path to full Roosevelt book (if available).

    Optional: Only available if user has processed Roosevelt.
    Tests requiring full book should use this fixture.

    Returns None if book not available.
    """
    book_dir = Path.home() / "Documents" / "book_scans" / "roosevelt-autobiography"
    return book_dir if book_dir.exists() else None
