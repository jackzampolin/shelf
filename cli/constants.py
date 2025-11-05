STAGE_DEFINITIONS = [
    {'name': 'tesseract', 'abbr': 'TES', 'class': 'pipeline.tesseract.TesseractStage'},
    {'name': 'ocr', 'abbr': 'OCR', 'class': 'pipeline.ocr.OCRStage'},
    {'name': 'ocr-pages', 'abbr': 'OPG', 'class': 'pipeline.ocr_pages.OcrPagesStage'},
    {'name': 'paragraph-correct', 'abbr': 'PAR', 'class': 'pipeline.paragraph_correct.ParagraphCorrectStage'},
    {'name': 'label-pages', 'abbr': 'LAB', 'class': 'pipeline.label_pages.LabelPagesStage'},
    {'name': 'find-toc', 'abbr': 'FTO', 'class': 'pipeline.find_toc.FindTocStage'},
    {'name': 'extract-toc', 'abbr': 'TOC', 'class': 'pipeline.extract_toc.ExtractTocStage'},
]

STAGE_NAMES = [s['name'] for s in STAGE_DEFINITIONS]
STAGE_ABBRS = {s['name']: s['abbr'] for s in STAGE_DEFINITIONS}

CORE_STAGES = STAGE_NAMES
REPORT_STAGES = ['ocr', 'paragraph-correct', 'label-pages']


def get_stage_map(model=None, workers=None, max_retries=3):
    """
    Instantiate pipeline stages with appropriate parameters.

    Different stage types require different initialization:
    - OCR stages: CPU-bound (ocr) or API-bound (ocr-pages), worker count controls parallelism
    - LLM stages: API-bound, higher worker default (30) for better throughput
    - extract-toc: Single-pass operation, no worker control needed

    max_retries applies only to stages making fallible API calls.
    """
    stage_map = {}

    for stage_def in STAGE_DEFINITIONS:
        module_path, class_name = stage_def['class'].rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        stage_class = getattr(module, class_name)

        kwargs = {}

        if stage_def['name'] == 'tesseract':
            # CPU-bound Tesseract stage (default PSM 3, cpu_count workers)
            if workers:
                kwargs['max_workers'] = workers
            kwargs['psm_mode'] = 3

        elif stage_def['name'] == 'ocr':
            if workers:
                kwargs['max_workers'] = workers

        elif stage_def['name'] == 'ocr-pages':
            # API-bound OCR stage with default 30 workers (DeepInfra rate limits allow high concurrency)
            if workers:
                kwargs['max_workers'] = workers
            else:
                kwargs['max_workers'] = 30

        elif stage_def['name'] in ['paragraph-correct', 'label-pages']:
            if model:
                kwargs['model'] = model
            if workers:
                kwargs['max_workers'] = workers
            else:
                kwargs['max_workers'] = 30
            kwargs['max_retries'] = max_retries

        elif stage_def['name'] in ['find-toc', 'extract-toc']:
            if model:
                kwargs['model'] = model

        stage_map[stage_def['name']] = stage_class(**kwargs)

    return stage_map
