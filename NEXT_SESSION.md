# Next Session: Documentation & Code Cleanup Audit

**Previous Session**: Built comprehensive E2E validation against IA ground truth. Pipeline validated at 92% accuracy on Roosevelt book.

**Current State**:
- Pipeline fully functional and validated
- 17 commits ahead on main branch
- Ready to process more books at scale
- Need to ensure docs and code are clean before production use

---

## Objective

Systematic audit of documentation and code to remove stale content, update outdated instructions, and ensure everything reflects current architecture.

**Why Now?** Before running many books through the pipeline, we need confidence that:
- Documentation accurately describes current behavior
- No stale code paths or unused functions
- Instructions work for new users
- Architecture docs match implementation

---

## Session Tasks

### 1. Documentation Audit (60-90 min)

**Files to Review:**
- `README.md` - Does it reflect current CLI and features?
- `CLAUDE.md` - Are workflow instructions current?
- `CONTRIBUTING.md` - Are setup steps accurate?
- `docs/PIPELINE_ARCHITECTURE.md` - Does it match current structure?
- `docs/STRUCTURE.md` - Are structure stage docs accurate?
- `docs/OCR_CLEAN.md` - Still relevant?
- `docs/MCP_SETUP.md` - Does MCP setup work?

**For Each Doc:**
- [ ] Read through completely
- [ ] Test any code examples or commands
- [ ] Check if references to files/functions are accurate
- [ ] Update or remove outdated sections
- [ ] Flag any TODOs or placeholders
- [ ] Verify examples match current output formats

**Key Questions:**
- Are there references to old file structures?
- Do CLI commands still work as documented?
- Are stage names consistent (OCR/Correct/Fix/Structure)?
- Do JSON schemas in docs match actual output?
- Are costs and performance estimates current?

### 2. Code Cleanup Audit (45-60 min)

**Dead Code Detection:**
```bash
# Find potentially unused functions
grep -r "^def " pipeline/ tools/ | cut -d: -f2 | sort

# Check for commented-out code blocks
grep -rn "^# def\|^# class" pipeline/ tools/

# Find TODO/FIXME comments
grep -rn "TODO\|FIXME\|XXX\|HACK" pipeline/ tools/ tests/
```

**Files to Review:**
- `pipeline/` - Any unused pipeline stages or functions?
- `tools/` - Deprecated tools or old implementations?
- `tests/` - Stale tests or fixtures that don't match current code?
- Root scripts - Any old entry points no longer used?

**For Each Module:**
- [ ] Check if all functions are actually called
- [ ] Look for commented-out code to remove
- [ ] Verify imports are used
- [ ] Check for duplicate implementations
- [ ] Remove debug print statements
- [ ] Update docstrings to match current behavior

**Specific Areas:**
- `pipeline/merge.py` - Is this still used? (might be old)
- `pipeline/quality_review.py` - Is this integrated?
- Old test files - Any skipped tests that should be removed?
- Example outputs - Are they current?

### 3. Configuration & Dependencies (30 min)

**pyproject.toml Review:**
- [ ] Are all dependencies still used?
- [ ] Any missing dependencies?
- [ ] Version pins appropriate?
- [ ] Scripts section accurate?

**Config Files:**
- [ ] `.gitignore` - Any missing patterns?
- [ ] `pytest.ini` - Markers accurate?
- [ ] `.env.example` - All required vars documented?

### 4. Create Cleanup Report (15 min)

Document findings in `docs/CLEANUP_AUDIT.md`:
```markdown
# Cleanup Audit Report

Date: [date]

## Documentation Issues Found
- [ ] Issue 1
- [ ] Issue 2

## Code Issues Found
- [ ] Dead code in X
- [ ] Unused function Y

## Action Items
1. Remove X
2. Update Y
3. ...

## Verified Working
- ✅ Feature A works as documented
- ✅ CLI command B produces expected output
```

---

## Success Criteria

- [ ] All documentation tested and verified accurate
- [ ] No commented-out code blocks remaining
- [ ] All TODOs either resolved or documented
- [ ] No dead code or unused functions
- [ ] Test suite reflects current architecture
- [ ] Examples and fixtures are current
- [ ] Cleanup report documents any deferred items

---

## Commands to Start

```bash
# 1. Check repo status
tree -L 2 --gitignore
git status

# 2. Start documentation review
cat README.md
cat CLAUDE.md
cat docs/PIPELINE_ARCHITECTURE.md

# 3. Look for dead code
grep -rn "TODO\|FIXME" pipeline/ tools/
grep -r "^# def " pipeline/ | head -20

# 4. Check test coverage
pytest --collect-only | grep "test session starts" -A 20
```

---

## Session Start Prompt

```
I want to do a systematic audit of our documentation and code before running
more books through the pipeline. Let's:

1. Review each doc file to ensure it's accurate and current
2. Find and remove any dead code or commented-out sections
3. Verify all examples and commands still work
4. Create a cleanup report for any issues found

Start by reading NEXT_SESSION.md for the plan, then let's begin with the
documentation audit.
```

---

## Notes

**Why This Matters:**
- Prevents confusion when onboarding new developers
- Ensures docs don't mislead about current behavior
- Removes maintenance burden of unused code
- Builds confidence before scaling to many books
- Makes codebase easier to understand and modify

**Scope:**
- Focus on accuracy, not adding new features
- Remove rather than fix deprecated code
- Update docs to match reality, not aspirations
- Be ruthless with stale content

**Not in Scope:**
- Adding new features
- Refactoring working code
- Improving test coverage (unless tests are broken)
- Performance optimization
