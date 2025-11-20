#!/bin/bash
# Setup ToC ground truth dataset from existing book scans

set -e

BOOK_STORAGE="${BOOK_STORAGE_ROOT:-$HOME/Documents/book_scans}"
GT_ROOT="tests/fixtures/toc_ground_truth"

BOOKS=(
    "fiery-peace"
    "admirals"
    "groves-bomb"
    "american-caesar"
    "hap-arnold"
)

echo "Setting up ToC ground truth dataset..."
echo "Book storage: $BOOK_STORAGE"
echo "Ground truth root: $GT_ROOT"
echo ""

for book in "${BOOKS[@]}"; do
    echo "Processing $book..."

    book_dir="$BOOK_STORAGE/$book"
    gt_dir="$GT_ROOT/$book"

    # Check if book exists
    if [ ! -d "$book_dir" ]; then
        echo "  ⚠️  Book not found: $book_dir"
        continue
    fi

    # Create structure
    mkdir -p "$gt_dir/find/ocr/paddle"
    mkdir -p "$gt_dir/find/ocr/mistral"
    mkdir -p "$gt_dir/find/ocr/olm"
    mkdir -p "$gt_dir/find/source"
    mkdir -p "$gt_dir/extract/ocr/paddle"
    mkdir -p "$gt_dir/extract/ocr/mistral"
    mkdir -p "$gt_dir/extract/ocr/olm"
    mkdir -p "$gt_dir/extract/source"

    # Get ToC page range from finder_result.json
    if [ -f "$book_dir/extract-toc/finder_result.json" ]; then
        toc_start=$(jq -r '.toc_page_range.start_page' "$book_dir/extract-toc/finder_result.json")
        toc_end=$(jq -r '.toc_page_range.end_page' "$book_dir/extract-toc/finder_result.json")
        echo "  ToC pages: $toc_start-$toc_end"
    else
        echo "  ⚠️  No finder_result.json found"
        continue
    fi

    # Copy FIND phase data (first 50 pages)
    echo "  Copying find phase data (pages 1-50)..."

    if [ -f "$book_dir/extract-toc/finder_result.json" ]; then
        cp "$book_dir/extract-toc/finder_result.json" "$gt_dir/find/expected_result.json"
    fi

    for page in $(seq -f "%04g" 1 50); do
        # Paddle OCR
        if [ -f "$book_dir/ocr-pages/paddle/page_$page.json" ]; then
            cp "$book_dir/ocr-pages/paddle/page_$page.json" "$gt_dir/find/ocr/paddle/"
        fi
        # Mistral OCR
        if [ -f "$book_dir/ocr-pages/mistral/page_$page.json" ]; then
            cp "$book_dir/ocr-pages/mistral/page_$page.json" "$gt_dir/find/ocr/mistral/"
        fi
        # OLM OCR
        if [ -f "$book_dir/ocr-pages/olm/page_$page.json" ]; then
            cp "$book_dir/ocr-pages/olm/page_$page.json" "$gt_dir/find/ocr/olm/"
        fi
        # Source images
        if [ -f "$book_dir/source/page_$page.png" ]; then
            cp "$book_dir/source/page_$page.png" "$gt_dir/find/source/"
        fi
    done

    # Copy EXTRACT phase data (ToC pages only)
    echo "  Copying extract phase data (ToC pages $toc_start-$toc_end)..."

    if [ -f "$book_dir/extract-toc/toc.json" ]; then
        cp "$book_dir/extract-toc/toc.json" "$gt_dir/extract/expected_toc.json"
    fi

    for page in $(seq -f "%04g" $toc_start $toc_end); do
        # Paddle OCR
        if [ -f "$book_dir/ocr-pages/paddle/page_$page.json" ]; then
            cp "$book_dir/ocr-pages/paddle/page_$page.json" "$gt_dir/extract/ocr/paddle/"
        fi
        # Mistral OCR
        if [ -f "$book_dir/ocr-pages/mistral/page_$page.json" ]; then
            cp "$book_dir/ocr-pages/mistral/page_$page.json" "$gt_dir/extract/ocr/mistral/"
        fi
        # OLM OCR
        if [ -f "$book_dir/ocr-pages/olm/page_$page.json" ]; then
            cp "$book_dir/ocr-pages/olm/page_$page.json" "$gt_dir/extract/ocr/olm/"
        fi
        # Source images
        if [ -f "$book_dir/source/page_$page.png" ]; then
            cp "$book_dir/source/page_$page.png" "$gt_dir/extract/source/"
        fi
    done

    # Create metadata.json
    cat > "$gt_dir/metadata.json" <<EOF
{
  "scan_id": "$book",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "toc_page_range": {
    "start_page": $toc_start,
    "end_page": $toc_end
  },
  "total_entries": $(jq -r '.toc.total_entries // .total_entries' "$book_dir/extract-toc/toc.json" 2>/dev/null || echo 'null'),
  "entries_by_level": $(jq -c '.toc.entries_by_level // .entries_by_level' "$book_dir/extract-toc/toc.json" 2>/dev/null || echo 'null'),
  "notes": ""
}
EOF

    echo "  ✅ Complete"
    echo ""
done

echo "Ground truth dataset setup complete!"
echo ""
echo "Usage:"
echo "  python tests/test_toc_extraction.py"
