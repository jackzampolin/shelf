#!/bin/bash
# Setup ToC ground truth dataset from existing book scans
# Creates valid book directories for testing extract-toc stage

set -e

BOOK_STORAGE="${BOOK_STORAGE_ROOT:-$HOME/Documents/book_scans}"
GT_ROOT="tests/fixtures/toc_ground_truth"

BOOKS=(
    "accidental-president"
    "admirals"
    "american-caesar"
    "asia-wars"
    "bitter-revolution"
    "china-good-war"
    "china-japan"
    "china-lobby"
    "china-macro"
    "fiery-peace"
    "forgotten-ally"
    "fourth-turning"
    "groves-bomb"
    "hap-arnold"
    "ike-mccarthy"
    "immense-conspiracy"
    "making-bomb"
    "nimitz"
    "right-wing-critics"
)

echo "Setting up ToC ground truth dataset..."
echo "Book storage: $BOOK_STORAGE"
echo "Ground truth root: $GT_ROOT"
echo "Structure: Standard book directory layout for testing"
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

    # Check if extract-toc has run
    if [ ! -f "$book_dir/extract-toc/finder_result.json" ]; then
        echo "  ⚠️  No finder_result.json found (extract-toc not run)"
        continue
    fi

    # Get ToC page range
    toc_start=$(jq -r '.toc_page_range.start_page' "$book_dir/extract-toc/finder_result.json")
    toc_end=$(jq -r '.toc_page_range.end_page' "$book_dir/extract-toc/finder_result.json")
    echo "  ToC pages: $toc_start-$toc_end"

    # Create standard book directory structure
    mkdir -p "$gt_dir/source"
    mkdir -p "$gt_dir/ocr-pages/paddle"
    mkdir -p "$gt_dir/ocr-pages/mistral"
    mkdir -p "$gt_dir/ocr-pages/olm"
    mkdir -p "$gt_dir/.expected/find"
    mkdir -p "$gt_dir/.expected/finalize"

    # Copy metadata.json
    if [ -f "$book_dir/metadata.json" ]; then
        cp "$book_dir/metadata.json" "$gt_dir/metadata.json"
    fi

    # Copy first 50 pages (for find phase)
    echo "  Copying pages 1-50 (source + OCR)..."
    for page in $(seq -f "%04g" 1 50); do
        # Source images
        if [ -f "$book_dir/source/page_$page.png" ]; then
            cp "$book_dir/source/page_$page.png" "$gt_dir/source/" 2>/dev/null || true
        fi
        # Paddle OCR
        if [ -f "$book_dir/ocr-pages/paddle/page_$page.json" ]; then
            cp "$book_dir/ocr-pages/paddle/page_$page.json" "$gt_dir/ocr-pages/paddle/" 2>/dev/null || true
        fi
        # Mistral OCR
        if [ -f "$book_dir/ocr-pages/mistral/page_$page.json" ]; then
            cp "$book_dir/ocr-pages/mistral/page_$page.json" "$gt_dir/ocr-pages/mistral/" 2>/dev/null || true
        fi
        # OLM OCR
        if [ -f "$book_dir/ocr-pages/olm/page_$page.json" ]; then
            cp "$book_dir/ocr-pages/olm/page_$page.json" "$gt_dir/ocr-pages/olm/" 2>/dev/null || true
        fi
    done

    # Copy expected outputs and clean them
    echo "  Copying and cleaning expected results..."

    # Expected find phase output
    if [ -f "$book_dir/extract-toc/finder_result.json" ]; then
        # Copy and clean: keep only toc_found, toc_page_range, structure_summary
        jq '{
            toc_found: .toc_found,
            toc_page_range: .toc_page_range,
            structure_summary: .structure_summary
        }' "$book_dir/extract-toc/finder_result.json" > "$gt_dir/.expected/find/finder_result.json"
    fi

    # Expected final ToC
    if [ -f "$book_dir/extract-toc/toc.json" ]; then
        # Copy and clean: keep only toc.entries with core fields
        jq '{
            toc: {
                entries: (.toc.entries // .entries) | map({
                    entry_number: .entry_number,
                    title: .title,
                    level: .level,
                    level_name: .level_name,
                    printed_page_number: .printed_page_number
                })
            }
        }' "$book_dir/extract-toc/toc.json" > "$gt_dir/.expected/finalize/toc.json"
    fi

    echo "  ✅ Complete"
    echo ""
done

echo "Ground truth dataset setup complete!"
echo ""
echo "Structure: Each book is a valid BookStorage directory"
echo "  - metadata.json, source/, ocr-pages/{paddle,mistral,olm}/"
echo "  - .expected/find/finder_result.json (expected find output)"
echo "  - .expected/finalize/toc.json (expected final ToC)"
echo ""
echo "Usage:"
echo "  pytest tests/test_toc_ground_truth.py -v"
