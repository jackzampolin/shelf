STAGE_DEFINITIONS = [
    {'name': 'tesseract', 'class': 'pipeline.tesseract.TesseractStage'},
    {'name': 'ocr-pages', 'class': 'pipeline.ocr_pages.OcrPagesStage'},
    {'name': 'label-pages', 'class': 'pipeline.label_pages.LabelPagesStage'},
    {'name': 'find-toc', 'class': 'pipeline.find_toc.FindTocStage'},
    {'name': 'extract-toc', 'class': 'pipeline.extract_toc.ExtractTocStage'},
    {'name': 'link-toc', 'class': 'pipeline.link_toc.LinkTocStage'},
]

STAGE_NAMES = [s['name'] for s in STAGE_DEFINITIONS]

def get_stage_class(stage_name: str):
    for stage_def in STAGE_DEFINITIONS:
        if stage_def['name'] == stage_name:
            module_path, class_name = stage_def['class'].rsplit('.', 1)
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)

    raise ValueError(f"Unknown stage: {stage_name}")

def get_stage_instance(storage, stage_name: str, **overrides):
    stage_class = get_stage_class(stage_name)
    kwargs = stage_class.default_kwargs(**overrides)
    return stage_class(storage, **kwargs)


def get_stage_map(storage, **overrides):
    return {
        stage_def['name']: get_stage_instance(storage, stage_def['name'], **overrides)
        for stage_def in STAGE_DEFINITIONS
    }
