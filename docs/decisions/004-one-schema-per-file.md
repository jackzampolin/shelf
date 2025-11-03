# 4. One Schema Per File (Discoverability Over DRY)

**Date:** 2025-10-30

**Status:** Accepted

**Context:**
Pydantic schemas define data contracts between stages. Organization affects maintainability and discoverability.

**Decision:**
One schema per file in `schemas/` directory. Duplicate common fields across schemas. Easy to find > fewer total lines.

**Alternatives Considered:**
- Single `schemas.py` with all schemas
- Base classes for common fields (DRY)
- Shared schemas across stages

**Consequences:**
- "Where's the schema?" → grep returns one file
- Change one schema without affecting others
- Slightly more code duplication
- Clear ownership (each stage owns its schemas)
