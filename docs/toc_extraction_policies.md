# ToC Extraction Policies

Definitive policies for extract-toc stage behavior.

## Capitalization

**Policy**: Preserve original capitalization EXACTLY as shown in OCR text

**Rationale**: Capitalization may carry semantic meaning (emphasis, styling, original formatting choices)

**Examples:**
- `"FOREWORD"` → Keep as `"FOREWORD"` (all caps)
- `"The Opening Chapter"` → Keep as `"The Opening Chapter"` (title case)
- `"foreword"` → Keep as `"foreword"` (lowercase)

**Do NOT normalize** (e.g., ALL CAPS → Title Case)

---

## Quotes

**Policy**: Preserve surrounding quotes EXACTLY as shown

**Rationale**: Quotes indicate direct quotations or stylistic emphasis in original ToC

**Examples:**
- `'"A sort of wartime normal"'` → Keep quotes: `'"A sort of wartime normal"'`
- `'"Use 'Em or Lose 'Em"'` → Keep quotes: `'"Use 'Em or Lose 'Em"'`
- `"The Beginning"` → No quotes to preserve: `"The Beginning"`

**Do NOT strip quotes** from titles

---

## Numbering Patterns

**Policy**: Detect and preserve numbering patterns (Roman, Arabic, spelled-out)

**Rationale**: The numbering pattern is part of the book's structural style

**Examples:**

### Roman Numerals:
- `"Part I: The Beginning"` → `entry_number="I"`
- `"Book III"` → `entry_number="III"`

### Arabic Numerals:
- `"Part 1: Foundation"` → `entry_number="1"`
- `"Unit 2: Economics"` → `entry_number="2"`

### Spelled Out:
- `"Part One: Early Days"` → `entry_number="One"`
- `"Book Two: Middle Period"` → `entry_number="Two"`

**Do NOT convert** between patterns (e.g., "One" → "1")

---

## Empty Titles

**Policy**: Empty titles are VALID when entry is just structural prefix

**Rationale**: Some books have parts/books/volumes with NO descriptive titles - just numbered divisions

**Examples:**

Valid empty titles:
- `"Part I"` → `entry_number="I"`, `title=""`, `level_name="part"`
- `"BOOK II"` → `entry_number="II"`, `title=""`, `level_name="book"`
- `"Volume III"` → `entry_number="III"`, `title=""`, `level_name="volume"`

**Do NOT invent titles** if the original ToC doesn't have them

---

## Prefix Parsing

**Policy**: Parse structural prefixes (Part, Book, Unit, Volume, Act) as entry_number, NOT title

**Pattern**: `"Prefix Number: Title Text"`
- `entry_number` = Number (preserve pattern: Roman/Arabic/Spelled)
- `title` = Title Text (WITHOUT the prefix)
- `level_name` = Semantic type (part/book/unit/volume/act)

**Examples:**
- `"Part I: The Beginning"` → `entry_number="I"`, `title="The Beginning"`, `level_name="part"`
- `"BOOK III: War Years"` → `entry_number="III"`, `title="War Years"`, `level_name="book"`
- `"Part One: Origins"` → `entry_number="One"`, `title="Origins"`, `level_name="part"`

**Exception - Separate Parent Entry:**

ONLY treat prefix as separate parent entry if:
1. Prefix appears on separate line with NO title text following
2. AND next entries are clearly INDENTED (visual hierarchy)
3. AND prefix line has NO page number

Example:
```
Part I                    <-- Separate parent entry
  Chapter 1: Foo ... 10   <-- Indented child
  Chapter 2: Bar ... 20   <-- Indented child
```
→ Entry 1: `title="Part I"`, `level=1`, `page=null`
→ Entry 2: `entry_number="1"`, `title="Foo"`, `level=2`, `page="10"`

---

## Multi-line Entries

**Policy**: Merge multi-line entries at same indentation level

**Pattern**: Title text + page number on separate lines, NO indentation change

**Examples:**

Multi-line with page number below:
```
Part I
The Opening Period
I
```
→ ONE entry: `entry_number="I"`, `title="The Opening Period"`, `page="I"`, `level=1`

Multi-line title continuation:
```
Chapter 1: An Incredibly Long Title That
           Continues on the Next Line ... 15
```
→ ONE entry: `title="Chapter 1: An Incredibly Long Title That Continues on the Next Line"`, `page="15"`

**Key Rule**: Line breaks ≠ hierarchy. Only INDENTATION indicates parent/child.

---

## Level Detection

**Policy**: Levels determined by VISUAL INDENTATION, verified against global structure

**Hierarchy Indicators:**
- Level 1: Flush left (0-20px from margin) OR largest/boldest
- Level 2: Moderate indent (20-60px from margin)
- Level 3: Deep indent (60-100px from margin)

**Global Structure Enforcement:**
- Find phase analyzes ENTIRE ToC → determines `total_levels`
- Extract phase MUST match this count
- If visual analysis conflicts with global structure → re-examine

**Examples:**

Flat structure (total_levels=1):
```
Part I
The Opening Period
I
Part II
The Middle Years
39
```
→ All entries at SAME indentation = level 1 (even if multi-line)

Hierarchical (total_levels=2):
```
Part I: Ancient Era
  Chapter 1: Origins ... 1      <-- Indented
  Chapter 2: Growth ... 20
```
→ Parts at level 1, Chapters at level 2 (indentation difference)

---

## Ground Truth Alignment

These policies define "correct" extraction. Ground truth should reflect these rules.

**When ground truth differs from extraction:**
1. Check if extraction follows these policies
2. If yes → Update ground truth
3. If no → Fix extraction (prompt or code)

**Recent updates:**
- Capitalization: NOW preserve (was normalize)
- Quotes: NOW preserve (was strip)
- Numbering: NOW preserve pattern (was convert)
- Empty titles: NOW embrace (was avoid)

---

## Implementation Status

✅ Detection prompt updated (2025-11-20)
✅ Finder prompt updated (2025-11-20)
⚠️  Ground truth needs audit for new policies
⏳ Validation logic may need updates

---

## Related Files

- `pipeline/extract_toc/detection/prompts.py` - Per-page extraction
- `pipeline/extract_toc/find/agent/prompts.py` - Structure discovery
- `tests/fixtures/toc_ground_truth/` - Ground truth dataset
- `tests/test_extract_toc_accuracy.py` - Accuracy testing
