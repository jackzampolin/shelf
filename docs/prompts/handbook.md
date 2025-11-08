# Prompt Engineering Handbook

**Core philosophy:** Just like our codebase architecture (`docs/decisions/`), prompts follow fundamental principles that enable reliable LLM reasoning.

This handbook distills lessons from building real-world LLM agents that process scanned books.

## Quick Reference

When writing prompts, apply these 5 principles:

1. **Information Hygiene** - Structure for clarity → fast understanding → correct reasoning
2. **Teach Generalization** - Principles transfer across books, examples don't
3. **Triangulate Truth** - Cross-verify sources, no single signal is reliable
4. **Anticipate Failure** - Name pitfalls explicitly, calibrate confidence
5. **Economics-Aware** - Cost shapes strategy (cheap → expensive)

Each principle has specific techniques documented in `docs/prompts/techniques/`.

---

## Principle 1: Information Hygiene

**Maps to:** ADR 000 (Information Hygiene)

**Core insight:** Clear structure → Fast understanding → Correct reasoning

LLMs process prompts sequentially. Structure matters. Long unstructured text creates context pollution - irrelevant patterns leak in, signal gets lost in noise.

**Techniques:**
- **XML structure** - Tag semantic sections (`<role>`, `<task>`, `<output_requirements>`)
- **Trust upstream stages** - Clear scope prevents re-interpretation and inconsistency

**When to apply:**
- Prompts > 500 words need structure
- Multi-stage pipelines need clear boundaries
- Critical instructions must stand out (primacy/recency)

**Reference:** `pipeline/find_toc/agent/prompts.py` (well-structured), `pipeline/extract_toc/assembly/prompts.py` (simple, no tags needed)

---

## Principle 2: Teach Generalization, Not Memorization

**Specific to LLMs** (no direct ADR, but critical for prompts)

**Core insight:** Principles transfer across books, specific examples don't

When prompts use actual content from test data ("Chapter: April 12, 1945"), models learn to recognize THAT BOOK instead of the underlying pattern. This is overfitting.

**Techniques:**
- **Generic examples** - Use "Ancient World", "Medieval Period", never actual chapter titles
- **Pattern-based teaching** - Teach visual signs/structural properties, not format enumeration
- **Teach WHAT/WHY before HOW** - Philosophy → Principles → Examples → Instructions

**When to apply:**
- Any time you provide examples
- Teaching structural patterns (ToC formats, hierarchies)
- Complex tasks requiring judgment

**Reference:** `pipeline/extract_toc/detection/prompts.py:161-205` (explicit comment: "NOT from any specific book")

---

## Principle 3: Triangulate Truth from Multiple Sources

**Maps to:** ADR 001 (Ground Truth from Observation)

**Core insight:** No single source is reliable; cross-verification reveals truth

OCR has errors. Boundaries might be mislabeled. Visual can be ambiguous. But when multiple independent signals agree, confidence increases.

**Techniques:**
- **Vision-first workflow** - Clarify what image shows vs. what OCR provides
- **Grep-guided attention** - Use cheap text search to guide expensive vision
- **Multiple overlapping signals** - Detective-style: boundaries + grep + OCR + vision
- **Density-based reasoning** - Match frequency reveals running headers and boundaries

**When to apply:**
- High-stakes decisions (finding critical content)
- When individual signals are noisy
- Large search spaces (hundreds of pages)

**Reference:** `pipeline/link_toc/agent/prompts.py:6-54` (detective philosophy with 4 overlapping signals)

---

## Principle 4: Anticipate Failure Modes

**Maps to:** ADR 002 (Clear Boundaries → Reliability)

**Core insight:** Name pitfalls explicitly; calibrate confidence rigorously

Models repeat mistakes without explicit guidance. Common false positives (running headers vs. boundaries) need named patterns with detection logic.

**Techniques:**
- **Named failure patterns** - "RUNNING HEADERS - These are NOT boundaries" with explicit signs
- **Confidence calibration** - Rubrics with specific thresholds and criteria

**When to apply:**
- Tasks with common false positives
- Ambiguous cases requiring judgment
- When you've observed repeated errors in testing

**Reference:** `pipeline/label_pages/batch/prompts.py:74-152` (named false positives + confidence rubric)

---

## Principle 5: Economics-Aware Design

**Maps to:** ADR 003 (Cost Tracking as First-Class Concern)

**Core insight:** Cost shapes strategy (cheap → expensive → stop)

LLM API calls cost money. Grep is free. Vision is $0.001/image. Unguided search through 500 pages = waste. Cost-aware strategy = grep first, vision only for candidates, stop when confident.

**Technique:**
- **Cost awareness** - Label operations (FREE/CHEAP/EXPENSIVE), provide cost-efficient workflow

**When to apply:**
- Operations involving paid API calls
- Large search spaces
- Batch processing scenarios

**Reference:** `pipeline/find_toc/agent/prompts.py:32,167-174` ("FREE - no cost" labels + explicit cost guidance)

---

## Applying These Principles

When writing a new stage prompt:

1. **Structure clearly** (Principle 1) - XML tags for long prompts
2. **Teach patterns** (Principle 2) - Generic examples, visual signs, philosophy first
3. **Enable triangulation** (Principle 3) - Multiple signals, cross-verification
4. **Handle failure** (Principle 4) - Name pitfalls, calibrate confidence
5. **Optimize cost** (Principle 5) - Cheap operations first, stop early

**Principle combinations that work well:**
- Grep → Vision (Principles 3 + 5): Cost-aware triangulation
- Philosophy → Patterns → Examples (Principle 2): Teach generalization
- Multiple Signals → Confidence (Principles 3 + 4): Cross-check then assess

**Anti-patterns to avoid:**
- Using test data in examples (breaks Principle 2)
- Single information source (ignores Principle 3)
- Vague confidence (ignores Principle 4)
- Unguided search (ignores Principle 5)

---

## Detailed Techniques

See `docs/prompts/techniques/` for deep dives:
- `generic-examples.md`
- `pattern-based-teaching.md`
- `teach-why-first.md`
- `xml-structure.md`
- `trust-upstream.md`
- `vision-first-workflow.md`
- `grep-guided-attention.md`
- `density-reasoning.md`
- `multiple-signals.md`
- `failure-modes.md`
- `confidence-calibration.md`
- `cost-awareness.md`

Each technique file contains: problem, when to use, how to apply, codebase examples, anti-patterns.
