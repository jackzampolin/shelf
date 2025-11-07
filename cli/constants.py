# Import stage registry from infra (single source of truth)
from infra.pipeline.registry import STAGE_DEFINITIONS, STAGE_NAMES, STAGE_ABBRS

CORE_STAGES = STAGE_NAMES
REPORT_STAGES = []  # No stages currently generate reports


def get_stage_map(storage, model=None, workers=None, max_retries=3):
    """
    Instantiate pipeline stages with appropriate parameters.

    Args:
        storage: BookStorage instance (required for all stages)
        model: Optional model name override
        workers: Optional worker count override
        max_retries: Number of retries for API-bound stages

    Different stage types require different initialization:
    - tesseract: CPU-bound, worker count controls parallelism
    - ocr-pages: API-bound, default 30 workers for throughput
    - label-pages: Vision-based page classification with retries
    - find-toc/extract-toc: Single-pass with vision models
    - link-toc: Agent-based ToC-to-scan-page mapping

    max_retries applies only to stages making fallible API calls.
    """
    stage_map = {}

    for stage_def in STAGE_DEFINITIONS:
        module_path, class_name = stage_def['class'].rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        stage_class = getattr(module, class_name)

        # All stages now require storage as first argument
        kwargs = {}

        if stage_def['name'] == 'tesseract':
            # CPU-bound Tesseract stage (default PSM 3, cpu_count workers)
            if workers:
                kwargs['max_workers'] = workers
            kwargs['psm_mode'] = 3

        elif stage_def['name'] == 'ocr-pages':
            # API-bound OCR stage with default 30 workers (DeepInfra rate limits allow high concurrency)
            if workers:
                kwargs['max_workers'] = workers
            else:
                kwargs['max_workers'] = 30

        elif stage_def['name'] == 'label-pages':
            # Vision-based page labeling with model selection and retries
            if model:
                kwargs['model'] = model
            if workers:
                kwargs['max_workers'] = workers
            kwargs['max_retries'] = max_retries

        elif stage_def['name'] in ['find-toc', 'extract-toc']:
            if model:
                kwargs['model'] = model

        elif stage_def['name'] == 'link-toc':
            # Agent-based ToC entry finder with model selection
            if model:
                kwargs['model'] = model
            kwargs['max_iterations'] = 15
            kwargs['verbose'] = False

        stage_map[stage_def['name']] = stage_class(storage, **kwargs)

    return stage_map
