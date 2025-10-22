"""
Book digitization pipeline stages.

Current stages (refactored design):
0. ingest - Extract metadata and prepare PDF for processing
1. ocr - Extract text and structure from PDFs using vision models
2. correction - LLM-based text correction and quality assessment

Future stages (design in progress - see Issue #56):
- Structure extraction and assembly (TBD)
"""