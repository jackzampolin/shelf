# Built with Claude Contest Submission

## X (Twitter) Post Version

```
🚀 #BuiltWithClaude: Scanshelf - Turn physical books into digital libraries

Built in <1 week using Claude Sonnet 4.5 for intelligent document understanding. Process 400+ page books in ~20 minutes for <$4.

🎯 What it does:
• OCR → LLM correction → Claude Sonnet 4.5 structure extraction
• Extracts chapters, footnotes, bibliographies with perfect boundaries
• Generates clean text for audiobooks + JSON for RAG/search
• Tracks provenance: every paragraph → original scan pages

⚡️ Why Claude Sonnet 4.5?
The structure stage is pure magic:
• Identifies semantic boundaries (not just page breaks)
• Understands complex document layouts (multi-column, footnotes, etc.)
• Costs 0.11¢/page (10x cheaper than I expected)
• 433-page Roosevelt autobiography: $0.49, 90 seconds

📊 Real demo included:
• Theodore Roosevelt's 1913 autobiography
• Full processing run: 18 min, $3.58 total
• Sample outputs with actual costs
• 11 chapters perfectly extracted

🛠 Use cases:
• Research: Citation-ready with scan page provenance
• Audiobooks: Clean TTS-optimized text output
• RAG: Paragraph-level JSON with metadata

Try it yourself:
🔗 github.com/jackzampolin/scanshelf
📖 Full demo walkthrough included

What should I digitize next? 📚

#BuildWithClaude #AI #DocumentProcessing
```

## Discord Post Version

```markdown
# 🚀 Built with Claude: Scanshelf

## What I Built
**Scanshelf** - An open-source pipeline that turns scanned books into digital libraries with semantic structure extraction.

Feed it a PDF scan → get back:
- ✅ Clean, corrected text (OCR errors fixed)
- ✅ Chapter boundaries & titles
- ✅ Footnotes & bibliographies parsed
- ✅ TTS-optimized text for audiobooks
- ✅ RAG-ready JSON with paragraph-level provenance

## How I Built It (< 1 Week)
I rebuilt my thesis research tool as an OSS project this week using Claude Sonnet 4.5 for the critical structure extraction stage.

**4-stage pipeline:**
1. **OCR**: Tesseract layout-aware extraction
2. **Correction**: gpt-4o-mini fixes OCR errors (3-agent system)
3. **Fix**: Claude Sonnet 4.5 targeted fixes for flagged issues
4. **Structure**: Claude Sonnet 4.5 semantic analysis 🌟

## Why Claude Sonnet 4.5?
The structure stage is where Claude Sonnet 4.5 shines:

**Semantic Understanding:**
- Identifies chapter boundaries by meaning, not just formatting
- Handles complex layouts: multi-column, footnotes, mixed content
- Extracts accurate titles even from running headers
- Understands document structure (front matter, body, back matter)

**Performance:**
- 433-page book: $0.49, 90 seconds
- That's **0.11¢ per page** for PhD-level document analysis
- 10x cheaper and more accurate than I expected

**Example:** Roosevelt's autobiography has no table of contents in the scan. Claude Sonnet 4.5 identified all 11 chapter boundaries perfectly, extracted titles from running headers, and even classified front/back matter sections.

## Demo: Theodore Roosevelt's Autobiography
I included a complete working demo processing a 433-page public domain book:

**Processing Stats:**
- Duration: 18 minutes end-to-end
- Cost: $3.58 total ($0.49 for Claude structure extraction)
- Output: 11 chapters, 267 page numbers mapped, full provenance

**Sample outputs included:**
- Chapter JSON with paragraph-level granularity
- TTS-optimized reading text
- Complete metadata with cost breakdown

Try it: https://github.com/jackzampolin/scanshelf/tree/main/examples/roosevelt-demo

## Use Cases
🔬 **Research**: Every paragraph links back to original scan pages for citations

🎧 **Audiobooks**: Clean text output optimized for TTS (no OCR artifacts)

🤖 **RAG/Search**: Structured JSON with metadata for vector embeddings

📚 **Digital Libraries**: Preserve & digitize rare books with full provenance

## Screenshots
[Include in Discord post:]
1. Example chapter JSON showing paragraph structure
2. Cost breakdown from actual processing run
3. CLI output showing pipeline progress

## Technical Details
- **Language**: Python
- **Models**: Claude Sonnet 4.5 (structure + fixes), gpt-4o-mini (correction)
- **API**: OpenRouter for model access
- **License**: MIT (fully open source)
- **Repo**: github.com/jackzampolin/scanshelf

## What's Next?
Would love feedback on:
- What books should I demo next?
- Other document types to support? (magazines, journals, etc.)
- Feature requests?

Built entirely with Claude Code + Claude Sonnet 4.5 this past week for the #BuiltWithClaude contest! 🎉
```

## Key Points for Both Platforms

### Must Include:
✅ What you built - Scanshelf, book digitization pipeline
✅ How you built it in a week - Rebuilt thesis tool as OSS
✅ Screenshots/demos - Link to working demo + sample outputs
✅ Claude Sonnet 4.5 usage - Structure extraction stage

### Engagement Hooks:
1. Real numbers: $3.58 for 433 pages, 18 minutes
2. Relatable use case: turning physical books digital
3. Working demo anyone can try
4. Multiple audiences: researchers, audiobook creators, developers

### Differentiation:
- Not just "I built with Claude" - shows specific cost/performance data
- Real working demo with actual outputs
- Open source + MIT license = community can contribute
- Practical use cases with clear value

## Submission Timing
- Deadline: October 7, 2025 at 9am ET
- Post on **both** X and Discord for maximum reach
- Include link to GitHub repo
- Tag appropriately: #BuiltWithClaude #BuildWithClaude

## Supporting Materials
- GitHub: https://github.com/jackzampolin/scanshelf
- Demo: https://github.com/jackzampolin/scanshelf/tree/main/examples/roosevelt-demo
- README with full technical details
- Working code anyone can clone and run
