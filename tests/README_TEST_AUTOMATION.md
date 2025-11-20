# Test Results Automation

Automated tracking of extract-toc accuracy tests with git metadata correlation.

## Quick Start

### Run test and auto-save results:
```bash
pytest tests/test_extract_toc_accuracy.py -v -s | tee >(python tests/save_test_results.py)
```

### Compare last two runs:
```bash
python tests/compare_test_results.py --latest
```

### Compare specific runs:
```bash
python tests/compare_test_results.py test_results/result_20251120_120000_abc1234.json test_results/result_20251120_130000_def5678.json
```

---

## How It Works

### 1. `save_test_results.py`

**Purpose**: Automatically save test results with git metadata

**What it captures:**
- Full test output (text report)
- Git commit hash, branch, message
- Changed files since last commit
- Test statistics (perfect match %, entry match %, etc.)
- Timestamp

**Files created:**
```
test_results/
├── result_20251120_120000_abc1234.txt      # Full output
├── result_20251120_120000_abc1234.json     # Metadata + stats
└── latest.json                              # Pointer to most recent
```

**Usage in test pipeline:**
```bash
# Stream output to both console AND save script
pytest tests/test_extract_toc_accuracy.py -v -s | tee >(python tests/save_test_results.py)

# Or save from file
pytest tests/test_extract_toc_accuracy.py -v -s > output.txt
cat output.txt | python tests/save_test_results.py
```

**Filename format:**
`result_<timestamp>_<git-short-hash>.{txt,json}`

Example: `result_20251120_143022_a3c355d.json`

### 2. `compare_test_results.py`

**Purpose**: Compare two test runs and show improvements/regressions

**What it shows:**
- Git metadata (commits, branches, changed files)
- Side-by-side metrics comparison
- Improvement/regression indicators (✅/❌)
- Relative improvement percentage

**Example output:**
```
TEST RESULTS COMPARISON
================================================================================

Run 1: a3c355d (main)
       feat: emphasize visual pattern (names + page numbers) ove
       2025-11-20T11:30:00

Run 2: c576eae (main)
       fix: apply consistent level_name from find phase structur
       2025-11-20T13:10:00

Changed files in Run 2:
  - pipeline/extract_toc/detection/prompts.py
  - pipeline/extract_toc/find/agent/prompts.py

--------------------------------------------------------------------------------

Metric                        Run 1        Run 2       Change
--------------------------------------------------------------------------------
Perfect Match             7 (36.8%)   10 (52.6%)  ✅     +15.8%
Partial Match                    12            8          -4
Errors                            0            1          +1
Avg Title Match              91.5%        97.4%  ✅      +5.9%
Avg Entry Match              87.2%        89.9%  ✅      +2.7%

================================================================================

✅ IMPROVEMENT: +3 books now perfect (42.9% relative improvement)

📊 Remaining: 9 books still need work (47.4%)
```

---

## Workflow

### Iterative Prompt Development:

1. **Make prompt changes** (edit prompts)
2. **Commit changes** (so git metadata is accurate)
3. **Run test with auto-save**:
   ```bash
   pytest tests/test_extract_toc_accuracy.py -v -s | tee >(python tests/save_test_results.py)
   ```
4. **Compare to previous**:
   ```bash
   python tests/compare_test_results.py --latest
   ```
5. **Analyze** - Which books improved? Which regressed?
6. **Iterate** - Refine prompts based on analysis

### Historical Tracking:

All results are saved in `test_results/` with git hashes, so you can:
- Track which commit introduced improvements
- Correlate code changes with accuracy changes
- Analyze trends over time
- Revert to previous prompts if needed

### Finding Specific Results:

```bash
# List all results
ls -lh test_results/

# Find results from specific commit
ls test_results/*abc1234*

# Find results from specific date
ls test_results/result_20251120*

# View latest stats
cat test_results/latest.json | jq '.stats'

# View git info
cat test_results/latest.json | jq '.git'
```

---

## Metadata Format

### JSON Structure:
```json
{
  "timestamp": "2025-11-20T13:10:00",
  "git": {
    "commit_hash": "c576eae123...",
    "commit_short": "c576eae",
    "branch": "main",
    "commit_message": "fix: apply consistent level_name...",
    "changed_files": [
      "pipeline/extract_toc/detection/prompts.py"
    ],
    "is_dirty": false
  },
  "stats": {
    "total_books": 19,
    "perfect_match": 10,
    "perfect_match_pct": 52.6,
    "partial_match": 8,
    "errors": 1,
    "avg_title_match": 97.4,
    "avg_entry_match": 89.9
  },
  "output_file": "test_results/result_20251120_131000_c576eae.txt"
}
```

---

## Advanced Usage

### Query Results with jq:

```bash
# Get perfect match % from all runs
jq -r '.stats.perfect_match_pct' test_results/result_*.json

# Find runs with >50% perfect match
jq -r 'select(.stats.perfect_match_pct > 50) | .git.commit_short' test_results/result_*.json

# List commits and their perfect match %
for f in test_results/result_*.json; do
  echo "$(jq -r '.git.commit_short' $f): $(jq -r '.stats.perfect_match_pct' $f)%"
done | sort -t: -k2 -n
```

### Track Trends:

```bash
# Create CSV of results
echo "timestamp,commit,perfect_match_pct,avg_entry_match" > results.csv
for f in test_results/result_*.json; do
  jq -r '[.timestamp, .git.commit_short, .stats.perfect_match_pct, .stats.avg_entry_match] | @csv' $f >> results.csv
done

# Plot with your favorite tool
```

### Cleanup Old Results:

```bash
# Keep only last 10 results
ls -t test_results/result_*.txt | tail -n +11 | xargs rm
ls -t test_results/result_*.json | tail -n +11 | xargs rm
```

---

## Integration with CI/CD

For future automation:

```bash
# In CI pipeline
pytest tests/test_extract_toc_accuracy.py -v -s > test_output.txt || true
python tests/save_test_results.py < test_output.txt

# Upload results as artifact
# Compare to baseline
# Post comment on PR with comparison
```

---

## Tips

1. **Always commit before testing** - Ensures git metadata is accurate
2. **Use descriptive commit messages** - Easier to understand what changed
3. **Run comparison immediately** - See impact of your changes right away
4. **Save baseline runs** - Keep known-good results for comparison
5. **Track prompts separately** - Use git to version control prompts

---

## Troubleshooting

**Q: "No report found" warning**
A: The input doesn't contain the test report. Make sure you're piping actual test output.

**Q: Git metadata shows "unknown"**
A: Not in a git repository or git command failed. Check `git status` works.

**Q: Can't find previous results**
A: No files in `test_results/` directory. Run test with save script first.

**Q: Results show is_dirty=true**
A: You have uncommitted changes. Commit them before testing for accurate tracking.
