STAGE_DEFINITIONS = [
    {
        'name': 'tesseract',
        'abbr': 'TES',
        'display_name': 'Tesseract',
        'class': 'pipeline.tesseract.TesseractStage',
        'default_kwargs': lambda model=None, workers=None, max_retries=3: {
            'psm_mode': 3,
            **({'max_workers': workers} if workers else {})
        }
    },
    {
        'name': 'ocr-pages',
        'abbr': 'OPG',
        'display_name': 'OCR-Pages',
        'class': 'pipeline.ocr_pages.OcrPagesStage',
        'default_kwargs': lambda model=None, workers=None, max_retries=3: {
            'max_workers': workers if workers else 30
        }
    },
    {
        'name': 'label-pages',
        'abbr': 'LBL',
        'display_name': 'Label-Pages',
        'class': 'pipeline.label_pages.LabelPagesStage',
        'default_kwargs': lambda model=None, workers=None, max_retries=3: {
            **({'model': model} if model else {}),
            **({'max_workers': workers} if workers else {}),
            'max_retries': max_retries
        }
    },
    {
        'name': 'find-toc',
        'abbr': 'FTO',
        'display_name': 'Find-ToC',
        'class': 'pipeline.find_toc.FindTocStage',
        'default_kwargs': lambda model=None, workers=None, max_retries=3: {
            **({'model': model} if model else {})
        }
    },
    {
        'name': 'extract-toc',
        'abbr': 'TOC',
        'display_name': 'Extract-ToC',
        'class': 'pipeline.extract_toc.ExtractTocStage',
        'default_kwargs': lambda model=None, workers=None, max_retries=3: {
            **({'model': model} if model else {})
        }
    },
    {
        'name': 'link-toc',
        'abbr': 'LNK',
        'display_name': 'Link-ToC',
        'class': 'pipeline.link_toc.LinkTocStage',
        'default_kwargs': lambda model=None, workers=None, max_retries=3: {
            **({'model': model} if model else {}),
            'max_iterations': 15,
            'verbose': False
        }
    },
]

STAGE_NAMES = [s['name'] for s in STAGE_DEFINITIONS]
STAGE_ABBRS = {s['name']: s['abbr'] for s in STAGE_DEFINITIONS}
STAGE_DISPLAY_NAMES = {s['name']: s['display_name'] for s in STAGE_DEFINITIONS}


def get_stage_class(stage_name: str):
    for stage_def in STAGE_DEFINITIONS:
        if stage_def['name'] == stage_name:
            module_path, class_name = stage_def['class'].rsplit('.', 1)
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)

    raise ValueError(f"Unknown stage: {stage_name}")


def get_stage_instance(storage, stage_name: str, model=None, workers=None, max_retries=3):
    for stage_def in STAGE_DEFINITIONS:
        if stage_def['name'] == stage_name:
            stage_class = get_stage_class(stage_name)
            kwargs = stage_def['default_kwargs'](model=model, workers=workers, max_retries=max_retries)
            return stage_class(storage, **kwargs)

    raise ValueError(f"Unknown stage: {stage_name}")


def get_stage_map(storage, model=None, workers=None, max_retries=3):
    return {
        stage_def['name']: get_stage_instance(storage, stage_def['name'], model, workers, max_retries)
        for stage_def in STAGE_DEFINITIONS
    }
