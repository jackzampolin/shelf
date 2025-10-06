# Next Session: Fix Correction Stage to Update Regions

## Current Problem

The correction/fix pipeline has an architectural flaw:

**OCR stage produces:**
```json
{
  "regions": [
    {"type": "header", "text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY in question..."},
    {"type": "body", "text": "Instead of opposing the bill I ardontly..."}  // ← OCR error
  ]
}
```

**Correction stage:**
1. ✅ Concatenates all regions (including headers) into full page text
2. ✅ Finds errors and fixes them → creates `corrected_text`
3. ❌ DOES NOT update the original `regions[].text` with corrections
4. ✅ Saves both original regions + corrected_text

**Result:**
```json
{
  "regions": [
    {"type": "header", "text": "80 THEODORE ROOSEVELT..."},  // ← Still original OCR
    {"type": "body", "text": "Instead of opposing the bill I ardontly..."}  // ← Still has OCR error!
  ],
  "llm_processing": {
    "corrected_text": "80 THEODORE ROOSEVELT...\n\nInstead of opposing the bill I ardently..."  // ← Fixed but headers included
  }
}
```

**Impact on Structure Stage:**
- Can't use `corrected_text` (has headers baked in)
- Can't use `regions[].text` (has OCR errors)
- Currently using regions (to filter headers) but getting OCR errors in final output
- Result: 40 headers leaked through + some OCR errors remain

---

## The Solution

**Make correction stage update individual regions with their corrections.**

### What Needs to Happen

After Agent 2 applies corrections, we need to:
1. Parse the `corrected_text` to identify what changed
2. Apply those changes back to the original `regions[].text`
3. Mark regions as `corrected: true`

### The Challenge

**Agent 1 (Error Detection) returns:**
```json
{
  "errors": [
    {
      "error_id": 1,
      "original_text": "ardontly",
      "error_type": "ocr_substitution",
      "location": "paragraph 1",
      "context_before": "I ",
      "context_after": " championed"
      // ❌ NO "corrected_text" field - doesn't know the fix yet
    }
  ]
}
```

**Agent 2 (Apply Corrections) returns:**
```
80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY

Instead of opposing the bill I ardently[CORRECTED:1] championed it...
```
Just text with `[CORRECTED:id]` markers, NOT structured JSON.

**To map corrections back to regions, we need to:**
1. Use the `[CORRECTED:id]` markers in Agent 2's output
2. Extract what each correction actually changed to
3. Find which region contains each error
4. Apply the correction to that region

---

## Implementation Plan

### Option A: Parse Agent 2 Output (Recommended)

**Code location:** `pipeline/correct.py:552` (function `apply_corrections_to_regions`)

**Current broken attempt:**
```python
def apply_corrections_to_regions(self, page_data, corrected_text, error_catalog):
    # ❌ This looks for corrected_text in error_catalog, but it's not there
    for error in errors:
        original = error.get('original_text')
        corrected = error.get('corrected_text')  # ← Returns None!
```

**What to do instead:**
```python
def apply_corrections_to_regions(self, page_data, corrected_text, error_catalog):
    """
    Parse corrected_text to extract what each [CORRECTED:id] marker replaced,
    then apply those changes to the original regions.
    """
    import re

    # Build original text from regions (same way Agent 2 saw it)
    correctable_regions = self.filter_correctable_regions(page_data)
    original_text = self.build_page_text(page_data, correctable_regions)

    # Parse corrected_text to find all [CORRECTED:id] markers
    # Pattern: "text[CORRECTED:id]" means "text" is the correction
    corrections_applied = {}

    # For each marker, find what word/phrase comes before it
    # Match pattern: (word(s))[CORRECTED:id]
    marker_pattern = r'(\S+(?:\s+\S+)?)\[CORRECTED:(\d+)\]'

    for match in re.finditer(marker_pattern, corrected_text):
        corrected_word = match.group(1)
        error_id = int(match.group(2))

        # Look up the original from error_catalog
        error = next((e for e in error_catalog['errors']
                     if e.get('error_id') == error_id), None)

        if error:
            corrections_applied[error_id] = {
                'original': error['original_text'],
                'corrected': corrected_word,
                'error': error
            }

    # Now apply each correction to the appropriate region
    for region in page_data.get('regions', []):
        if region['type'] not in ['header', 'body', 'caption']:
            continue

        region_text = region['text']
        updated_text = region_text

        # Apply corrections that appear in this region
        for error_id, correction in corrections_applied.items():
            if correction['original'] in updated_text:
                updated_text = updated_text.replace(
                    correction['original'],
                    f"{correction['corrected']}[CORRECTED:{error_id}]",
                    1  # Only first occurrence
                )

        if updated_text != region_text:
            region['text'] = updated_text
            region['corrected'] = True

    return page_data
```

### Option B: Make Agent 2 Return Structured JSON

Change Agent 2's prompt to return:
```json
{
  "corrected_text": "full text...",
  "changes": [
    {"error_id": 1, "original": "ardontly", "corrected": "ardently", "location": "region_2"}
  ]
}
```

Then directly apply those structured changes to regions.

**Pros:** Cleaner, more reliable
**Cons:** Requires changing Agent 2 prompt, testing, might break existing pipeline

---

## After Fixing Correction Stage

### Update Structure Loader

**File:** `pipeline/structure/loader.py:37-66`

**Current code tries to filter regions but falls back to full text:**
```python
def extract_body_text(self, data):
    # Gets fixed_text or corrected_text (has headers)
    full_text = agent4.get('fixed_text') or llm.get('corrected_text')

    # Gets regions
    regions = data.get('regions', [])

    # Filters to body
    body_regions = [r for r in regions if r['type'] in ['body', 'caption', 'footnote']]

    # ❌ Returns region text (has OCR errors) OR full_text (has headers)
    return '\n\n'.join([r['text'] for r in body_regions]) if body_regions else full_text
```

**After correction fix, change to:**
```python
def extract_body_text(self, data):
    """Extract corrected body text from regions, excluding headers."""
    regions = data.get('regions', [])

    if not regions:
        # Fallback to full text if no regions
        llm = data.get('llm_processing', {})
        agent4 = llm.get('agent4_fixes', {})
        return agent4.get('fixed_text') or llm.get('corrected_text', '')

    # Filter to body regions (exclude headers, footers, page numbers)
    body_regions = [
        r for r in regions
        if r['type'] in ['body', 'caption', 'footnote']
    ]

    if not body_regions:
        # Page has no body content (blank page, image-only, etc.)
        return ''

    # Sort by reading order
    body_regions.sort(key=lambda r: r.get('reading_order', 0))

    # Extract text from corrected regions
    # These now have corrections applied!
    return '\n\n'.join([r['text'] for r in body_regions])
```

---

## Testing Plan

1. **Test on single page:**
   ```bash
   uv run python ar.py correct roosevelt-autobiography --start 100 --end 100
   ```

2. **Verify regions updated:**
   ```bash
   cat ~/Documents/book_scans/roosevelt-autobiography/corrected/page_0100.json | \
     python3 -c "import sys, json; d=json.load(sys.stdin); \
     r=d['regions'][1]; \
     print('Body region corrected:', r.get('corrected', False)); \
     print('Has [CORRECTED] markers:', '[CORRECTED:' in r['text']); \
     print('Text:', r['text'][:200])"
   ```

3. **Run on small batch:**
   ```bash
   uv run python ar.py correct roosevelt-autobiography --start 1 --end 10
   ```

4. **If successful, run on all pages:**
   ```bash
   # This will re-process ALL pages with region updates
   uv run python ar.py correct roosevelt-autobiography --start 1 --end 636
   ```
   **Time:** ~9 minutes
   **Cost:** ~$2.77 (same as before, just re-running)

5. **Run structure:**
   ```bash
   rm -rf ~/Documents/book_scans/roosevelt-autobiography/structured/
   uv run python ar.py structure roosevelt-autobiography
   ```

6. **Verify clean output:**
   ```bash
   # Should be 0 or near-0 headers
   grep -c "THEODORE ROOSEVELT\|BOYHOOD AND YOUTH" \
     ~/Documents/book_scans/roosevelt-autobiography/structured/reading/full_book.txt
   ```

---

## Expected Outcome

After this fix:
- ✅ Regions have corrected text (no OCR errors)
- ✅ Can filter headers using region types
- ✅ Structure loader gets clean body text
- ✅ Reading output has NO headers
- ✅ Preserves structured OCR data for future use

---

## Files to Modify

1. **`pipeline/correct.py:552`** - Fix `apply_corrections_to_regions()`
2. **`pipeline/structure/loader.py:37`** - Update `extract_body_text()` to trust corrected regions
3. **`pipeline/fix.py:95`** - (Optional) Apply same logic for agent4_fixes

---

## Current Status (End of Session)

- ✅ Identified root cause
- ✅ Created `apply_corrections_to_regions()` function skeleton
- ❌ Function doesn't work (looks for wrong fields)
- ✅ Updated structure loader to filter headers
- ⚠️ Current output: 99.97% clean but has some OCR errors + 40 headers

**Next session should:** Implement Option A properly and test.

---

## Notes

- **Don't skip this fix** - it's the right architecture
- Having corrected regions is valuable beyond just this book
- Future features (like per-paragraph annotations) will need corrected regions
- This is a one-time fix that makes the whole pipeline better

---

## Fallback if Time is Short

If fixing this properly takes too long and deadline approaches:

**Quick hack for contest demo:**
Just update `pipeline/structure/loader.py` to use `corrected_text` and add a simple regex to strip common headers:

```python
def extract_body_text(self, data):
    llm = data.get('llm_processing', {})
    text = agent4.get('fixed_text') or llm.get('corrected_text', '')

    # Quick header filter
    lines = text.split('\n')
    cleaned = [
        line for line in lines
        if not re.match(r'^\d+\s+THEODORE ROOSEVELT', line)
        and not re.match(r'^BOYHOOD AND YOUTH', line)
    ]
    return '\n'.join(cleaned)
```

This isn't clean but would work for the demo.
