#!/bin/bash
# Remove pytest.skip() calls that check for Roosevelt data
# Replace with proper asserts or roosevelt_full_book fixture checks

set -e

echo "🔍 Finding and documenting all pytest.skip calls..."
grep -rn "pytest.skip" tests/*.py | tee /tmp/skips_before.txt

echo ""
echo "📝 Summary of changes needed:"
echo "   - Replace roosevelt_book_dir with roosevelt_full_book fixture"
echo "   - Change pytest.skip() to proper assertions or conditional skips"
echo "   - Tests needing full book should check: if roosevelt_full_book is None: pytest.skip()"
echo ""
echo "✅ Manual changes completed in test_correct_stage.py"
echo "⏭️  Remaining: test_fix_stage.py, test_structure_*.py"
echo ""
echo "Run this to see remaining skips:"
echo "  grep -rn 'pytest.skip' tests/*.py"
