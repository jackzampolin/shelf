# Configuration Patterns

**Purpose**: Define standard configuration structure for pipeline stages (future state).

---

## Overview

**Current:** Config split between env vars, hardcoded defaults, and CLI args.

**Future:** Unified, hierarchical configuration with per-stage profiles.

**Core principle:** Configuration is explicit, validated, and immutable during processing.

---

## System Architecture (Future State)

```
┌───────────────────────────────────────────────┐
│         Configuration Hierarchy               │
└───────────────────────────────────────────────┘

1. DEFAULTS → config/<stage>.py
2. ENVIRONMENT → .env file
3. CLI OVERRIDES → --model, --workers flags

Precedence: CLI > Environment > Defaults
```

---

## Standard Structure

### Per-Stage Config Files

**Location:** `config/<stage>.py` (to be implemented)

**Pattern:**
```python
# config/correction.py
CORRECTION_CONFIG = {
    "model": {
        "default": "openai/gpt-4o-mini",
        "env_var": "CORRECT_MODEL"
    },
    "parallelization": {
        "max_workers": 30,
        "rate_limit": 150,
        "env_var": "CORRECT_WORKERS"
    },
    "quality": {
        "min_confidence": 0.8,
        "env_var": "CORRECT_MIN_CONFIDENCE"
    }
}
```

### Stage Initialization (Future)

```python
from config.loader import load_stage_config

class CorrectionStage:
    def __init__(self, scan_id, **overrides):
        self.config = load_stage_config(
            "correction",
            CORRECTION_CONFIG,
            overrides=overrides
        )
        self.config.validate()
        self.config.freeze()  # Immutable during processing
```

---

## Design Principles

**Explicit Over Implicit**
- No hidden defaults in function signatures
- All configuration in `config/` directory
- Stage documents what it needs

**Hierarchical Precedence**
- Defaults: Safe for production
- Environment: Per-deployment (API keys, paths)
- CLI: Per-run experiments

**Validate Early**
- Check before processing starts
- Fail fast with clear errors
- Validate models, workers, paths

**Immutable During Processing**
- Freeze config after validation
- Prevents mid-run modifications
- Ensures reproducibility

**Save to Metadata**
- Record exact config used
- Enable result reproducibility
- Track configuration experiments

---

## Standard Parameters

**Every stage should have:**

1. **Model Configuration**
   - `model` - LLM model name
   - `temperature` - Model temperature (if applicable)

2. **Parallelization**
   - `max_workers` - Thread pool size
   - `rate_limit` - API calls/min (optional)
   - `chunk_size` - Items per batch (optional)

3. **Processing Options**
   - `enable_checkpoints` - Resume capability
   - `enable_debug_output` - Save debug files
   - `log_level` - Logging verbosity

4. **Paths** (inherited from global)
   - `storage_root` - Base directory
   - `book_dir` - Scan-specific directory

---

## Config Loader (To Be Implemented)

**File:** `config/loader.py`

**Purpose:** Unified loading with precedence and validation

```python
def load_stage_config(stage_name, config_spec, overrides=None):
    """
    Load with precedence: CLI > ENV > Defaults
    Returns: Frozen ConfigObject with dot-notation access
    """
    # 1. Start with defaults
    # 2. Apply environment overrides
    # 3. Apply CLI overrides
    # 4. Return frozen config object
```

---

## Migration Path

**Current → Future:**

1. Create `config/loader.py` utility
2. Convert `config/__init__.py` to per-stage files
3. Refactor stages to use `load_stage_config()`
4. Remove hardcoded defaults from constructors
5. Add config freezing and metadata persistence

**Backward compatibility:** Keep `Config` class during migration.

---

## Metadata Persistence

**Save config snapshot to checkpoint:**
```python
checkpoint.set_metadata({
    'config_snapshot': self.config.to_dict(),
    'config_timestamp': datetime.now().isoformat()
})
```

**Benefits:** Reproducibility, configuration tracking, result comparison.

---

## Anti-Patterns

❌ Hardcoding defaults in `__init__`
❌ Modifying config during processing
❌ Mixing stage config with global config
❌ Skipping validation

---

## Summary

Production-ready configuration:
1. ✅ Per-stage config files in `config/`
2. ✅ Hierarchical loading (defaults → env → CLI)
3. ✅ Early validation
4. ✅ Immutable during execution
5. ✅ Saved to metadata

**Current:** `config/__init__.py`, `config/parallelization.py`

**Future:** Per-stage configs + unified loader
