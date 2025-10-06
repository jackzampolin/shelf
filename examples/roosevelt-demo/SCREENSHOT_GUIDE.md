# Screenshots for Contest Submission

## Screenshot 1: Chapter Structure JSON

Show the semantic structure extraction capability:

```bash
# Display formatted chapter JSON with jq
cat examples/roosevelt-demo/output/sample_chapters/chapter_01.json | jq '.' | head -50
```

**Highlights to capture:**
- Chapter metadata (title, page range, summary)
- Paragraph structure with unique IDs
- Provenance tracking (`scan_pages` array)
- Clean, structured JSON output

## Screenshot 2: Processing Cost Breakdown

Show the actual costs from the metadata:

```bash
# Display cost information
cat examples/roosevelt-demo/output/metadata/metadata.json | jq '.stats'
```

**Key numbers to highlight:**
- `total_cost_usd`: $0.49
- `pages_loaded`: 433
- `chapters_detected`: 11
- Phase breakdown showing Claude Sonnet 4.5 costs

## Screenshot 3: CLI Processing Output

If you have terminal output saved, show:
- Pipeline stages running
- Progress indicators
- Time estimates
- Final success message

## Screenshot 4: Sample Paragraph with Provenance

Extract a compelling example showing the provenance feature:

```bash
# Show a paragraph with clear provenance
cat examples/roosevelt-demo/output/sample_chapters/chapter_01.json | jq '.paragraphs[0]'
```

Output shows:
```json
{
  "id": "ch01_p001",
  "text": "THEODORE ROOSEVELT AN AUTOBIOGRAPHY...",
  "scan_pages": [21],
  "type": "body"
}
```

## Screenshot 5: Chapter List from Metadata

Show all extracted chapters:

```bash
cat examples/roosevelt-demo/output/metadata/metadata.json | jq '.chapters'
```

**Demonstrates:**
- 11 chapters accurately extracted
- Chapter titles extracted from text
- Page ranges correctly identified
- No table of contents was provided in scan

## For Discord Post

Include 2-3 screenshots maximum:
1. **Most impactful**: Cost breakdown ($0.49 for 433 pages)
2. **Technical demonstration**: Chapter JSON structure
3. **Visual appeal**: Chapter list showing all 11 chapters

## For X (Twitter) Post

Include 1-2 images:
1. **Hero image**: Cost breakdown + key stats
2. **Optional**: Sample chapter JSON or chapter list

## Creating the Images

### Terminal Screenshots
Use iTerm2 or Terminal with:
- Dark theme for better visual appeal
- Clear, readable font size (14pt+)
- Syntax highlighting with jq for JSON
- Crop to remove unnecessary whitespace

### Text Overlays (Optional)
Consider adding annotations:
- Arrow pointing to `total_cost_usd: 0.49152`
- Highlight "11 chapters detected"
- Circle the provenance tracking feature

### Image Dimensions
- X optimal: 1200x675 (16:9 ratio)
- Discord optimal: 1920x1080 or similar
- Ensure text is readable at thumbnail size
