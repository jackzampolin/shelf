# Single source of truth for all pipeline stages
STAGE_DEFINITIONS = [
    {'name': 'ocr', 'abbr': 'OCR', 'class': 'pipeline.ocr.OCRStage'},
    {'name': 'chandra-ocr', 'abbr': 'CHA', 'class': 'pipeline.chandra_ocr.ChandraOCRStage'},
    {'name': 'paragraph-correct', 'abbr': 'PAR', 'class': 'pipeline.paragraph_correct.ParagraphCorrectStage'},
    {'name': 'label-pages', 'abbr': 'LAB', 'class': 'pipeline.label_pages.LabelPagesStage'},
    {'name': 'extract-toc', 'abbr': 'TOC', 'class': 'pipeline.extract_toc.ExtractTocStage'},
]

# Derived constants
STAGE_NAMES = [s['name'] for s in STAGE_DEFINITIONS]
STAGE_ABBRS = {s['name']: s['abbr'] for s in STAGE_DEFINITIONS}

# Legacy constants (deprecated, use STAGE_NAMES instead)
CORE_STAGES = STAGE_NAMES
REPORT_STAGES = ['ocr', 'chandra-ocr', 'paragraph-correct', 'label-pages']


def get_stage_map(model=None, workers=None, max_retries=3):
    """
    Build stage map from STAGE_DEFINITIONS.

    Returns:
        Dict mapping stage names to instantiated stage objects
    """
    stage_map = {}

    for stage_def in STAGE_DEFINITIONS:
        module_path, class_name = stage_def['class'].rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        stage_class = getattr(module, class_name)

        # Build kwargs based on stage requirements
        kwargs = {}

        # OCR stages: max_workers only
        if stage_def['name'] in ['ocr', 'chandra-ocr']:
            if workers:
                kwargs['max_workers'] = workers

        # LLM stages: model, max_workers, max_retries
        elif stage_def['name'] in ['paragraph-correct', 'label-pages']:
            if model:
                kwargs['model'] = model
            if workers:
                kwargs['max_workers'] = workers
            else:
                kwargs['max_workers'] = 30  # default for LLM stages
            kwargs['max_retries'] = max_retries

        # extract-toc: model only
        elif stage_def['name'] == 'extract-toc':
            if model:
                kwargs['model'] = model

        stage_map[stage_def['name']] = stage_class(**kwargs)

    return stage_map
