"""
Tests for infra/pipeline/status/phase_tracker.py and multi_phase.py

Key behaviors to verify:
1. PhaseStatusTracker tracks items via discoverer/validator
2. Status transitions: not_started -> in_progress -> completed
3. MultiPhaseStatusTracker manages multiple phases
4. Metrics rollup across phases
"""

import json
import pytest
from pathlib import Path

from infra.pipeline.status.phase_tracker import PhaseStatusTracker
from infra.pipeline.status.multi_phase import MultiPhaseStatusTracker


def simple_discoverer(output_dir: Path):
    """Discover items 1-5 (simulating page numbers)."""
    return [1, 2, 3, 4, 5]


def file_validator(item, output_dir: Path):
    """Check if output file exists for this item."""
    return (output_dir / f"page_{item:04d}.json").exists()


def create_output_file(output_dir: Path, item: int):
    """Helper to create an output file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"page_{item:04d}.json"
    file_path.write_text(json.dumps({"item": item}))


class TestPhaseStatusTrackerBasics:
    """Test basic PhaseStatusTracker operations."""

    def test_not_started_status(self, stage_storage):
        """New tracker with no completed items should be not_started."""
        tracker = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="test-phase",
            discoverer=simple_discoverer,
            validator=file_validator,
            run_fn=lambda t: None
        )

        status = tracker.get_status()

        assert status["status"] == "not_started"
        assert status["progress"]["total_items"] == 5
        assert status["progress"]["completed_items"] == 0

    def test_in_progress_status(self, stage_storage):
        """Tracker with some completed items should be in_progress."""
        tracker = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="test-phase",
            discoverer=simple_discoverer,
            validator=file_validator,
            run_fn=lambda t: None
        )

        # Complete some items
        create_output_file(tracker.phase_dir, 1)
        create_output_file(tracker.phase_dir, 2)

        status = tracker.get_status()

        assert status["status"] == "in_progress"
        assert status["progress"]["completed_items"] == 2
        assert status["progress"]["remaining_items"] == [3, 4, 5]

    def test_completed_status(self, stage_storage):
        """Tracker with all items complete should be completed."""
        tracker = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="test-phase",
            discoverer=simple_discoverer,
            validator=file_validator,
            run_fn=lambda t: None
        )

        # Complete all items
        for i in [1, 2, 3, 4, 5]:
            create_output_file(tracker.phase_dir, i)

        status = tracker.get_status()

        assert status["status"] == "completed"
        assert status["progress"]["completed_items"] == 5
        assert status["progress"]["remaining_items"] == []

    def test_is_completed(self, stage_storage):
        """is_completed should return True when all items done."""
        tracker = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="test-phase",
            discoverer=simple_discoverer,
            validator=file_validator,
            run_fn=lambda t: None
        )

        assert tracker.is_completed() is False

        # Complete all items
        for i in [1, 2, 3, 4, 5]:
            create_output_file(tracker.phase_dir, i)

        assert tracker.is_completed() is True


class TestPhaseStatusTrackerRemaining:
    """Test remaining items tracking."""

    def test_get_remaining_items(self, stage_storage):
        """get_remaining_items should return uncompleted items."""
        tracker = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="test-phase",
            discoverer=simple_discoverer,
            validator=file_validator,
            run_fn=lambda t: None
        )

        # Complete items 1 and 3
        create_output_file(tracker.phase_dir, 1)
        create_output_file(tracker.phase_dir, 3)

        remaining = tracker.get_remaining_items()

        assert remaining == [2, 4, 5]


class TestPhaseStatusTrackerSubdir:
    """Test use_subdir option."""

    def test_use_subdir_creates_nested_dir(self, stage_storage):
        """use_subdir=True should create phase_name subdirectory."""
        tracker = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="nested-phase",
            discoverer=simple_discoverer,
            validator=file_validator,
            run_fn=lambda t: None,
            use_subdir=True
        )

        # phase_dir should be output_dir/nested-phase
        expected_dir = stage_storage.output_dir / "nested-phase"
        assert tracker.phase_dir == expected_dir


class TestPhaseStatusTrackerRun:
    """Test run functionality."""

    def test_run_calls_run_fn(self, stage_storage):
        """run() should call the provided run_fn."""
        call_tracker = {"called": False}

        def my_run_fn(tracker):
            call_tracker["called"] = True

        tracker = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="run-test",
            discoverer=simple_discoverer,
            validator=file_validator,
            run_fn=my_run_fn
        )

        tracker.run()

        assert call_tracker["called"] is True

    def test_run_passes_kwargs(self, stage_storage):
        """run() should pass run_kwargs to run_fn."""
        received_kwargs = {}

        def my_run_fn(tracker, **kwargs):
            received_kwargs.update(kwargs)

        tracker = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="kwargs-test",
            discoverer=simple_discoverer,
            validator=file_validator,
            run_fn=my_run_fn,
            run_kwargs={"batch_size": 10, "parallel": True}
        )

        tracker.run()

        assert received_kwargs["batch_size"] == 10
        assert received_kwargs["parallel"] is True


class TestMultiPhaseStatusTracker:
    """Test MultiPhaseStatusTracker."""

    def create_phase_tracker(self, stage_storage, name, items):
        """Helper to create a PhaseStatusTracker with custom items."""
        def discoverer(output_dir):
            return items

        return PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name=name,
            discoverer=discoverer,
            validator=file_validator,
            run_fn=lambda t: None,
            use_subdir=True
        )

    def test_not_started_when_no_phases_complete(self, stage_storage):
        """MultiPhaseStatusTracker should be not_started when no phases done."""
        phase1 = self.create_phase_tracker(stage_storage, "phase1", [1, 2])
        phase2 = self.create_phase_tracker(stage_storage, "phase2", [1, 2])

        multi = MultiPhaseStatusTracker(stage_storage, [phase1, phase2])

        status = multi.get_status()

        assert status["status"] == "not_started"
        assert status["progress"]["total_phases"] == 2
        assert status["progress"]["completed_phases"] == []

    def test_in_progress_when_some_phases_complete(self, stage_storage):
        """MultiPhaseStatusTracker should be in_progress when some phases done."""
        phase1 = self.create_phase_tracker(stage_storage, "phase1", [1, 2])
        phase2 = self.create_phase_tracker(stage_storage, "phase2", [1, 2])

        # Complete phase1
        create_output_file(phase1.phase_dir, 1)
        create_output_file(phase1.phase_dir, 2)

        multi = MultiPhaseStatusTracker(stage_storage, [phase1, phase2])

        status = multi.get_status()

        assert status["status"] == "in_progress_phase2"
        assert status["progress"]["completed_phases"] == ["phase1"]
        assert status["progress"]["current_phase"] == "phase2"

    def test_completed_when_all_phases_complete(self, stage_storage):
        """MultiPhaseStatusTracker should be completed when all phases done."""
        phase1 = self.create_phase_tracker(stage_storage, "phase1", [1, 2])
        phase2 = self.create_phase_tracker(stage_storage, "phase2", [1, 2])

        # Complete both phases
        for p in [phase1, phase2]:
            create_output_file(p.phase_dir, 1)
            create_output_file(p.phase_dir, 2)

        multi = MultiPhaseStatusTracker(stage_storage, [phase1, phase2])

        status = multi.get_status()

        assert status["status"] == "completed"
        assert status["progress"]["completed_phases"] == ["phase1", "phase2"]

    def test_is_completed(self, stage_storage):
        """is_completed should return True when all phases done."""
        phase1 = self.create_phase_tracker(stage_storage, "phase1", [1])
        phase2 = self.create_phase_tracker(stage_storage, "phase2", [1])

        multi = MultiPhaseStatusTracker(stage_storage, [phase1, phase2])

        assert multi.is_completed() is False

        # Complete all phases
        create_output_file(phase1.phase_dir, 1)
        create_output_file(phase2.phase_dir, 1)

        assert multi.is_completed() is True

    def test_run_skips_completed_phases(self, stage_storage):
        """run() should skip already completed phases."""
        run_tracker = {"phase1": 0, "phase2": 0}

        def make_run_fn(name):
            def run_fn(tracker):
                run_tracker[name] += 1
            return run_fn

        phase1 = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="phase1",
            discoverer=lambda d: [1],
            validator=file_validator,
            run_fn=make_run_fn("phase1"),
            use_subdir=True
        )
        phase2 = PhaseStatusTracker(
            stage_storage=stage_storage,
            phase_name="phase2",
            discoverer=lambda d: [1],
            validator=file_validator,
            run_fn=make_run_fn("phase2"),
            use_subdir=True
        )

        # Complete phase1
        create_output_file(phase1.phase_dir, 1)

        multi = MultiPhaseStatusTracker(stage_storage, [phase1, phase2])
        multi.run()

        # phase1 should be skipped, phase2 should run
        assert run_tracker["phase1"] == 0
        assert run_tracker["phase2"] == 1
