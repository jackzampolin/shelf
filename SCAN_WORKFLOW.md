# Scan Intake Workflow Guide

## Quick Start

### First-Time Setup
```bash
# Install dependencies
pip install watchdog

# Make the script executable
chmod +x scan_intake.py

# Run the intake system
python scan_intake.py
```

## Workflow: Scanning Your First Book

### 1. Physical Preparation
- **De-spine the book** (if not already done)
- **Check pages** for tears or stuck-together sheets
- **Remove any staples** or binding remnants
- **Stack pages** in order (the scanner takes up to 50 sheets)

### 2. Scanner Configuration

When your ScanSnap iX1500 arrives:

1. **Install ScanSnap Home** from Fujitsu website
2. **Create a scanning profile** called "Book Digitization":
   - Resolution: **300 DPI** (minimum for OCR)
   - Color mode: **Grayscale** for text-only books
   - File format: **PDF**
   - Duplex: **Enabled** (scans both sides)
   - Save to: `~/Documents/ScanSnap Home/`

### 3. Using the Intake System

Start the intake system:
```bash
python scan_intake.py
```

#### Step-by-Step Process

1. **Choose option 1** - Start new book
   ```
   Book title: The American Caesar
   Author (optional): William Manchester
   ISBN (optional): 978-0316544986
   ```

2. **Load first batch** into scanner (pages 1-50)

3. **Scan the batch** using your Book Digitization profile

4. **Choose option 2** - Add PDF to current book
   ```
   PDF path: ~/Documents/ScanSnap Home/scan_2024-01-29_001.pdf
   Starting page number: 1
   Ending page number: 50
   ```

5. **Repeat** for each 50-page batch:
   - Pages 51-100 → batch 2
   - Pages 101-150 → batch 3
   - etc.

6. **Choose option 3** - Finish current book when done

## Directory Structure Created

```
~/Documents/book_scans/
└── The-American-Caesar/
    ├── metadata.json           # Book info and batch tracking
    ├── raw_pdfs/              # Archive of original scans
    │   ├── The-American-Caesar_p0001-0050.pdf
    │   ├── The-American-Caesar_p0051-0100.pdf
    │   └── ...
    └── batches/               # Working directory for processing
        ├── batch_001/
        │   └── The-American-Caesar_p0001-0050.pdf
        ├── batch_002/
        │   └── The-American-Caesar_p0051-0100.pdf
        └── ...
```

## Metadata Tracking

Each book gets a `metadata.json` file:
```json
{
  "title": "The American Caesar",
  "safe_title": "The-American-Caesar",
  "author": "William Manchester",
  "isbn": "978-0316544986",
  "scan_date": "2024-01-29T10:30:00",
  "batches": [
    {
      "batch_number": 1,
      "filename": "The-American-Caesar_p0001-0050.pdf",
      "page_start": 1,
      "page_end": 50,
      "timestamp": "2024-01-29T10:32:00",
      "status": "pending"
    }
  ],
  "total_pages": 720,
  "status": "complete"
}
```

## Automatic Mode (File Watcher)

Instead of manual intake, you can use the watcher:

1. Start a book: **Option 1**
2. Start the watcher: **Option 5**
3. Scan batches normally - they'll be auto-detected and organized
4. Files must be named with page ranges: `scan_001-050.pdf`

## Tips for Efficient Scanning

### Naming Convention
If you name your PDFs with page numbers in ScanSnap, the system will auto-detect them:
- ✅ `scan_001-050.pdf`
- ✅ `pages_051-100.pdf`
- ✅ `book_101-150.pdf`

### Batch Sizes
- **Standard**: 50 pages (ADF limit)
- **Thick paper**: 30-40 pages
- **Thin/delicate**: 20-30 pages

### Quality Checks
After each batch:
1. Check the PDF opened correctly
2. Verify page count matches expectation
3. Look for skipped/doubled pages
4. Check first and last page numbers

## Next Steps

Once your book is fully scanned and organized:

1. **Pages are ready** for OCR processing
2. **Metadata is tracked** for the entire book
3. **Batches are organized** for parallel processing
4. **Original PDFs are preserved** in `raw_pdfs/`

The organized structure makes it easy to:
- Process batches in parallel
- Resume if interrupted
- Track progress per book
- Maintain provenance

## Troubleshooting

### Scanner produces single PDF for entire book
- Split it using `pdftk` or Preview.app
- Or scan in smaller batches (recommended)

### Pages are out of order
- Check batch numbers in metadata.json
- Rename files to correct page ranges
- Re-run intake

### Missing pages detected
- Check scanner for jams
- Re-scan the missing range
- Add as new batch

### File watcher not detecting
- Check ScanSnap save location
- Ensure PDF extension (not JPEG)
- Check folder permissions

## Command Reference

```bash
# Start intake system
python scan_intake.py

# Options:
1 - Start new book (creates folder structure)
2 - Add PDF batch (moves and organizes)
3 - Finish book (marks complete)
4 - List all books (shows status)
5 - Start watcher (auto-detect mode)
6 - Exit
```

---

Ready to scan! The system will organize everything for the OCR pipeline to process later.