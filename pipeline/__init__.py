"""
Book digitization pipeline stages.

Sequential processing:
1. ocr.py - Extract text from PDFs using Tesseract
2. correct.py - 3-agent LLM correction pipeline
3. fix.py - Agent 4 targeted fixes for flagged pages
4. merge.py - Merge corrected pages into final dual-structure text
"""