"""
Stage registry - single source of truth for pipeline stages.

This module defines all available stages and provides utilities for
dynamically loading stage classes. Used by both the CLI and BaseStage
for dependency resolution.
"""

STAGE_DEFINITIONS = [
    {'name': 'tesseract', 'abbr': 'TES', 'class': 'pipeline.tesseract.TesseractStage'},
    {'name': 'ocr-pages', 'abbr': 'OPG', 'class': 'pipeline.ocr_pages.OcrPagesStage'},
    {'name': 'label-pages', 'abbr': 'LBL', 'class': 'pipeline.label_pages.LabelPagesStage'},
    {'name': 'find-toc', 'abbr': 'FTO', 'class': 'pipeline.find_toc.FindTocStage'},
    {'name': 'extract-toc', 'abbr': 'TOC', 'class': 'pipeline.extract_toc.ExtractTocStage'},
    {'name': 'link-toc', 'abbr': 'LNK', 'class': 'pipeline.link_toc.LinkTocStage'},
]

STAGE_NAMES = [s['name'] for s in STAGE_DEFINITIONS]
STAGE_ABBRS = {s['name']: s['abbr'] for s in STAGE_DEFINITIONS}


def get_stage_class(stage_name: str):
    """
    Dynamically load and return a stage class by name.

    Args:
        stage_name: Stage name (e.g., "ocr-pages")

    Returns:
        Stage class

    Raises:
        ValueError: If stage_name not found in registry
    """
    for stage_def in STAGE_DEFINITIONS:
        if stage_def['name'] == stage_name:
            module_path, class_name = stage_def['class'].rsplit('.', 1)
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)

    raise ValueError(f"Unknown stage: {stage_name}")


def get_stage_instance(storage, stage_name: str, **overrides):
    """
    Create a stage instance with default parameters.

    Args:
        storage: BookStorage instance
        stage_name: Stage name (e.g., "ocr-pages")
        **overrides: CLI-provided overrides (model, workers, max_retries, etc.)

    Returns:
        Initialized stage instance

    Raises:
        ValueError: If stage_name not found in registry
    """
    stage_class = get_stage_class(stage_name)
    kwargs = stage_class.default_kwargs(**overrides)
    return stage_class(storage, **kwargs)


def get_stage_map(storage, **overrides):
    """
    Instantiate all pipeline stages with appropriate parameters.

    Args:
        storage: BookStorage instance (required for all stages)
        **overrides: CLI-provided overrides (model, workers, max_retries, etc.)

    Returns:
        Dict mapping stage names to initialized stage instances
    """
    return {
        stage_def['name']: get_stage_instance(storage, stage_def['name'], **overrides)
        for stage_def in STAGE_DEFINITIONS
    }
