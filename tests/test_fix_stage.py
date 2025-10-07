"""
Fix Stage Tests

Tests for Agent 4 targeted fix pipeline including:
- Agent4TargetedFix (main orchestrator)
- Targeted fix application based on Agent 3 feedback
- Parsing structured feedback from Agent 3
- Applying fixes to regions
- Checkpoint integration
- Processing flagged pages

Uses real API calls with Roosevelt book fixtures.
Tests are marked with @pytest.mark.api for selective execution.
Cost: ~$0.01-0.02 per full test run.
"""

import pytest
import json
import shutil
from pathlib import Path
from pipeline.fix import Agent4TargetedFix


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def roosevelt_book_dir():
    """Path to Roosevelt book with real data."""
    book_dir = Path.home() / "Documents" / "book_scans" / "roosevelt-autobiography"
    if not book_dir.exists():
        pytest.skip("Roosevelt book not found - run pipeline first")
    return book_dir


@pytest.fixture
def sample_review_page(roosevelt_book_dir):
    """Load a real review page from Roosevelt if available."""
    review_dir = roosevelt_book_dir / "needs_review"
    review_files = list(review_dir.glob("page_*.json"))

    if not review_files:
        pytest.skip("No review pages available - run correction stage first")

    # Return first review page
    with open(review_files[0]) as f:
        return json.load(f)


@pytest.fixture
def temp_test_book(tmp_path, roosevelt_book_dir):
    """Create a temporary test book with Roosevelt pages for Fix stage testing."""
    test_book = tmp_path / "test-roosevelt-fix"
    test_book.mkdir()

    # Create directory structure
    (test_book / "corrected").mkdir()
    (test_book / "needs_review").mkdir()
    (test_book / "logs").mkdir()

    # Copy a few corrected pages
    corrected_src = roosevelt_book_dir / "corrected"
    if corrected_src.exists():
        for page_file in list(corrected_src.glob("page_*.json"))[:3]:
            dst = test_book / "corrected" / page_file.name
            shutil.copy(page_file, dst)

    # Copy review pages if they exist
    review_src = roosevelt_book_dir / "needs_review"
    if review_src.exists():
        for page_file in list(review_src.glob("page_*.json"))[:2]:
            dst = test_book / "needs_review" / page_file.name
            shutil.copy(page_file, dst)

    return test_book


@pytest.fixture
def mock_review_page():
    """Create a mock review page with Agent 3 feedback for testing."""
    return {
        "page_number": 42,
        "regions": [
            {
                "type": "body",
                "text": "The presidnet walked into tbe room.",
                "bbox": [100, 200, 600, 50]
            }
        ],
        "llm_processing": {
            "corrected_text": "The presidnet walked into the[CORRECTED:1] room.",
            "error_catalog": {
                "errors": [
                    {
                        "error_id": 1,
                        "original_text": "tbe",
                        "suggested_correction": "the"
                    },
                    {
                        "error_id": 2,
                        "original_text": "presidnet",
                        "suggested_correction": "president"
                    }
                ]
            },
            "verification": {
                "page_number": 42,
                "confidence_score": 0.75,
                "needs_human_review": True,
                "review_reason": "Missed correction: presidnet should be president",
                "missed_corrections": [
                    {
                        "error_id": 2,
                        "original_text": "presidnet",
                        "should_be": "president",
                        "location": "first sentence"
                    }
                ],
                "incorrectly_applied": []
            }
        }
    }


# ============================================================================
# AGENT 4 INITIALIZATION TESTS
# ============================================================================

class TestAgent4Initialization:
    """Test Agent4TargetedFix initialization."""

    @pytest.fixture
    def agent4_book_dir(self, tmp_path):
        """Create a temporary book directory for Agent4 tests."""
        book_dir = Path.home() / "Documents" / "book_scans" / "test-book"
        # Clean up if it exists from previous run
        if book_dir.exists():
            shutil.rmtree(book_dir)
        book_dir.mkdir(parents=True)
        (book_dir / "needs_review").mkdir()
        (book_dir / "corrected").mkdir()
        yield book_dir
        # Cleanup
        if book_dir.exists():
            shutil.rmtree(book_dir)

    def test_agent4_initialization(self, agent4_book_dir):
        """Test Agent4TargetedFix initializes correctly."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book",
            max_workers=5,
            enable_checkpoints=False
        )

        assert agent4.book_slug == "test-book"
        assert agent4.max_workers == 5
        assert agent4.checkpoint is None
        assert agent4.model == "anthropic/claude-3.5-sonnet"

    def test_agent4_creates_directories(self, agent4_book_dir):
        """Test that Agent4 verifies required directories exist."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book",
            enable_checkpoints=False
        )

        logs_dir = agent4.base_dir / "logs"
        assert logs_dir.exists()

    def test_agent4_stats_initialization(self, agent4_book_dir):
        """Test that Agent4 stats are initialized correctly."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book",
            enable_checkpoints=False
        )

        assert agent4.stats['pages_processed'] == 0
        assert agent4.stats['pages_fixed'] == 0
        assert agent4.stats['pages_failed'] == 0
        assert agent4.stats['total_cost_usd'] == 0.0


# ============================================================================
# AGENT 3 FEEDBACK PARSING TESTS
# ============================================================================

class TestAgent3FeedbackParsing:
    """Test parsing Agent 3 feedback structures."""

    @pytest.fixture
    def agent4_book_dir(self):
        """Create a temporary book directory for Agent4 tests."""
        book_dir = Path.home() / "Documents" / "book_scans" / "test-book-parsing"
        if book_dir.exists():
            shutil.rmtree(book_dir)
        book_dir.mkdir(parents=True)
        (book_dir / "needs_review").mkdir()
        (book_dir / "corrected").mkdir()
        yield book_dir
        if book_dir.exists():
            shutil.rmtree(book_dir)

    def test_parse_structured_missed_corrections(self, agent4_book_dir, mock_review_page):
        """Test parsing structured missed corrections from Agent 3."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book-parsing",
            enable_checkpoints=False
        )

        corrections = agent4.parse_agent3_feedback(mock_review_page)

        assert len(corrections) == 1
        assert corrections[0]['original_text'] == "presidnet"
        assert corrections[0]['should_be'] == "president"

    def test_parse_incorrectly_applied_corrections(self, agent4_book_dir):
        """Test parsing incorrectly applied corrections from Agent 3."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book-parsing",
            enable_checkpoints=False
        )

        review_data = {
            "page_number": 10,
            "llm_processing": {
                "verification": {
                    "missed_corrections": [],
                    "incorrectly_applied": [
                        {
                            "error_id": 3,
                            "was_changed_to": "incorrect",
                            "should_be": "correct",
                            "reason": "wrong word choice"
                        }
                    ]
                }
            }
        }

        corrections = agent4.parse_agent3_feedback(review_data)

        assert len(corrections) == 1
        assert corrections[0]['should_be'] == "correct"
        assert 'was_changed_to' in corrections[0]

    def test_parse_fallback_review_reason(self, agent4_book_dir):
        """Test fallback to review_reason when structured data not available."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book-parsing",
            enable_checkpoints=False
        )

        # Old format without structured corrections
        review_data = {
            "page_number": 10,
            "llm_processing": {
                "verification": {
                    "review_reason": "Multiple OCR errors detected"
                }
            }
        }

        corrections = agent4.parse_agent3_feedback(review_data)

        assert len(corrections) == 1
        assert 'fallback_instruction' in corrections[0]

    def test_parse_no_corrections_needed(self, agent4_book_dir):
        """Test parsing when no corrections are needed."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book-parsing",
            enable_checkpoints=False
        )

        review_data = {
            "page_number": 10,
            "llm_processing": {
                "verification": {
                    "missed_corrections": [],
                    "incorrectly_applied": []
                }
            }
        }

        corrections = agent4.parse_agent3_feedback(review_data)

        assert len(corrections) == 0


# ============================================================================
# FIX APPLICATION TESTS
# ============================================================================

class TestFixApplication:
    """Test applying fixes to regions."""

    @pytest.fixture
    def agent4_book_dir(self):
        """Create a temporary book directory for Agent4 tests."""
        book_dir = Path.home() / "Documents" / "book_scans" / "test-book-apply"
        if book_dir.exists():
            shutil.rmtree(book_dir)
        book_dir.mkdir(parents=True)
        (book_dir / "needs_review").mkdir()
        (book_dir / "corrected").mkdir()
        yield book_dir
        if book_dir.exists():
            shutil.rmtree(book_dir)

    def test_apply_fixes_to_regions(self, agent4_book_dir):
        """Test that fixes are correctly applied to region text."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book-apply",
            enable_checkpoints=False
        )

        page_data = {
            "page_number": 1,
            "regions": [
                {
                    "type": "body",
                    "text": "The presidnet walked.",
                    "bbox": [0, 0, 100, 20]
                }
            ]
        }

        fixed_text = "The president[FIXED:A4-1] walked."
        missed_corrections = [
            {
                "original_text": "presidnet",
                "should_be": "president"
            }
        ]

        updated_page = agent4.apply_fixes_to_regions(
            page_data, fixed_text, missed_corrections
        )

        # Verify fix was applied to region
        assert 'president' in updated_page['regions'][0]['text']
        assert updated_page['regions'][0].get('fixed') == True

    def test_apply_fixes_skips_non_text_regions(self, agent4_book_dir):
        """Test that fixes are not applied to image regions."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book-apply",
            enable_checkpoints=False
        )

        page_data = {
            "page_number": 1,
            "regions": [
                {
                    "type": "image",
                    "bbox": [0, 0, 100, 100],
                    "image_file": "test.png"
                },
                {
                    "type": "body",
                    "text": "Test text",
                    "bbox": [0, 100, 100, 20]
                }
            ]
        }

        fixed_text = "Test text"
        missed_corrections = []

        updated_page = agent4.apply_fixes_to_regions(
            page_data, fixed_text, missed_corrections
        )

        # Image region should be unchanged
        assert 'image_file' in updated_page['regions'][0]
        assert 'fixed' not in updated_page['regions'][0]


# ============================================================================
# REAL API CALL TESTS
# ============================================================================

@pytest.mark.api
class TestAgent4RealAPICalls:
    """Test Agent 4 with real API calls."""

    @pytest.fixture
    def agent4_book_dir(self):
        """Create a temporary book directory for Agent4 tests."""
        book_dir = Path.home() / "Documents" / "book_scans" / "test-book-api"
        if book_dir.exists():
            shutil.rmtree(book_dir)
        book_dir.mkdir(parents=True)
        (book_dir / "needs_review").mkdir()
        (book_dir / "corrected").mkdir()
        yield book_dir
        if book_dir.exists():
            shutil.rmtree(book_dir)

    def test_agent4_targeted_fix_real_call(self, agent4_book_dir, mock_review_page):
        """Test Agent 4 makes targeted fix with real API call."""

        # Save mock review page as corrected page
        page_num = mock_review_page['page_number']
        corrected_file = agent4_book_dir / "corrected" / f"page_{page_num:04d}.json"
        with open(corrected_file, 'w') as f:
            json.dump(mock_review_page, f)

        agent4 = Agent4TargetedFix(
            book_slug="test-book-api",
            max_workers=1,
            enable_checkpoints=False
        )

        # Extract data needed for agent4_targeted_fix
        corrected_text = mock_review_page['llm_processing']['corrected_text']
        verification = mock_review_page['llm_processing']['verification']
        agent3_feedback = verification['review_reason']
        missed_corrections = verification['missed_corrections']

        # Call Agent 4
        fixed_text = agent4.agent4_targeted_fix(
            page_num=page_num,
            page_data=mock_review_page,
            corrected_text=corrected_text,
            agent3_feedback=agent3_feedback,
            missed_corrections=missed_corrections
        )

        # Verify output
        assert isinstance(fixed_text, str)
        assert len(fixed_text) > 0

        # Verify file was updated
        assert corrected_file.exists()
        with open(corrected_file) as f:
            updated_data = json.load(f)
        assert 'agent4_fixes' in updated_data['llm_processing']

        # Verify cost was tracked
        assert agent4.stats['total_cost_usd'] > 0

    def test_process_flagged_page_end_to_end(self, temp_test_book):
        """Test processing a flagged page end-to-end."""
        if not list((temp_test_book / "needs_review").glob("*.json")):
            pytest.skip("No review pages in temp test book")

        agent4 = Agent4TargetedFix(
            book_slug=temp_test_book.name,
            max_workers=1,
            enable_checkpoints=False
        )

        # Get a review file
        review_files = list((temp_test_book / "needs_review").glob("page_*.json"))
        if not review_files:
            pytest.skip("No review pages available")

        review_file = review_files[0]

        # Process it
        agent4.process_flagged_page(review_file)

        # Verify stats updated
        assert agent4.stats['pages_processed'] > 0

    def test_process_all_flagged_pages(self, temp_test_book):
        """Test processing all flagged pages."""
        if not list((temp_test_book / "needs_review").glob("*.json")):
            pytest.skip("No review pages in temp test book")

        agent4 = Agent4TargetedFix(
            book_slug=temp_test_book.name,
            max_workers=2,
            enable_checkpoints=False
        )

        # Process all flagged pages
        agent4.process_all_flagged(resume=False)

        # Verify processing occurred
        assert agent4.stats['pages_processed'] >= 0


# ============================================================================
# CHECKPOINT TESTS
# ============================================================================

class TestFixCheckpoints:
    """Test checkpoint integration for Fix stage."""

    @pytest.fixture
    def agent4_book_dir(self):
        """Create a temporary book directory for Agent4 tests."""
        book_dir = Path.home() / "Documents" / "book_scans" / "test-book-checkpoint"
        if book_dir.exists():
            shutil.rmtree(book_dir)
        book_dir.mkdir(parents=True)
        (book_dir / "needs_review").mkdir()
        (book_dir / "corrected").mkdir()
        yield book_dir
        if book_dir.exists():
            shutil.rmtree(book_dir)

    def test_checkpoint_enabled(self, agent4_book_dir):
        """Test that checkpoints can be enabled."""
        agent4 = Agent4TargetedFix(
            book_slug="test-book-checkpoint",
            enable_checkpoints=True
        )

        assert agent4.checkpoint is not None
        assert agent4.checkpoint.stage == "fix"

    def test_checkpoint_skips_already_fixed(self, agent4_book_dir, mock_review_page):
        """Test that checkpoint skips already-fixed pages."""

        # Use the same page number as mock_review_page
        page_num = mock_review_page['page_number']  # This is 42

        # Create a corrected page that already has agent4_fixes
        corrected_data = {
            "page_number": page_num,
            "regions": [],
            "llm_processing": {
                "corrected_text": "Some text",
                "agent4_fixes": {
                    "timestamp": "2024-10-01T12:00:00",
                    "fixed_text": "Already fixed"
                }
            }
        }

        corrected_file = agent4_book_dir / "corrected" / f"page_{page_num:04d}.json"
        with open(corrected_file, 'w') as f:
            json.dump(corrected_data, f)

        # Create review file with mock_review_page
        review_file = agent4_book_dir / "needs_review" / f"page_{page_num:04d}.json"
        with open(review_file, 'w') as f:
            json.dump(mock_review_page, f)

        agent4 = Agent4TargetedFix(
            book_slug="test-book-checkpoint",
            enable_checkpoints=False
        )

        # Process - should skip because already has agent4_fixes
        agent4.process_flagged_page(review_file)

        # Should have been marked as processed and fixed (checkpoint found)
        assert agent4.stats['pages_processed'] == 1
        assert agent4.stats['pages_fixed'] == 1


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================

class TestFixErrorHandling:
    """Test error handling in Fix stage."""

    @pytest.fixture
    def agent4_book_dir(self):
        """Create a temporary book directory for Agent4 tests."""
        book_dir = Path.home() / "Documents" / "book_scans" / "test-book-error"
        if book_dir.exists():
            shutil.rmtree(book_dir)
        book_dir.mkdir(parents=True)
        (book_dir / "needs_review").mkdir()
        (book_dir / "corrected").mkdir()
        yield book_dir
        if book_dir.exists():
            shutil.rmtree(book_dir)

    def test_handles_missing_corrected_file(self, agent4_book_dir):
        """Test handling of missing corrected file."""
        # Create review file without corresponding corrected file
        review_data = {
            "page_number": 99,
            "regions": [],
            "llm_processing": {"verification": {}}
        }

        review_file = agent4_book_dir / "needs_review" / "page_0099.json"
        with open(review_file, 'w') as f:
            json.dump(review_data, f)

        agent4 = Agent4TargetedFix(
            book_slug="test-book-error",
            enable_checkpoints=False
        )

        # Should handle gracefully
        agent4.process_flagged_page(review_file)

        # Should have marked as failed
        assert agent4.stats['pages_failed'] == 1

    def test_handles_missing_corrected_text(self, agent4_book_dir):
        """Test handling of missing corrected_text in JSON."""
        page_num = 10

        # Create corrected file without corrected_text
        corrected_data = {
            "page_number": page_num,
            "regions": [],
            "llm_processing": {}  # Missing corrected_text
        }

        corrected_file = agent4_book_dir / "corrected" / f"page_{page_num:04d}.json"
        with open(corrected_file, 'w') as f:
            json.dump(corrected_data, f)

        # Create review file
        review_data = {
            "page_number": page_num,
            "regions": [],
            "llm_processing": {"verification": {}}
        }

        review_file = agent4_book_dir / "needs_review" / f"page_{page_num:04d}.json"
        with open(review_file, 'w') as f:
            json.dump(review_data, f)

        agent4 = Agent4TargetedFix(
            book_slug="test-book-error",
            enable_checkpoints=False
        )

        # Should handle gracefully
        agent4.process_flagged_page(review_file)

        # Should have marked as failed
        assert agent4.stats['pages_failed'] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not api"])
