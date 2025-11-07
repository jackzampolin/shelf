# Import stage registry from infra (single source of truth)
from infra.pipeline.registry import (
    STAGE_DEFINITIONS,
    STAGE_NAMES,
    STAGE_ABBRS,
    get_stage_class,
    get_stage_instance,
    get_stage_map,
)

CORE_STAGES = STAGE_NAMES
REPORT_STAGES = []  # No stages currently generate reports
