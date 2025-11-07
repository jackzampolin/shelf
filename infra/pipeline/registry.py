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
    for stage_def in STAGE_DEFINITIONS:
        if stage_def['name'] == stage_name:
            module_path, class_name = stage_def['class'].rsplit('.', 1)
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)

    raise ValueError(f"Unknown stage: {stage_name}")
