# OCR Text Comparison and Merging Techniques

**Research Date:** 2025-11-11
**Context:** Shelf project has 3 OCR providers (Mistral, OlmOCR, PaddleOCR) producing markdown text from the same source images. This research explores standard techniques for comparing and merging their outputs to achieve optimal results.

**Key Constraint:** We operate WITHOUT ground truth - no reference text exists to compare against.

---

## Table of Contents

1. [OCR Quality Metrics](#1-ocr-quality-metrics)
2. [Text Comparison Algorithms](#2-text-comparison-algorithms)
3. [OCR Voting and Consensus Methods](#3-ocr-voting-and-consensus-methods)
4. [Real-World Implementations](#4-real-world-implementations)
5. [Python Libraries and Tools](#5-python-libraries-and-tools)
6. [Recommendations for Strategy A](#6-recommendations-for-strategy-a)
7. [References](#7-references)

---

## 1. OCR Quality Metrics

### 1.1 Character Error Rate (CER)

**Definition:** The percentage of characters incorrectly recognized by OCR.

**Formula:**
```
CER = (Insertions + Deletions + Substitutions) / Total Characters × 100%
```

**Key Points:**
- Uses Levenshtein distance at character level
- 0% = perfect OCR, lower is better
- Typical range: 2-10% for clean English scans
- Good HTR models: ≤5% CER
- **Requires ground truth** for calculation

**Pros:**
- Precise character-level accuracy measurement
- Standard metric in OCR research
- Easy to interpret

**Cons:**
- Requires reference text (ground truth)
- Doesn't capture semantic meaning
- Small character errors can be insignificant (e.g., punctuation)

**References:**
- [Evaluating OCR Output Quality with CER and WER](https://towardsdatascience.com/evaluating-ocr-output-quality-with-character-error-rate-cer-and-word-error-rate-wer-853175297510/)
- [DocuClipper: What Is OCR Accuracy](https://www.docuclipper.com/blog/ocr-accuracy/)

---

### 1.2 Word Error Rate (WER)

**Definition:** The percentage of words containing one or more incorrect characters.

**Formula:**
```
WER = (Word Insertions + Word Deletions + Word Substitutions) / Total Words × 100%
```

**Key Points:**
- Uses Levenshtein distance at word level
- Typically 3-4x higher than CER (one wrong character = entire word error)
- 95% accuracy = 5% WER (good target)
- **Requires ground truth** for calculation

**Example:**
- Text: "The quick brown fox" (4 words)
- OCR: "Teh quik brwon fox" (3 words wrong)
- CER: 16.67% (3 errors / 18 characters)
- WER: 75% (3 errors / 4 words)

**Pros:**
- Better reflects practical usability
- Aligns with human perception of errors
- Standard metric alongside CER

**Cons:**
- Requires ground truth
- Very sensitive (one character error = whole word fails)
- Word segmentation issues can inflate errors

**References:**
- [Comparing CER and WER for OCR Accuracy](https://medium.com/@tam.tamanna18/deciphering-accuracy-evaluation-metrics-in-nlp-and-ocr-a-comparison-of-character-error-rate-cer-e97e809be0c8)
- [Greifswald: Word Error Rate & Character Error Rate](https://rechtsprechung-im-ostseeraum.archiv.uni-greifswald.de/word-error-rate-character-error-rate-how-to-evaluate-a-model/)

---

### 1.3 No-Reference Quality Metrics

**Context:** Since we lack ground truth, we need "blind" quality assessment methods.

**Approaches:**

#### 1.3.1 Confidence Scores
- Modern OCR engines provide per-character/word confidence scores
- Can be used as proxy for quality without ground truth
- **Challenge:** Reliability depends on engine calibration
- Research shows high correlation between confidence and actual error rates

**Key Finding:** "When there is a high enough correlation between word confidence and Word Character Error, the word confidence can be used to calculate a proxy measure for categorizing digitized texts" (Springmann et al.)

#### 1.3.2 Language Model-Based Metrics
- Use standard language models (LM) or masked language models (MLM)
- Assess text plausibility without reference
- Perplexity scores indicate how "natural" the text appears
- Works for assessing OCR quality automatically

#### 1.3.3 Lexicon-Based Metrics
- Check words against dictionaries
- Out-of-vocabulary (OOV) rate
- Simple but effective for detecting obvious errors
- Limited by dictionary coverage (proper nouns, technical terms, etc.)

**Pros:**
- Work without ground truth
- Practical for real-world scenarios
- Can guide merging decisions

**Cons:**
- Indirect measures of quality
- May miss semantically wrong but lexically valid text
- Confidence scores vary by engine calibration

**References:**
- [Confidence-Aware Document OCR Error Detection (2024)](https://arxiv.org/html/2409.04117v1)
- [Unraveling Confidence: OCR Scores as Proxy](https://link.springer.com/chapter/10.1007/978-3-031-41734-4_7)
- [Rerunning OCR: Quality Assessment Without Ground Truth](https://arxiv.org/html/2110.01661)

---

## 2. Text Comparison Algorithms

### 2.1 Levenshtein Distance (Edit Distance)

**Definition:** Minimum number of single-character edits (insertions, deletions, substitutions) to transform one string into another.

**Algorithm:** Dynamic programming, O(n×m) where n, m are string lengths.

**Key Points:**
- Foundation for CER and WER calculations
- Works at character or word level
- Provides quantitative similarity measure
- Can be normalized: `similarity = 1 - (distance / max_length)`

**Use Case for Our Project:**
- Compare individual words/lines from different OCR outputs
- Identify which OCR engine produced the closest match to consensus
- Measure disagreement between providers

**Python Implementation:**
```python
from Levenshtein import distance

text1 = "The quick brown fox"
text2 = "The quik brown fox"
edit_dist = distance(text1, text2)  # Returns: 1
```

**Pros:**
- Simple, well-understood
- Fast implementations available
- Works without ground truth (just needs two texts)

**Cons:**
- Doesn't capture semantic similarity
- Character-level only (unless adapted for words)
- Equal weight to all edit types

**References:**
- [Edit Distance - Wikipedia](https://en.wikipedia.org/wiki/Edit_distance)
- [Levenshtein Distance for Sequence Comparison](https://ieeexplore.ieee.org/document/9097943/)

---

### 2.2 Myers Diff Algorithm

**Definition:** Efficient diff algorithm (O(N×D)) that finds shortest edit script between two sequences.

**Key Points:**
- Powers Git diff, GNU diff, and Google's diff-match-patch
- Optimized for human-readable output
- Generates insertion/deletion/match operations
- More sophisticated than simple Levenshtein

**Use Case for Our Project:**
- Visualize differences between OCR outputs
- Identify specific regions of disagreement
- Generate patches/merges

**Python Implementation:**
```python
from diff_match_patch import diff_match_patch

dmp = diff_match_patch()
diffs = dmp.diff_main("text1", "text2")
dmp.diff_cleanupSemantic(diffs)  # Human-readable cleanup
```

**Pros:**
- Human-readable diff output
- Efficient performance
- Battle-tested (used in Google Docs since 2006)
- Includes fuzzy matching and patching

**Cons:**
- More complex than simple edit distance
- Designed for full-text comparison (may be overkill for word-level)

**References:**
- [Google diff-match-patch](https://github.com/google/diff-match-patch)
- [Myers 1986 Algorithm](https://neil.fraser.name/writing/diff/)
- [Practical Guide to Diff Algorithms](https://ably.com/blog/practical-guide-to-diff-algorithms)

---

### 2.3 Sequence Alignment Algorithms

**Context:** Borrowed from bioinformatics, these algorithms align sequences optimally.

#### 2.3.1 Needleman-Wunsch Algorithm
**Type:** Global alignment (aligns entire sequences)

**Key Points:**
- Dynamic programming: O(n×m)
- Customizable scoring: match reward, mismatch penalty, gap penalty
- Produces optimal alignment with gaps
- Used in Microsoft's Genalog for OCR text alignment

**Use Case for Our Project:**
- Align OCR outputs that may have missing/extra characters
- Handle insertion/deletion errors gracefully
- Foundation for multi-sequence alignment

**Python Implementation:**
```python
from Bio import pairwise2
from Bio.pairwise2 import format_alignment

# Align two sequences
alignments = pairwise2.align.globalms(
    "THECATINHAT",
    "TEHATINHAT",
    match=2,      # Match score
    mismatch=-1,  # Mismatch penalty
    open=-2,      # Gap open penalty
    extend=-0.5   # Gap extend penalty
)

# Best alignment
print(format_alignment(*alignments[0]))
```

**Output:**
```
THECATINHAT
|| |||||||
TE-HATINHAT
```

**Alternative Libraries:**
- [PySeq](https://farhanma.github.io/pyseq/) - N-W and Hirschberg's algorithm
- [minineedle](https://github.com/scastlara/minineedle) - Lightweight implementation

#### 2.3.2 Smith-Waterman Algorithm
**Type:** Local alignment (finds best matching subsequences)

**Key Points:**
- Finds optimal local regions of similarity
- Useful when texts have large insertions/deletions
- More computationally expensive than global alignment

**Use Case for Our Project:**
- Less relevant (we expect mostly complete texts)
- Could help with severely corrupted pages

**Pros (Both Algorithms):**
- Handle gaps/insertions elegantly
- Customizable scoring schemes
- Proven in bioinformatics

**Cons:**
- O(n×m) can be slow for long texts
- Requires tuning scoring parameters
- May be overkill for simple comparisons

**References:**
- [Needleman-Wunsch in Python (Gist)](https://gist.github.com/slowkow/06c6dba9180d013dfd82bec217d22eb5)
- [Microsoft Genalog Text Alignment](https://microsoft.github.io/genalog/text_alignment.html)
- [Biopython pairwise2](https://biopython.org/docs/1.75/api/Bio.pairwise2.html)

---

### 2.4 N-gram Similarity

**Definition:** Compare texts based on overlapping character or word n-grams.

**Key Points:**
- N-gram = sequence of n consecutive items (chars/words)
- Similarity measured via Jaccard, Cosine, Dice coefficients
- Works at character level (trigrams common) or word level
- Captures local patterns

**Approach:**
1. Extract n-grams from both texts
2. Compute overlap (intersection)
3. Calculate similarity score

**Example (Character Trigrams):**
```
Text1: "the cat"
Trigrams: {the, he , e c, ca, cat}

Text2: "the dog"
Trigrams: {the, he , e d, do, dog}

Jaccard = |intersection| / |union| = 2/8 = 0.25
```

**Python Implementation:**
```python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(3, 3))
tfidf_matrix = vectorizer.fit_transform([text1, text2])
similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
```

**Use Case for Our Project:**
- Fast approximate similarity
- Useful for ranking OCR outputs
- Works well for finding similar but not identical texts

**Pros:**
- Fast computation
- Robust to small variations
- No alignment needed

**Cons:**
- **Lexical similarity only** (not semantic)
- May miss reordering
- Requires tuning n-gram size

**References:**
- [N-gram Similarity with Cosine](https://stackoverflow.com/questions/4037174/n-gram-sentence-similarity-with-cosine-similarity-measurement)
- [N-Grams for Text Similarity Detection](https://www.mdpi.com/2076-3417/9/9/1870)

---

### 2.5 Semantic Similarity (Advanced)

**Context:** N-grams measure lexical similarity, but semantic similarity captures meaning.

**Approaches:**
- **Word embeddings:** Word2Vec, GloVe, FastText
- **Sentence embeddings:** Sentence-BERT, Universal Sentence Encoder
- **Soft cosine similarity:** Uses word embeddings in cosine calculation

**Key Point:** "Two sentences may be similar without using the same words" - semantic approaches address this.

**Use Case for Our Project:**
- **Limited applicability:** OCR outputs are supposed to be *identical* text
- Semantic similarity is more for paraphrase detection
- Could help detect major OCR hallucinations vs. real content

**Pros:**
- Captures meaning beyond exact words
- State-of-the-art for paraphrase detection

**Cons:**
- Computationally expensive
- Requires pre-trained models
- Overkill for our use case (we want exact text matching)

**References:**
- [Semantic Similarity Methods Comparison](https://arxiv.org/pdf/1910.09129)
- [Soft Cosine Similarity](https://medium.com/@bravekjh/unlocking-the-power-of-fuzzy-matching-in-python-a-practical-guide-ec37ebd8f3eb)

---

## 3. OCR Voting and Consensus Methods

### 3.1 ROVER (Recognizer Output Voting Error Reduction)

**Origin:** Developed at NIST, originally for speech recognition, adapted for OCR.

**Core Concept:** Combine multiple recognizer outputs through alignment and voting to produce composite output with lower error rate than any individual system.

**How It Works:**

1. **Alignment Phase:**
   - Use dynamic programming to align all OCR outputs
   - Build a Word Transition Network (WTN)
   - Find optimal alignment across N systems

2. **Voting Phase:**
   - At each aligned position, vote for best token
   - Voting schemes:
     - **Frequency:** Most common token wins
     - **Average confidence:** Highest mean confidence wins
     - **Maximum confidence:** Highest individual confidence wins

**Key Findings:**
- 20-50% error reduction when combining 3 OCR scans
- Works at character, word, or line level
- Performs as well or better than simple majority voting

**Algorithm Overview:**
```
Input: N OCR outputs (O₁, O₂, ..., Oₙ)

1. Pairwise align all outputs using dynamic programming
2. Build multiple sequence alignment (MSA)
3. For each aligned position:
   - Collect all candidate tokens
   - Score candidates by voting scheme
   - Select winner
4. Output: Merged sequence
```

**Voting Example:**
```
OCR1: "The quick brown fox"
OCR2: "The quik brown fox"
OCR3: "The quick brown fox"

Position 2 (word):
  - "quick" (2 votes) ← Winner
  - "quik"  (1 vote)

Result: "The quick brown fox"
```

**LV-ROVER (Lexicon-Verified ROVER):**
- Enhanced version for handwriting recognition
- Adds lexicon verification step
- Reduced complexity vs. original ROVER
- Can combine hundreds of recognizers

**Use Case for Our Project:**
- **Perfect fit:** We have 3 OCR outputs for same images
- Word-level voting seems most appropriate
- Can use confidence scores if available

**Pros:**
- Well-researched, proven approach
- Significant error reduction (20-50%)
- Flexible voting schemes
- No ground truth needed

**Cons:**
- Requires alignment (computational cost)
- Works best with 3+ systems
- May struggle with systematic errors (all systems wrong)

**References:**
- [ROVER Paper (NIST)](https://www.researchgate.net/publication/2397671_A_Post-Processing_System_To_Yield_Reduced_Word_Error_Rates_Recognizer_Output_Voting_Error_Reduction_ROVER)
- [LV-ROVER for Handwriting](https://arxiv.org/abs/1707.07432)
- [SCTK ROVER Documentation](https://github.com/usnistgov/SCTK/blob/master/doc/rover.1)
- [Using Consensus Sequence Voting (OCR)](https://www.semanticscholar.org/paper/Using-Consensus-Sequence-Voting-to-Correct-OCR-Lopresti-Zhou/e17d8b64d137e904fa611b7be082090f5cbe0625)

---

### 3.2 Multi-Sequence Alignment (MSA)

**Context:** Extension of pairwise alignment (Needleman-Wunsch) to N sequences.

**Approaches:**

#### 3.2.1 Progressive Alignment
**Method:**
1. Align two most similar sequences
2. Add third sequence to alignment
3. Continue until all sequences aligned

**Use Case:** Foundation of many consensus methods

#### 3.2.2 Character Confidence-Based MSA (Ocromore)
**Method:**
- Word-wise alignment
- Character-level confidence scores
- Select characters with highest confidence at each position

**Results:** 33% error reduction, 0.49% accuracy increase (Ocromore study)

**Use Case for Our Project:**
- **Highly relevant** if confidence scores available
- Word-wise approach fits markdown structure
- Proven results on real OCR data

**Pros:**
- Uses confidence information
- Proven error reduction
- Open-source implementation exists (Ocromore)

**Cons:**
- Requires confidence scores
- More complex than simple voting
- Computational overhead

**References:**
- [Progressive Multiple Alignment (BioPython)](https://biopython.org/wiki/AlignIO)
- [Ocromore: Character Confidence MSA](https://zenodo.org/records/1493860)

---

### 3.3 Voting Granularity: Character vs. Word vs. Line Level

**Recent Research Finding (2024):** Line-level OCR is becoming superior to word-level.

#### 3.3.1 Character-Level Voting
**Pros:**
- Maximum granularity
- Can fix single-character errors

**Cons:**
- Segmentation errors confound voting
- Character split/merge issues
- High computational cost

**Best for:** Handwriting, heavily degraded text

#### 3.3.2 Word-Level Voting
**Pros:**
- Natural unit of meaning
- Aligns with language models
- Easier alignment

**Cons:**
- Word segmentation errors propagate
- One character wrong = entire word rejected
- Punctuation challenges

**Best for:** Clean printed text, moderate quality

#### 3.3.3 Line-Level Voting
**Pros:**
- **Maximum context for language models**
- Avoids word segmentation errors
- Handles skewed/warped pages better
- Better punctuation recognition (needs sentence context)

**Cons:**
- Coarser granularity
- Requires good line segmentation (usually reliable)

**Key Insight:** "The bottleneck in accuracy has moved to word segmentation, so line-level OCR bypasses errors in word detection and provides larger sentence context."

**Recommendation for Our Project:**
- **Markdown preserves line structure** - natural fit
- Start with line-level comparison
- Drop to word-level for fine-grained merging
- Character-level only for specific corrections

**References:**
- [Why Stop at Words? Line-Level OCR (2024)](https://arxiv.org/html/2508.21693v1)
- [Voting-Based OCR System](https://www.researchgate.net/publication/326016983_VOTING-BASED_OCR_SYSTEM)
- [Consensus Sequence Voting](https://www.sciencedirect.com/science/article/abs/pii/S1077314296905020)

---

### 3.4 Confidence-Based Merging

**Concept:** Weight votes by OCR engine confidence scores.

**Approaches:**

#### 3.4.1 Weighted Voting
```
Score(token) = Σ (confidence_i × vote_i)
```

**Example:**
```
OCR1: "color" (confidence: 0.95)
OCR2: "colour" (confidence: 0.80)
OCR3: "color" (confidence: 0.92)

Weighted score:
  "color":  (0.95 + 0.92) / 2 = 0.935
  "colour": 0.80 / 1 = 0.80

Winner: "color"
```

#### 3.4.2 Confidence Thresholding
- Only consider OCR outputs above confidence threshold
- Discard low-confidence regions
- Fallback to voting if all low confidence

**Key Finding:** "Confidence-based voting boosts results by an additional 8%, leading to a total average improvement of about 17%."

**Caveat:** "The reliability of confidence score as a measure of quality is largely dependent on the way the engine has been configured."

**Use Case for Our Project:**
- **Check if our OCR providers give confidence scores**
  - Mistral: Likely (modern VLM)
  - OlmOCR: Uncertain
  - PaddleOCR: Yes (supports confidence)
- If available: use weighted voting
- If not: use frequency-based voting

**Pros:**
- Better accuracy than unweighted voting
- Accounts for OCR engine certainty
- Proven 8-17% improvement

**Cons:**
- Requires confidence scores
- Confidence calibration varies by engine
- May need per-engine tuning

**References:**
- [ConfBERT: Confidence-Aware Error Detection (2024)](https://arxiv.org/html/2409.04117v1)
- [Improving OCR by Cross-Fold Training and Voting](https://www.researchgate.net/publication/325994888_Improving_OCR_Accuracy_on_Early_Printed_Books_by_Utilizing_Cross_Fold_Training_and_Voting)

---

## 4. Real-World Implementations

### 4.1 Ocromore

**Organization:** University Library of Mannheim (UB-Mannheim)

**Description:** Command-line post-processing tool for combining multiple OCR outputs.

**Technical Details:**
- **Language:** Python 3.6+
- **Storage:** SQLite database via pandas
- **Algorithm:** Word-wise character confidence-based MSA
- **License:** Apache 2.0 (Free/Open Source)

**Features:**
- Parses different OCR output formats
- Multi-sequence alignment
- Character accuracy increase: +0.49%
- Error reduction: 33% vs. best single OCR

**Use Case for Our Project:**
- **Directly applicable** to our scenario
- Open source - can study implementation
- Proven results on real documents

**Repository:** [UB-Mannheim/ocromore](https://github.com/UB-Mannheim/ocromore)

**References:**
- [Ocromore - Zenodo](https://zenodo.org/records/1493860)
- [GitHub Repository](https://github.com/UB-Mannheim/ocromore)

---

### 4.2 Google Books

**Approach:** Multiple OCR processing pipeline

**Key Insights:**
- Uses OCR to transform raw images to text
- De-warping algorithms using LIDAR data
- Extracts page numbers, footnotes, illustrations
- Adaptive language and image models

**Challenges Addressed:**
- Different fonts in old books
- Scanning blur
- Character/word warping at book edges

**OCR Technology:**
- Historically used OCRopus (designed for high-volume projects)
- Now likely proprietary systems

**Relevance to Our Project:**
- Large-scale book scanning faces similar challenges
- Emphasis on handling degraded/varied content
- Multi-stage processing pipeline

**References:**
- [Improving Book OCR (Google Research)](https://research.google/pubs/improving-book-ocr-by-adaptive-language-and-image-models/)
- [Google Books - Wikipedia](https://en.wikipedia.org/wiki/Google_Books)

---

### 4.3 Internet Archive

**Approach:** Transitioned to open-source OCR

**Key Changes:**
- Moving to Tesseract/OCRopus
- Leveraging PDF libraries
- FOSS (Free and Open Source) emphasis

**OCR Workflow:**
- HathiTrust and Internet Archive book processing
- 3.5+ million books digitized
- Available in Google BigQuery

**Relevance to Our Project:**
- Proves viability of open-source OCR at scale
- Similar challenges: old books, varied quality
- Community-driven improvements

**References:**
- [FOSS Wins: 19th Century Newspapers](https://blog.archive.org/2020/11/23/foss-wins-again-free-and-open-source-communities-comes-through-on-19th-century-newspapers-and-books-and-periodicals/)
- [GDELT: 3.5M Books Processed](https://blog.gdeltproject.org/3-5-million-books-1800-2015-gdelt-processes-internet-archive-and-hathitrust-book-archives-and-available-in-google-bigquery/)

---

### 4.4 MEMOE (Multi-Evidence Multi-OCR-Engine)

**Description:** Research system combining multiple OCR engines with various evidence types.

**Approach:**
- Combines output streams from one or more OCR engines
- Integrates various types of evidence
- Produces higher quality output than individual engines

**Performance:**
- Performs as well or better than majority voting
- Especially effective with multiple engines

**Relevance to Our Project:**
- Validates multi-engine approach
- Shows evidence beyond just OCR text can help
- Academic validation of consensus methods

**References:**
- [A Multi-Evidence, Multi-Engine OCR System](https://www.researchgate.net/publication/252980446_A_multi-evidence_multi-engine_OCR_system)

---

### 4.5 Microsoft Genalog

**Description:** Text alignment for OCR using Needleman-Wunsch

**Use Case:**
- Align correct transcripts to text images
- Uses "messy" OCR output
- Bioinformatics-style sequence alignment

**Technical Details:**
- Biopython's Needleman-Wunsch implementation
- Handles OCR with insertions/deletions
- Produces aligned text for training data generation

**Relevance to Our Project:**
- Shows sequence alignment applied to OCR
- Microsoft-quality implementation
- Could adapt for multi-OCR alignment

**Repository:** [DDMAL/text_alignment](https://github.com/DDMAL/text_alignment)

**References:**
- [Genalog Text Alignment Docs](https://microsoft.github.io/genalog/text_alignment.html)

---

## 5. Python Libraries and Tools

### 5.1 RapidFuzz

**Description:** Fast string matching library for Python and C++

**Performance:**
- **2,500 text pairs/second** (fastest in benchmarks)
- 40% faster than alternatives
- Built in C++ for speed

**Features:**
- Levenshtein distance
- Token-based comparison
- Unicode support
- FuzzyWuzzy-compatible API

**Comparison:**
```
RapidFuzz:   2,500 pairs/sec
Levenshtein: 1,800 pairs/sec
Jellyfish:   1,600 pairs/sec
FuzzyWuzzy:  1,200 pairs/sec
difflib:     1,000 pairs/sec
```

**Use Case for Our Project:**
- **Primary choice** for fast text similarity
- Batch comparison of OCR outputs
- Word-level matching in voting

**Installation:**
```bash
pip install rapidfuzz
```

**Example:**
```python
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

# Simple similarity
similarity = fuzz.ratio("The quick brown fox", "The quik brown fox")  # 94.74

# Levenshtein distance
distance = Levenshtein.distance("quick", "quik")  # 1

# Token-based (order-independent)
token_sort = fuzz.token_sort_ratio("fox brown quick", "quick brown fox")  # 100
```

**Pros:**
- Fastest available
- Comprehensive features
- Active maintenance
- Drop-in replacement for FuzzyWuzzy

**Cons:**
- C++ dependency (build requirements)

**References:**
- [RapidFuzz GitHub](https://github.com/rapidfuzz)
- [RapidFuzz vs Difflib](https://dev.to/mrquite/smart-text-matching-rapidfuzz-vs-difflib-ge5)
- [Comparative Analysis of Python Text Matching](https://media.neliti.com/media/publications/617608-a-comparative-analysis-of-python-text-ma-d5e66ac3.pdf)

---

### 5.2 python-Levenshtein

**Description:** Fast C extension for Levenshtein distance computation

**Status:** Now an alias to RapidFuzz's Levenshtein module (backward compatibility)

**Features:**
- Character/word edit distance
- String similarity ratios
- Faster than difflib for strings

**Use Case for Our Project:**
- If already using python-Levenshtein, continue (now uses RapidFuzz backend)
- Otherwise, use RapidFuzz directly

**Installation:**
```bash
pip install Levenshtein
```

**Example:**
```python
from Levenshtein import distance, ratio

d = distance("kitten", "sitting")  # 3
r = ratio("kitten", "sitting")     # 0.615
```

**Pros:**
- Well-known library
- Now backed by RapidFuzz (fast)
- Simple API

**Cons:**
- Legacy name (prefer RapidFuzz)
- String-only (not arbitrary sequences)

**References:**
- [Levenshtein Documentation](https://rapidfuzz.github.io/Levenshtein/)
- [GitHub Repository](https://github.com/rapidfuzz/Levenshtein)

---

### 5.3 difflib (Python Standard Library)

**Description:** Built-in Python library for sequence comparison

**Features:**
- SequenceMatcher class
- Unified/context diff formats
- Human-readable output
- No installation required

**Performance:**
- Slowest of major libraries (1,000 pairs/sec)
- Higher memory usage
- Pure Python implementation

**Use Case for Our Project:**
- **Avoid for performance-critical code**
- Use for debugging/visualization
- Alternative: CyDifflib (faster drop-in replacement)

**Example:**
```python
from difflib import SequenceMatcher

s = SequenceMatcher(None, "The quick brown fox", "The quik brown fox")
ratio = s.ratio()  # 0.95

# Get diff operations
for tag, i1, i2, j1, j2 in s.get_opcodes():
    print(f"{tag}: s1[{i1}:{i2}] s2[{j1}:{j2}]")
```

**Output:**
```
equal:  s1[0:5] s2[0:5]     # "The q"
delete: s1[5:6] s2[5:5]     # "u"
equal:  s1[6:19] s2[5:18]   # "ick brown fox"
```

**Pros:**
- No dependencies (stdlib)
- Human-readable diffs
- Works with arbitrary sequences (not just strings)

**Cons:**
- Slow performance
- High memory usage
- Not optimized for large-scale comparisons

**References:**
- [difflib Documentation](https://docs.python.org/3/library/difflib.html)
- [CyDifflib (faster drop-in)](https://github.com/cyruseuros/cydifflib)

---

### 5.4 diff-match-patch

**Description:** Google's high-performance diff/match/patch library

**Origin:** Powers Google Docs (since 2006)

**Features:**
- **Diff:** Myers algorithm with semantic cleanup
- **Match:** Fuzzy matching (Bitap algorithm)
- **Patch:** Apply diffs to create patches

**Languages:** C++, C#, Dart, Java, JavaScript, Lua, Objective-C, Python

**Use Case for Our Project:**
- **Excellent for full-text comparison**
- Visualizing differences between OCR outputs
- Generating patches/merges

**Installation:**
```bash
pip install diff-match-patch
```

**Example:**
```python
from diff_match_patch import diff_match_patch

dmp = diff_match_patch()

# Compute diff
text1 = "The quick brown fox jumps"
text2 = "The quik brown fox leaps"
diffs = dmp.diff_main(text1, text2)

# Clean up for readability
dmp.diff_cleanupSemantic(diffs)

# Result: list of (operation, text) tuples
# [(EQUAL, "The "), (DELETE, "quick"), (INSERT, "quik"), ...]

# Fuzzy matching
match_index = dmp.match_main("The quick brown fox", "quik", 5)  # Returns position
```

**Pros:**
- Battle-tested (Google Docs)
- Semantic cleanup for human readability
- Fuzzy matching included
- Multi-language support

**Cons:**
- Designed for full documents (may be overkill)
- Python port is older than original

**References:**
- [diff-match-patch GitHub](https://github.com/google/diff-match-patch)
- [Practical Guide to Diff Algorithms](https://ably.com/blog/practical-guide-to-diff-algorithms)

---

### 5.5 BioPython (pairwise2)

**Description:** Bioinformatics library with sequence alignment tools

**Features:**
- Needleman-Wunsch (global alignment)
- Smith-Waterman (local alignment)
- Customizable scoring matrices
- Gap penalties

**Use Case for Our Project:**
- **Overkill for simple comparisons**
- Useful if we need gap handling
- Educational value (understand alignment)

**Installation:**
```bash
pip install biopython
```

**Example:**
```python
from Bio import pairwise2
from Bio.pairwise2 import format_alignment

alignments = pairwise2.align.globalms(
    "THECATINHAT",
    "TEHATINHAT",
    match=2,
    mismatch=-1,
    open=-2,
    extend=-0.5
)

# Print best alignment
print(format_alignment(*alignments[0]))
```

**Output:**
```
THECATINHAT
|| |||||||
TE-HATINHAT
  Score=15
```

**Pros:**
- Handles gaps elegantly
- Customizable scoring
- Well-documented

**Cons:**
- Heavy dependency for text comparison
- O(n×m) can be slow
- Designed for DNA/protein sequences

**References:**
- [BioPython Documentation](https://biopython.org/docs/1.75/api/Bio.pairwise2.html)
- [BioPython Sequence Alignment](https://www.geeksforgeeks.org/python/biopython-sequence-alignment/)

---

### 5.6 Specialized OCR Tools

#### 5.6.1 Ocromore
**Language:** Python 3.6+
**Purpose:** Combine multiple OCR outputs
**Status:** Open source (Apache 2.0)

**Repository:** [UB-Mannheim/ocromore](https://github.com/UB-Mannheim/ocromore)

**Use Case:**
- **Study implementation** for our own merging code
- Potentially adapt/fork for our needs
- Reference for MSA approach

---

### 5.7 Library Recommendations Summary

| Library | Speed | Use Case | Complexity | Install |
|---------|-------|----------|------------|---------|
| **RapidFuzz** | ⭐⭐⭐⭐⭐ | Fast similarity, voting | Low | pip |
| python-Levenshtein | ⭐⭐⭐⭐⭐ | Edit distance | Low | pip |
| diff-match-patch | ⭐⭐⭐⭐ | Full-text diff/patch | Medium | pip |
| difflib | ⭐⭐ | Debugging/visualization | Low | stdlib |
| BioPython | ⭐⭐⭐ | Alignment with gaps | High | pip |
| Ocromore | N/A | OCR-specific merging | High | Manual |

**Recommended Stack for Shelf:**
1. **RapidFuzz** - Primary similarity/distance calculations
2. **diff-match-patch** - Full-text comparison and visualization
3. **difflib** - Quick debugging (already available)
4. **Ocromore** - Study implementation, possibly adapt code

---

## 6. Recommendations for Strategy A

**Context:** Strategy A aims to merge outputs from Mistral, OlmOCR, and PaddleOCR to achieve optimal markdown text.

### 6.1 Overall Approach: ROVER-Inspired Voting

**Rationale:**
- Proven 20-50% error reduction with 3 OCR systems
- No ground truth required
- Well-researched methodology
- Fits our scenario perfectly

**Proposed Algorithm:**

```
1. PRE-PROCESSING
   - Load all 3 OCR outputs (markdown format)
   - Parse into comparable units (lines/words)
   - Extract confidence scores (if available)

2. ALIGNMENT PHASE
   - Use line-level alignment (markdown preserves lines)
   - For each line:
     a. If all 3 OCR outputs agree → keep as-is
     b. If 2/3 agree → use majority (fast path)
     c. If 0/3 agree → proceed to word-level voting

3. WORD-LEVEL VOTING (for disagreements)
   - Align words using Needleman-Wunsch or difflib
   - For each word position:
     - Collect candidates from all 3 OCRs
     - Vote using confidence-weighted or frequency-based
     - Select winner

4. CHARACTER-LEVEL CORRECTION (optional, for stubborn errors)
   - Only for high-disagreement regions
   - Use edit distance to find best character-level match

5. POST-PROCESSING
   - Reconstruct markdown structure
   - Preserve formatting (headers, lists, tables)
   - Output merged markdown
```

---

### 6.2 Implementation Phases

#### Phase 1: Simple Majority Voting (Baseline)
**Goal:** Quick win with minimal complexity

**Steps:**
1. Split all 3 OCR outputs into lines
2. For each line:
   - If 2+ OCRs agree → use that version
   - If all 3 differ → use edit distance to pick "median" (closest to others)
3. Merge into final markdown

**Libraries:**
- RapidFuzz for fast line comparison

**Expected Result:**
- 20-30% error reduction (conservative estimate based on ROVER)
- Fast implementation (1-2 days)

**Code Sketch:**
```python
from rapidfuzz import fuzz
from collections import Counter

def merge_lines(ocr_lines_list):
    """Merge lines from 3 OCR outputs using majority voting."""
    merged = []

    for line_tuple in zip(*ocr_lines_list):  # (mistral_line, olm_line, paddle_line)
        # Check for exact matches
        counts = Counter(line_tuple)
        most_common, count = counts.most_common(1)[0]

        if count >= 2:
            # Majority agreement
            merged.append(most_common)
        else:
            # All different - pick median by edit distance
            median_line = find_median_line(line_tuple)
            merged.append(median_line)

    return merged

def find_median_line(lines):
    """Find line with minimum total edit distance to others."""
    scores = []
    for candidate in lines:
        total_distance = sum(
            fuzz.distance(candidate, other)
            for other in lines if other != candidate
        )
        scores.append((total_distance, candidate))

    return min(scores)[1]  # Return line with minimum distance
```

---

#### Phase 2: Confidence-Weighted Voting
**Goal:** Leverage OCR confidence scores for better accuracy

**Prerequisites:**
- Investigate which OCR providers return confidence scores:
  - Mistral OCR: Check API response
  - OlmOCR: Check documentation
  - PaddleOCR: **Yes** (supports confidence)

**Steps:**
1. Modify Phase 1 to include confidence scores
2. For disagreements, weight votes by confidence
3. Fall back to frequency voting if no confidence available

**Expected Result:**
- Additional 8-17% improvement (per research)
- 2-3 days implementation

**Code Sketch:**
```python
def confidence_weighted_vote(candidates):
    """Vote using confidence scores."""
    # candidates = [(text, confidence), ...]

    if all(conf is None for _, conf in candidates):
        # No confidence scores - fall back to frequency
        return frequency_vote([text for text, _ in candidates])

    # Weighted by confidence
    scores = {}
    for text, conf in candidates:
        scores[text] = scores.get(text, 0) + (conf or 0.5)  # Default 0.5 if None

    return max(scores.items(), key=lambda x: x[1])[0]
```

---

#### Phase 3: Multi-Sequence Alignment (MSA)
**Goal:** Handle insertions/deletions gracefully

**When Needed:**
- OCR outputs have significantly different lengths
- Missing/extra words due to layout detection errors

**Steps:**
1. Use Needleman-Wunsch to align all 3 outputs
2. Build consensus sequence allowing gaps
3. Vote at each aligned position

**Libraries:**
- BioPython pairwise2 (for alignment)
- Or adapt Ocromore's MSA implementation

**Expected Result:**
- Handle edge cases Phase 1/2 miss
- 5-7 days implementation (more complex)

**Code Sketch:**
```python
from Bio import pairwise2

def align_three_sequences(seq1, seq2, seq3):
    """Progressive alignment of 3 sequences."""
    # Step 1: Align first two
    alignment_12 = pairwise2.align.globalms(
        seq1, seq2,
        match=2, mismatch=-1, open=-2, extend=-0.5
    )[0]

    # Step 2: Align third to consensus of first two
    consensus_12 = make_consensus(alignment_12)
    alignment_final = pairwise2.align.globalms(
        consensus_12, seq3,
        match=2, mismatch=-1, open=-2, extend=-0.5
    )[0]

    return alignment_final
```

---

#### Phase 4: Markdown Structure Preservation
**Goal:** Ensure voting doesn't break markdown formatting

**Challenges:**
- Headers (`#`, `##`, etc.)
- Lists (`-`, `*`, `1.`)
- Tables (alignment, pipes)
- Code blocks (backticks)

**Steps:**
1. Parse markdown into structural elements
2. Vote within structural boundaries (don't mix header with paragraph)
3. Preserve markdown syntax tokens

**Libraries:**
- Consider lightweight markdown parser
- Or regex-based structure detection

**Expected Result:**
- Clean, valid markdown output
- 3-4 days implementation

---

### 6.3 Quality Assessment (Without Ground Truth)

**Metrics to Track:**

#### 6.3.1 Agreement Metrics
- **Line agreement rate:** % of lines where 2+ OCRs agree
- **Word agreement rate:** % of words where 2+ OCRs agree
- **Character agreement rate:** % of characters where 2+ OCRs agree

**Interpretation:**
- High agreement → OCRs are reliable, merging adds little
- Low agreement → OCRs are struggling, merging critical

#### 6.3.2 Confidence Scores
- **Average confidence:** Mean confidence across merged output
- **Low-confidence regions:** Flag areas where all OCRs have low confidence

#### 6.3.3 Language Model Perplexity
- **Optional:** Use GPT/BERT to assess text plausibility
- Lower perplexity → more natural text

#### 6.3.4 Lexicon-Based Metrics
- **OOV rate:** Out-of-vocabulary words (spell check)
- **Dictionary hit rate:** % of words in English dictionary

**Dashboard Idea:**
```
Merged OCR Quality Report
==========================
Lines processed: 1,234
Agreement rate:  78.5% (2+ OCRs agree)
Voting decisions: 265 (21.5% required voting)
Average confidence: 0.87

Low-confidence regions: 12 (flagged for review)
OOV rate: 3.2%
```

---

### 6.4 Markdown-Specific Considerations

**Key Insight:** Markdown output from OCR preserves document structure, which we must respect.

#### 6.4.1 Structural Elements to Preserve
- **Headings:** `#`, `##`, `###`, etc.
- **Lists:** Ordered (`1.`, `2.`) and unordered (`-`, `*`)
- **Tables:** Pipe-delimited with alignment
- **Emphasis:** `*italic*`, `**bold**`
- **Code blocks:** `` ` `` and ` ``` `
- **Links/Images:** `[text](url)`, `![alt](image)`

#### 6.4.2 Voting Strategy by Element Type

**Headers:**
- Vote on header text content
- Preserve header level (`#` count) if 2+ agree
- Be cautious: OCR might misread `##` as `#` or vice versa

**Tables:**
- Most challenging: alignment is critical
- Vote cell-by-cell (not line-by-line)
- Consider: pick single best OCR for entire table (avoid mixing)

**Lists:**
- Vote on list item content
- Preserve list markers (`-`, `*`, `1.`)
- Watch for indentation (nested lists)

**Code Blocks:**
- OCR often struggles with code (monospace fonts)
- Flag code blocks for manual review
- Or: pick single best OCR for code sections

#### 6.4.3 Implementation Note
```python
def vote_by_element_type(element_type, ocr_candidates):
    """Vote differently based on markdown element type."""

    if element_type == "table":
        # Pick best single OCR (avoid mixing table cells)
        return pick_best_table(ocr_candidates)

    elif element_type == "code":
        # Flag for review
        log_for_review(ocr_candidates)
        return majority_vote(ocr_candidates)

    else:
        # Standard voting
        return majority_vote(ocr_candidates)
```

---

### 6.5 Cost vs. Accuracy Trade-offs

**Context:** We're merging OCR outputs to avoid re-OCR costs, but merging itself has computational cost.

#### 6.5.1 Computational Cost Tiers

| Phase | Complexity | Time per Page | Accuracy Gain |
|-------|------------|---------------|---------------|
| Phase 1: Majority Voting | O(n) | ~0.1s | +20-30% |
| Phase 2: Confidence Weighted | O(n) | ~0.2s | +8-17% |
| Phase 3: MSA | O(n²) | ~1-5s | +5-10% |
| Phase 4: Markdown Aware | O(n) | +0.3s | Quality preservation |

**Recommendation:**
- **Start with Phase 1** - best ROI
- **Add Phase 2** if confidence scores available
- **Phase 3** only for problematic pages
- **Phase 4** essential for markdown validity

#### 6.5.2 When to Skip Merging
- **High agreement (>95%):** Just use majority OCR
- **Low agreement (<50%):** Consider re-OCR with better provider
- **Short texts (<100 words):** Merging overhead not worth it

---

### 6.6 Testing Strategy

#### 6.6.1 Unit Tests
```python
def test_majority_voting_all_agree():
    lines = ["The quick brown fox"] * 3
    assert merge_lines(lines) == ["The quick brown fox"]

def test_majority_voting_two_agree():
    lines = ["The quick brown fox", "The quick brown fox", "The quik brown fox"]
    assert merge_lines(lines) == ["The quick brown fox"]

def test_all_different_picks_median():
    lines = ["The quick brown fox", "The quik brwn fox", "Teh quick brown fox"]
    # Should pick "The quick brown fox" (closest to others)
    result = merge_lines(lines)
    assert result == ["The quick brown fox"]
```

#### 6.6.2 Integration Tests
- Load sample pages with 3 OCR outputs
- Run full merging pipeline
- Manually verify markdown validity
- Check structural preservation (headers, tables, lists)

#### 6.6.3 Evaluation Without Ground Truth
**Approach:** Human spot-checking
- Random sample 50 pages
- Review merged output vs. original 3 OCRs
- Count: improvements, degradations, no-change
- Target: >80% improved, <5% degraded

---

### 6.7 Recommended First Implementation

**Start here for maximum impact with minimum effort:**

```python
# strategy_a_simple_voter.py

from rapidfuzz import fuzz
from collections import Counter
from pathlib import Path

class SimpleOCRMerger:
    """Merge 3 OCR outputs using majority voting."""

    def __init__(self, ocr_outputs: list[str]):
        """
        Args:
            ocr_outputs: List of 3 markdown strings (Mistral, OlmOCR, PaddleOCR)
        """
        assert len(ocr_outputs) == 3, "Requires exactly 3 OCR outputs"
        self.ocr_outputs = ocr_outputs

    def merge(self) -> str:
        """Merge OCR outputs using line-level majority voting."""
        # Split into lines
        lines_by_ocr = [text.splitlines() for text in self.ocr_outputs]

        # Pad to same length (in case OCRs have different line counts)
        max_len = max(len(lines) for lines in lines_by_ocr)
        for lines in lines_by_ocr:
            while len(lines) < max_len:
                lines.append("")

        # Vote line by line
        merged_lines = []
        for line_tuple in zip(*lines_by_ocr):
            merged_line = self._vote_on_line(line_tuple)
            merged_lines.append(merged_line)

        return "\n".join(merged_lines)

    def _vote_on_line(self, lines: tuple[str, str, str]) -> str:
        """Vote on best line from 3 candidates."""
        # Remove empty lines from voting
        non_empty = [line for line in lines if line.strip()]

        if not non_empty:
            return ""

        if len(non_empty) == 1:
            return non_empty[0]

        # Check for exact matches
        counts = Counter(lines)
        most_common, count = counts.most_common(1)[0]

        if count >= 2:
            return most_common

        # All different - pick median by edit distance
        return self._find_median(lines)

    def _find_median(self, lines: tuple[str, str, str]) -> str:
        """Find line with minimum total edit distance to others."""
        scores = []
        for candidate in lines:
            total_distance = sum(
                fuzz.distance(candidate, other)
                for other in lines
            )
            scores.append((total_distance, candidate))

        return min(scores)[1]


# Usage example
if __name__ == "__main__":
    mistral_ocr = Path("ocr/mistral.md").read_text()
    olm_ocr = Path("ocr/olm.md").read_text()
    paddle_ocr = Path("ocr/paddle.md").read_text()

    merger = SimpleOCRMerger([mistral_ocr, olm_ocr, paddle_ocr])
    merged_text = merger.merge()

    Path("ocr/merged.md").write_text(merged_text)
    print(f"Merged {len(merged_text)} characters")
```

**Next Steps:**
1. Implement this baseline
2. Run on 10-20 sample pages
3. Manually evaluate quality
4. Measure agreement rates
5. Decide if Phase 2 (confidence weighting) needed
6. Iterate

---

## 7. References

### Academic Papers

1. **Lopresti, D., & Zhou, J. (1997).** "Using Consensus Sequence Voting to Correct OCR Errors." *Computer Vision and Image Understanding*, 67(1), 39-47.
   - URL: https://www.sciencedirect.com/science/article/abs/pii/S1077314296905020

2. **Fiscus, J. G. (1997).** "A Post-Processing System to Yield Reduced Word Error Rates: Recognizer Output Voting Error Reduction (ROVER)." *IEEE ASRU Workshop*.
   - URL: https://ieeexplore.ieee.org/document/659110/

3. **Jing, S., et al. (2024).** "Why Stop at Words? Unveiling the Bigger Picture through Line-Level OCR." *arXiv preprint*.
   - URL: https://arxiv.org/html/2508.21693v1

4. **Zhang, Y., et al. (2024).** "Confidence-Aware Document OCR Error Detection." *arXiv preprint*.
   - URL: https://arxiv.org/html/2409.04117v1

5. **Reul, C., et al. (2023).** "Unraveling Confidence: Examining Confidence Scores as Proxy for OCR Quality." *ICDAR 2023*.
   - URL: https://link.springer.com/chapter/10.1007/978-3-031-41734-4_7

6. **Myers, E. W. (1986).** "An O(ND) Difference Algorithm and its Variations." *Algorithmica*, 1(1-4), 251-266.

### Tools and Libraries

7. **Google diff-match-patch**
   - URL: https://github.com/google/diff-match-patch
   - Description: High-performance diff/match/patch library (powers Google Docs)

8. **RapidFuzz**
   - URL: https://github.com/rapidfuzz
   - Description: Fast string matching library for Python and C++

9. **Ocromore**
   - URL: https://github.com/UB-Mannheim/ocromore
   - Zenodo: https://zenodo.org/records/1493860
   - Description: Combining multiple OCR outputs (University of Mannheim)

10. **BioPython pairwise2**
    - URL: https://biopython.org/docs/1.75/api/Bio.pairwise2.html
    - Description: Sequence alignment tools (Needleman-Wunsch, Smith-Waterman)

11. **Microsoft Genalog**
    - URL: https://microsoft.github.io/genalog/text_alignment.html
    - Description: Text alignment for OCR using Needleman-Wunsch

### Comparative Studies

12. **Neliti (2024).** "A Comparative Analysis of Python Text Matching Libraries."
    - URL: https://media.neliti.com/media/publications/617608-a-comparative-analysis-of-python-text-ma-d5e66ac3.pdf

13. **Dev.to.** "Smart Text Matching: RapidFuzz vs Difflib."
    - URL: https://dev.to/mrquite/smart-text-matching-rapidfuzz-vs-difflib-ge5

### OCR Quality and Best Practices

14. **Towards Data Science.** "Evaluating OCR Output Quality with CER and WER."
    - URL: https://towardsdatascience.com/evaluating-ocr-output-quality-with-character-error-rate-cer-and-word-error-rate-wer-853175297510/

15. **Mistral AI.** "Mistral OCR."
    - URL: https://mistral.ai/news/mistral-ocr
    - Description: Modern VLM-based OCR with structure preservation

16. **Medium (Felix Pappe).** "PDF to Markdown Simplified: Implementation and Comparison of Mistral and Docling."
    - URL: https://felix-pappe.medium.com/pdf-to-markdown-simplified-implementation-and-comparison-of-mistral-and-docling-5c70b6f9a8f0

### Real-World Implementations

17. **Google Research.** "Improving Book OCR by Adaptive Language and Image Models."
    - URL: https://research.google/pubs/improving-book-ocr-by-adaptive-language-and-image-models/

18. **Internet Archive Blog.** "FOSS Wins Again: OCR for 19th Century Newspapers."
    - URL: https://blog.archive.org/2020/11/23/foss-wins-again-free-and-open-source-communities-comes-through-on-19th-century-newspapers-and-books-and-periodicals/

19. **GDELT Project.** "3.5 Million Books: Internet Archive and HathiTrust Processing."
    - URL: https://blog.gdeltproject.org/3-5-million-books-1800-2015-gdelt-processes-internet-archive-and-hathitrust-book-archives-and-available-in-google-bigquery/

### Stack Overflow and Practical Guides

20. **Stack Overflow.** "How to combine the results of multiple OCR tools to get better text recognition."
    - URL: https://stackoverflow.com/questions/55367637/how-to-combine-the-results-of-multiple-ocr-tools-to-get-better-text-recognition

21. **Stack Overflow.** "Software to Improve OCR Results Based on Output from Multiple OCR Software Packages."
    - URL: https://stackoverflow.com/questions/3271174/software-to-improve-ocr-results-based-on-output-from-multiple-ocr-software-packa

---

## Summary

**Key Takeaways for Shelf Strategy A:**

1. **ROVER-inspired voting** is the proven approach (20-50% error reduction with 3 OCR systems)

2. **Implementation path:**
   - Start with **simple majority voting** (Phase 1) - quick win
   - Add **confidence-weighted voting** (Phase 2) if scores available
   - Use **RapidFuzz** for fast text comparison
   - Consider **line-level** voting (better than word-level per 2024 research)

3. **No ground truth needed:**
   - Use agreement rates as quality proxy
   - Leverage confidence scores if available
   - Optional: language model perplexity for assessment

4. **Markdown considerations:**
   - Preserve structural elements (headers, tables, lists)
   - Consider element-specific voting strategies
   - Validate markdown output

5. **Libraries:**
   - **RapidFuzz** (primary, fastest)
   - **diff-match-patch** (visualization)
   - Study **Ocromore** implementation (open source)

6. **Testing:**
   - Unit test voting logic
   - Human spot-check 50+ pages
   - Track agreement rates
   - Target: >80% improvement, <5% degradation

**Next Action:** Implement `SimpleOCRMerger` baseline (provided in Section 6.7) and evaluate on sample pages.
