# Next Session: Label Stage Prompt Improvements

## Session Summary: Stage 2 & 3 Alignment Complete

### Completed This Session ✅

1. **Model Selection & Testing**
   - Tested Gemini Flash Lite → C grade (83% applied, schema bugs)
   - Tested Qwen VL → A grade (perfect schema compliance, $0.0027/page)
   - Tested GPT-5 Mini → A+ grade (flawless, but $0.0069/page - 3x cost)
   - **Selected:** Qwen VL for production (best quality/cost balance)

2. **Stage Alignment (Correction ↔ Label)**
   - Added configurable `max_retries` parameter to label stage
   - Removed 67+ lines of unused PDF helper code from label stage
   - Added `VISION_MODEL` env var to Config (centralized model setting)
   - Both stages now use Config.VISION_MODEL from .env
   - Added `--no-retry` flag to both stages
   - **Result:** 100% API alignment achieved

3. **Comprehensive Prompt Analysis**
   - Analyzed correction prompt git history (3 versions)
   - Documented 7 proven patterns that improved accuracy 75% → 84%
   - Analyzed label prompt against correction patterns
   - Generated 7 specific recommendations with before/after code
   - **Output:** `docs/correction_prompt_evolution_analysis.md`

### Key Insights Discovered 🔍

**Correction Prompt Success Pattern:**
- Went from 252 lines → 88 lines (-65% length)
- Accuracy improved 75% → 84% (+9pp)
- **Why:** Critical rules FIRST (LLM primacy bias), visual ❌/✅ markers, quantified baselines

**Label Prompt Issues:**
- 280 lines (3x longer than correction)
- Critical rules buried deep (not upfront)
- QUOTE under-detected: 0.86 confidence (target 0.90+)
- OTHER overused: 3.9% (target <2%)
- Page numbers: 87.7% success (target >92%)

**Root Cause:** Indentation check comes 3rd in decision tree, should be 1st for QUOTE detection.

---

## Next Session Objective

**Improve label stage prompt to achieve:**
- QUOTE confidence: 0.86 → 0.90+
- OTHER usage: 3.9% → <2%
- Page number extraction: 87.7% → >92%
- Prompt length: 280 lines → ~120 lines

---

## Priority Actions (4-6 hours total)

### Phase 1: Establish Baseline (30 min)

**Run current label analysis to measure starting point:**
```bash
# Test on accidental-president (447 pages) or right-wing-critics (371 pages)
uv run python tools/analyze_label.py accidental-president

# Check for analyze_label.py script
ls tools/analyze_label.py

# If doesn't exist, create it (similar to analyze_correction.py)
# Should measure:
# - QUOTE detection rate and confidence
# - OTHER usage %
# - Page number extraction success rate
# - Block type distribution
```

**Document baseline metrics:**
- [ ] QUOTE avg confidence: _______
- [ ] OTHER usage %: _______
- [ ] Page number success rate: _______
- [ ] BODY %: _______ (should be 75-85%)

---

### Phase 2: High-Priority Improvements (2-3 hours)

#### Recommendation #1: Add Critical Rules Upfront (30 min)

**File:** `pipeline/3_label/__init__.py`
**Location:** Lines 531-560 (before `<page_number_extraction>`)

**Add section:**
```python
═══════════════════════════════════════════════════════════════════════
CRITICAL CLASSIFICATION RULES (READ THESE FIRST)
═══════════════════════════════════════════════════════════════════════

1. VISUAL SIGNALS ARE PRIMARY (content is secondary):
   ✅ Indented BOTH sides = QUOTE (even if content seems like body text)
   ✅ <8pt font at bottom = FOOTNOTE (even without superscripts)
   ✅ All-caps on map/chart = MAP_LABEL or DIAGRAM_LABEL (not OTHER)

2. BASELINE EXPECTATIONS (calibrate your confidence):
   - BODY: 75-85% of blocks (majority of content)
   - QUOTE: 2-8% (regular but not frequent)
   - FOOTNOTE: 5-15% (common in academic books)
   - HEADER/FOOTER: Present on 80%+ of pages
   - OTHER: <2% (RARE - only if truly no other type fits)

3. CHECK NEW TYPES BEFORE CHOOSING OTHER:
   ❌ WRONG: Unusual content → OTHER (confidence 0.75)
   ✅ CORRECT: Check these first:
      - Garbled text? → OCR_ARTIFACT
      - Map labels? → MAP_LABEL
      - Timeline labels? → DIAGRAM_LABEL
      - Photo attribution? → PHOTO_CREDIT
      - Still unclear? → Then consider OTHER

4. PAGE NUMBER EXTRACTION:
   ✅ Valid: "23", "ix", "147" (standalone numbers in corners/header/footer)
   ❌ Invalid: "Chapter 5", "page 1 of 300", "23 / The Accidental President"
   If ambiguous → set to null (better to skip than misidentify)
═══════════════════════════════════════════════════════════════════════
```

**See detailed code:** `docs/correction_prompt_evolution_analysis.md` - Recommendation #1

---

#### Recommendation #2: Reorder Classification Strategy (20 min)

**File:** `pipeline/3_label/__init__.py`
**Location:** Lines 727-761 (replace `<classification_strategy>`)

**Change decision tree order:**
- **Current:** Position → Font Size → Indentation → Content
- **Better:** **Indentation FIRST** → Position → Font Size → Content

**Why:** Indentation is QUOTE's strongest, most definitive signal. Checking it 3rd means model may already commit to BODY.

**See detailed code:** Agent 2 analysis - Recommendation #2

---

#### Recommendation #3: Enhance QUOTE Detection (45 min)

**File:** `pipeline/3_label/__init__.py`
**Location:** Lines 606-638 (replace `<quote_detection_guidance>`)

**Improvements needed:**
1. Quantify indentation: "0.25"-1" each side" (not vague "indented")
2. Add 3 ❌ WRONG examples (BODY with quotes, EPIGRAPH, dialogue)
3. Add 3 ✅ CORRECT examples with detailed reasoning
4. Make section more prescriptive (PRIMARY SIGNAL vs "pay attention")

**See detailed code:** Agent 2 analysis - Recommendation #3

---

#### Recommendation #4: Fix Page Number Extraction (30 min)

**File:** `pipeline/3_label/__init__.py`
**Location:** Lines 539-560 (replace `<page_number_extraction>`)

**Add specifics:**
- Position guidance: "within 1" of corner"
- Invalid formats: ❌ "Chapter 5", ❌ "page 1 of 300"
- Confidence fix: use 0.95 (not 1.0) for null cases
- Common failure examples

**Expected impact:** 87.7% → >92% success rate

**See detailed code:** Agent 2 analysis - Recommendation #4

---

#### Recommendation #5: Integrate New Types (15 min)

**File:** `pipeline/3_label/__init__.py`
**Location:** Lines 564-603 (modify `<block_classification>`)

**Changes:**
1. Move OCR_ARTIFACT, MAP_LABEL, DIAGRAM_LABEL, PHOTO_CREDIT from separate section (lines 666-692) into main list
2. Add ⚠️ NEW markers next to these types
3. Add OTHER-avoidance checklist at top of block classification
4. Remove redundant "new block types" section

**Expected impact:** OTHER usage 3.9% → <2%

**See detailed code:** Agent 2 analysis - Recommendation #5

---

### Phase 3: Test & Measure (30 min)

**After implementing Phase 2 changes:**

```bash
# Clean label stage
uv run python ar.py process clean label accidental-president -y

# Re-run with improved prompt
uv run python ar.py process label accidental-president

# Analyze results
uv run python tools/analyze_label.py accidental-president

# Compare to baseline:
# - QUOTE confidence (target: +5-10% improvement)
# - OTHER usage (target: -50% reduction)
# - Page number success (target: +5-7% improvement)
```

**Document results:**
- [ ] QUOTE avg confidence: _______ (vs baseline: _______)
- [ ] OTHER usage %: _______ (vs baseline: _______)
- [ ] Page number success: _______ (vs baseline: _______)
- [ ] Improvement met targets? Yes/No

---

### Phase 4: Optional Refinements (1-2 hours)

**If Phase 2 results show improvement, proceed with:**

#### Recommendation #6: Add More ❌/✅ Examples (45 min)

**Add 6 critical examples** (QUOTE vs BODY, OTHER vs new types, page numbers)

**See detailed code:** Agent 2 analysis - Recommendation #6

---

#### Recommendation #7: Add Confidence Calibration (30 min)

**Add calibration section** with expected distributions and self-check questions

**See detailed code:** Agent 2 analysis - Recommendation #7

---

## Reference Documents

**Analysis outputs from this session:**
1. `docs/correction_prompt_evolution_analysis.md` - Git history analysis, 7 proven patterns
2. Agent 2 output - 7 detailed recommendations with before/after code (in agent output above)

**Key files to modify:**
- `pipeline/3_label/__init__.py` (lines 527-845) - Main prompt
- `pipeline/3_label/schemas.py` (lines 13-56) - BlockType enum (review only, no changes planned)

**Analysis tools:**
- `tools/analyze_correction.py` - Reference for building analyze_label.py
- `tools/analyze_label.py` - **May need to create** if doesn't exist

**Test books:**
- `accidental-president` (447 pages) - Has correction data, good for testing
- `right-wing-critics` (371 pages) - Alternative test book

---

## Success Criteria

**Stage complete when:**
- ✅ QUOTE confidence ≥ 0.90 (currently 0.86)
- ✅ OTHER usage < 2% (currently 3.9%)
- ✅ Page number extraction > 92% (currently 87.7%)
- ✅ Prompt length reduced ~40% (280 → ~120 lines)
- ✅ Block type distribution reasonable (BODY 75-85%, QUOTE 2-8%, etc.)

**Validation:**
- Run analyze_label.py on test book
- Spot check 10-20 random pages for classification quality
- Verify QUOTE pages have proper indentation classification
- Verify OTHER pages couldn't fit specific types

---

## Environment Setup

**Model configuration:**
```bash
# Set in .env (applies to both correction and label stages)
VISION_MODEL=qwen/qwen3-vl-235b-a22b-instruct

# Or override per-run
uv run python ar.py process label accidental-president --model openai/gpt-5-mini
```

**Current costs (per page):**
- Qwen: $0.0016-0.0027 (recommended)
- GPT-5 Mini: $0.0067 (3x more, premium quality)
- Gemini Flash Lite: $0.001 (cheapest, but schema bugs)

---

## Notes

**Why this matters:**
- Label stage extracts structural metadata (page numbers, block types)
- Structure data drives ToC extraction, chapter detection, reference linking
- Current 87.7% page number extraction means ~55 pages misclassified (out of 447)
- QUOTE under-detection means missing important quotations in content
- OTHER overuse means losing semantic information (map labels, diagrams, etc.)

**Lessons from correction stage:**
1. Shorter prompts work better (LLM primacy bias)
2. Visual markers (❌/✅) create clarity
3. Quantified expectations calibrate behavior
4. Pattern-based guidance > verbose explanations
5. Data-driven iteration beats intuition
6. Examples prevent more errors than rules
7. Critical rules MUST come first

**Iterative approach:**
- Implement → Test → Measure → Refine
- Use analyze_label.py to identify top 3 failures
- Update prompt with specific examples from failures
- Re-test to verify improvement
- Don't implement all 7 recommendations at once (test incrementally)

---

## Quick Start (Next Session)

```bash
# 1. Establish baseline
uv run python tools/analyze_label.py accidental-president > baseline.txt

# 2. Implement Recommendations #1-3 (high priority)
# Edit pipeline/3_label/__init__.py

# 3. Test
uv run python ar.py process clean label accidental-president -y
uv run python ar.py process label accidental-president

# 4. Measure improvement
uv run python tools/analyze_label.py accidental-president > improved.txt
diff baseline.txt improved.txt

# 5. If improved, implement Rec #4-5, repeat
```

---

*This session: Aligned stages, selected model (Qwen), analyzed prompts, generated roadmap*
*Next session: Improve label prompt using proven correction patterns*
