from ..schemas import LinkedTableOfContents, PatternAnalysis, CandidateHeading


def determine_pattern_relationship(toc_structure, discovered_levels, candidate_count):
    if not discovered_levels:
        return "unknown", f"ToC has {toc_structure['count']} entries, no candidates discovered", 0.3

    most_common_level = max(set(discovered_levels), key=discovered_levels.count)

    if toc_structure["level"] == 1 and most_common_level == 1:
        return (
            "fill_gaps",
            f"ToC lists {toc_structure['count']} level-1 entries, discovered {candidate_count} level-1 headings filling gaps",
            0.8
        )

    if toc_structure["level"] == 1 and most_common_level == 2:
        return (
            "sections_under_chapters",
            f"ToC lists {toc_structure['count']} chapters, discovered {candidate_count} sections within chapters",
            0.8
        )

    levels_str = list(set(discovered_levels))
    return (
        "unknown",
        f"ToC has {toc_structure['count']} entries (level {toc_structure['level']}), discovered {candidate_count} headings (levels {levels_str})",
        0.5
    )


def analyze_toc_pattern(tracker, **kwargs):
    storage = tracker.storage
    logger = tracker.logger
    stage_storage = tracker.stage_storage

    linked_toc_data = stage_storage.load_file("linked_toc.json")
    if not linked_toc_data:
        logger.warning("No linked_toc.json found - skipping pattern analysis")
        return

    linked_toc = LinkedTableOfContents(**linked_toc_data)

    if not linked_toc.entries or len(linked_toc.entries) == 0:
        logger.info("No ToC entries - skipping pattern analysis")
        return

    mechanical_dir = storage.stage("label-structure").output_dir / "mechanical"
    if not mechanical_dir.exists():
        logger.warning("label-structure mechanical output not found")
        return

    all_headings = []
    for page_file in sorted(mechanical_dir.glob("page_*.json")):
        page_data = storage.stage("label-structure").load_file(f"mechanical/{page_file.name}")
        if not page_data:
            continue

        page_num = page_data.get("page_num")
        if page_num is None:
            continue

        headings = page_data.get("headings", [])

        for heading in headings:
            all_headings.append({
                "scan_page": page_num,
                "text": heading.get("text", ""),
                "level": heading.get("level", 1)
            })

    logger.info(f"Found {len(all_headings)} total headings in label-structure")

    toc_entries = [e for e in linked_toc.entries if e is not None]
    toc_pages = [e.scan_page for e in toc_entries if e.scan_page]

    if not toc_pages:
        logger.warning("No ToC entries with scan_pages - skipping")
        return

    body_range = (min(toc_pages), max(toc_pages))
    toc_levels = [e.level for e in toc_entries]
    toc_numbers = [e.entry_number for e in toc_entries if e.entry_number]

    ascending_pages = all(toc_pages[i] <= toc_pages[i+1] for i in range(len(toc_pages)-1))

    numbering_scheme = "none"
    if toc_numbers:
        first_num = toc_numbers[0]
        if first_num.upper() in ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']:
            numbering_scheme = "roman"
        elif first_num.isdigit():
            numbering_scheme = "arabic"
        else:
            numbering_scheme = "mixed"

    toc_structure = {
        "numbering": numbering_scheme,
        "level": max(set(toc_levels), key=toc_levels.count) if toc_levels else 1,
        "count": len(toc_entries),
        "ascending_pages": ascending_pages
    }

    body_headings = [
        h for h in all_headings
        if body_range[0] <= h["scan_page"] <= body_range[1]
    ]

    toc_page_set = set(toc_pages)
    candidate_headings_raw = [
        h for h in body_headings
        if h["scan_page"] not in toc_page_set
    ]

    logger.info(f"ToC covers {len(toc_pages)} pages, found {len(candidate_headings_raw)} candidate headings in body")

    candidate_headings = []
    for h in candidate_headings_raw:
        preceding = None
        following = None

        for toc_page in toc_pages:
            if toc_page < h["scan_page"]:
                preceding = toc_page
            elif toc_page > h["scan_page"] and following is None:
                following = toc_page
                break

        candidate_headings.append(CandidateHeading(
            scan_page=h["scan_page"],
            heading_text=h["text"],
            heading_level=h["level"],
            preceding_toc_page=preceding,
            following_toc_page=following
        ))

    discovered_levels = [h.heading_level for h in candidate_headings]

    discovered_structure = {
        "count": len(candidate_headings),
        "numbering": "unknown",
        "levels": list(set(discovered_levels)) if discovered_levels else []
    }

    expected_relationship, pattern_description, confidence = determine_pattern_relationship(
        toc_structure, discovered_levels, len(candidate_headings)
    )

    pattern_analysis = PatternAnalysis(
        pattern_description=pattern_description,
        expected_relationship=expected_relationship,
        body_range=body_range,
        toc_structure=toc_structure,
        discovered_structure=discovered_structure,
        candidate_headings=candidate_headings,
        confidence=confidence,
        reasoning=f"Analyzed {len(toc_entries)} ToC entries and {len(all_headings)} discovered headings. "
                  f"ToC numbering: {numbering_scheme}, pages ascending: {ascending_pages}. "
                  f"Found {len(candidate_headings)} candidates in body range."
    )

    storage.stage("link-toc").save_file(
        "pattern/pattern_analysis.json",
        pattern_analysis.model_dump(),
        schema=PatternAnalysis
    )

    logger.info(f"Pattern analysis complete: {pattern_description}")
    logger.info(f"Expected relationship: {expected_relationship}")
    logger.info(f"Candidate headings: {len(candidate_headings)}")
