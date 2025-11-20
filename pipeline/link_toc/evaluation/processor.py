from ..schemas import PatternAnalysis, HeadingDecision


EXCLUDED_BACK_MATTER = ["Index", "Bibliography", "Notes", "Appendix"]
MIN_HEADING_LENGTH = 3


def should_include_heading(heading_text):
    if len(heading_text) <= MIN_HEADING_LENGTH:
        return False, f"Too short ({len(heading_text)} chars, minimum {MIN_HEADING_LENGTH})"

    if heading_text in EXCLUDED_BACK_MATTER:
        return False, f"Standard back matter section: '{heading_text}'"

    return True, f"Substantive heading ({len(heading_text)} chars, not back matter)"


def evaluate_candidates(tracker, **kwargs):
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    pattern_dir = stage_storage.output_dir / "pattern"
    pattern_analysis_path = pattern_dir / "pattern_analysis.json"

    if not pattern_analysis_path.exists():
        logger.info("No pattern_analysis.json - skipping evaluation")
        return

    pattern_data = storage.stage("link-toc").load_file("pattern/pattern_analysis.json")
    pattern = PatternAnalysis(**pattern_data)

    if not pattern.candidate_headings:
        logger.info("No candidate headings to evaluate")
        return

    logger.info(f"Evaluating {len(pattern.candidate_headings)} candidate headings")

    decisions = []
    for candidate in pattern.candidate_headings:
        include, reasoning = should_include_heading(candidate.heading_text)

        if include:
            decision = HeadingDecision(
                scan_page=candidate.scan_page,
                heading_text=candidate.heading_text,
                include=True,
                title=candidate.heading_text,
                level=candidate.heading_level,
                entry_number=None,
                parent_toc_entry_index=None,
                reasoning=reasoning
            )
        else:
            decision = HeadingDecision(
                scan_page=candidate.scan_page,
                heading_text=candidate.heading_text,
                include=False,
                reasoning=reasoning
            )

        decisions.append(decision)

        decision_filename = f"heading_{candidate.scan_page:04d}.json"
        stage_storage.save_file(f"evaluation/{decision_filename}", decision.model_dump())

    included_count = sum(1 for d in decisions if d.include)
    logger.info(f"Evaluation complete: {included_count}/{len(decisions)} headings included")
