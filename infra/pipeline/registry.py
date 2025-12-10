STAGE_DEFINITIONS = [
    {'name': 'ocr-pages', 'class': 'pipeline.ocr_pages.OcrPagesStage'},
    {'name': 'label-structure', 'class': 'pipeline.label_structure.LabelStructureStage'},
    {'name': 'extract-toc', 'class': 'pipeline.extract_toc.ExtractTocStage'},
    {'name': 'link-toc', 'class': 'pipeline.link_toc.LinkTocStage'},
    {'name': 'common-structure', 'class': 'pipeline.common_structure.CommonStructureStage'},
    {'name': 'epub-output', 'class': 'pipeline.epub_output.EpubOutputStage'},
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


def get_all_stage_metadata():
    """Get metadata from all stage classes (for website generation)."""
    stages = []
    for stage_def in STAGE_DEFINITIONS:
        stage_class = get_stage_class(stage_def['name'])
        stages.append({
            'name': stage_def['name'],
            'icon': getattr(stage_class, 'icon', '📦'),
            'short_name': getattr(stage_class, 'short_name', stage_def['name']),
            'description': getattr(stage_class, 'description', ''),
            'dependencies': getattr(stage_class, 'dependencies', []),
            'phases': getattr(stage_class, 'phases', []),
        })
    return stages
