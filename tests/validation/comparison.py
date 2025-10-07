"""
Text comparison utilities for OCR validation.

Calculates accuracy metrics (CER, WER) to compare pipeline outputs
against Internet Archive ground truth data.
"""

import difflib
from typing import Optional
from jiwer import cer, wer, process_words, process_characters


def calculate_accuracy(hypothesis: str, reference: str) -> dict:
    """
    Compare OCR output against ground truth text.

    Uses standard OCR evaluation metrics:
    - CER (Character Error Rate): Levenshtein distance at character level
    - WER (Word Error Rate): Levenshtein distance at word level
    - Accuracy: 1 - error_rate (higher is better)

    Args:
        hypothesis: Our OCR/corrected text output
        reference: Ground truth text (from Internet Archive)

    Returns:
        Dictionary with:
        - cer: Character Error Rate (0-1, lower is better)
        - wer: Word Error Rate (0-1, lower is better)
        - character_accuracy: 1 - CER (0-1, higher is better)
        - word_accuracy: 1 - WER (0-1, higher is better)
        - char_count: Number of characters in reference
        - word_count: Number of words in reference
        - sample_diff: First few character differences

    Example:
        >>> result = calculate_accuracy("Hello wrld", "Hello world")
        >>> print(f"CER: {result['cer']:.2%}")
        CER: 9.09%
    """
    # Handle empty strings
    if not reference:
        return {
            'cer': 1.0 if hypothesis else 0.0,
            'wer': 1.0 if hypothesis else 0.0,
            'character_accuracy': 0.0 if hypothesis else 1.0,
            'word_accuracy': 0.0 if hypothesis else 1.0,
            'char_count': 0,
            'word_count': 0,
            'sample_diff': '',
        }

    # Calculate CER (Character Error Rate)
    char_error_rate = cer(reference, hypothesis)

    # Calculate WER (Word Error Rate)
    word_error_rate = wer(reference, hypothesis)

    # Get detailed character differences for debugging
    sample_diff = get_sample_differences(hypothesis, reference, max_samples=5)

    return {
        'cer': char_error_rate,
        'wer': word_error_rate,
        'character_accuracy': 1.0 - char_error_rate,
        'word_accuracy': 1.0 - word_error_rate,
        'char_count': len(reference),
        'word_count': len(reference.split()),
        'sample_diff': sample_diff,
    }


def get_sample_differences(hypothesis: str,
                          reference: str,
                          max_samples: int = 5,
                          context_chars: int = 20) -> str:
    """
    Get a sample of differences between two texts for debugging.

    Args:
        hypothesis: Our OCR output
        reference: Ground truth text
        max_samples: Maximum number of difference samples to show
        context_chars: Characters of context around each difference

    Returns:
        Formatted string showing sample differences
    """
    # Use SequenceMatcher to find differences
    matcher = difflib.SequenceMatcher(None, reference, hypothesis)

    differences = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Get context around the difference
            context_start = max(0, i1 - context_chars)
            context_end = min(len(reference), i2 + context_chars)

            ref_context = reference[context_start:context_end]
            ref_diff = reference[i1:i2]

            hyp_context_start = max(0, j1 - context_chars)
            hyp_context_end = min(len(hypothesis), j2 + context_chars)
            hyp_diff = hypothesis[j1:j2]

            differences.append({
                'type': tag,
                'reference': ref_diff,
                'hypothesis': hyp_diff,
                'context': ref_context,
                'position': i1,
            })

            if len(differences) >= max_samples:
                break

    if not differences:
        return "No differences found"

    # Format differences
    lines = []
    for i, diff in enumerate(differences, 1):
        lines.append(f"\nDifference #{i} ({diff['type']}) at position {diff['position']}:")
        lines.append(f"  Reference: '{diff['reference']}'")
        lines.append(f"  Hypothesis: '{diff['hypothesis']}'")
        lines.append(f"  Context: ...{diff['context']}...")

    return '\n'.join(lines)


def calculate_detailed_metrics(hypothesis: str, reference: str) -> dict:
    """
    Calculate detailed OCR metrics using jiwer's process functions.

    Provides additional metrics beyond simple CER/WER:
    - Substitutions, deletions, insertions
    - Match rate
    - More granular error analysis

    Args:
        hypothesis: Our OCR output
        reference: Ground truth text

    Returns:
        Dictionary with detailed metrics
    """
    if not reference:
        return {}

    # Get character-level measures
    char_output = process_characters(reference, hypothesis)

    # Get word-level measures
    word_output = process_words(reference, hypothesis)

    return {
        # Character-level
        'char_substitutions': char_output.substitutions,
        'char_deletions': char_output.deletions,
        'char_insertions': char_output.insertions,
        'char_hits': char_output.hits,
        'cer': char_output.wer,  # wer on chars = cer

        # Word-level
        'word_substitutions': word_output.substitutions,
        'word_deletions': word_output.deletions,
        'word_insertions': word_output.insertions,
        'word_hits': word_output.hits,
        'wer': word_output.wer,
    }


def format_accuracy_report(accuracy: dict, title: str = "OCR Accuracy Report") -> str:
    """
    Format accuracy dictionary as a readable report.

    Args:
        accuracy: Output from calculate_accuracy()
        title: Report title

    Returns:
        Formatted string report
    """
    report = [
        f"\n{'=' * 60}",
        f"{title:^60}",
        f"{'=' * 60}\n",
        f"Character Error Rate (CER): {accuracy['cer']:.2%}",
        f"Character Accuracy:         {accuracy['character_accuracy']:.2%}",
        f"",
        f"Word Error Rate (WER):      {accuracy['wer']:.2%}",
        f"Word Accuracy:              {accuracy['word_accuracy']:.2%}",
        f"",
        f"Reference Text:",
        f"  - Characters: {accuracy['char_count']:,}",
        f"  - Words:      {accuracy['word_count']:,}",
    ]

    if accuracy.get('sample_diff'):
        report.append(f"\n{accuracy['sample_diff']}")

    report.append(f"\n{'=' * 60}\n")

    return '\n'.join(report)


def compare_page_texts(our_text: str,
                      ia_text: str,
                      page_num: int,
                      stage: str = "OCR") -> dict:
    """
    Convenience function to compare a single page's text.

    Args:
        our_text: Text from our pipeline
        ia_text: Ground truth from Internet Archive
        page_num: Page number for reporting
        stage: Pipeline stage name (e.g., "OCR", "Correct", "Fix")

    Returns:
        Dictionary with accuracy metrics plus metadata
    """
    accuracy = calculate_accuracy(our_text, ia_text)

    return {
        'page_num': page_num,
        'stage': stage,
        **accuracy,
    }


def aggregate_accuracy(page_results: list[dict]) -> dict:
    """
    Aggregate accuracy metrics across multiple pages.

    Args:
        page_results: List of results from compare_page_texts()

    Returns:
        Dictionary with aggregated metrics:
        - avg_cer: Average CER across all pages
        - avg_wer: Average WER across all pages
        - min_accuracy: Worst performing page
        - max_accuracy: Best performing page
        - total_chars: Total characters processed
    """
    if not page_results:
        return {}

    total_chars = sum(r['char_count'] for r in page_results)
    total_words = sum(r['word_count'] for r in page_results)

    # Weight by character count for more accurate average
    weighted_cer = sum(
        r['cer'] * r['char_count'] for r in page_results
    ) / total_chars if total_chars > 0 else 0

    weighted_wer = sum(
        r['wer'] * r['word_count'] for r in page_results
    ) / total_words if total_words > 0 else 0

    # Find best and worst pages
    sorted_by_cer = sorted(page_results, key=lambda x: x['cer'])

    return {
        'avg_cer': weighted_cer,
        'avg_wer': weighted_wer,
        'avg_character_accuracy': 1.0 - weighted_cer,
        'avg_word_accuracy': 1.0 - weighted_wer,
        'total_chars': total_chars,
        'total_words': total_words,
        'pages_tested': len(page_results),
        'best_page': sorted_by_cer[0]['page_num'],
        'best_cer': sorted_by_cer[0]['cer'],
        'worst_page': sorted_by_cer[-1]['page_num'],
        'worst_cer': sorted_by_cer[-1]['cer'],
    }


def format_aggregate_report(aggregate: dict, title: str = "Aggregate Accuracy") -> str:
    """
    Format aggregated accuracy results as a report.

    Args:
        aggregate: Output from aggregate_accuracy()
        title: Report title

    Returns:
        Formatted string report
    """
    report = [
        f"\n{'=' * 60}",
        f"{title:^60}",
        f"{'=' * 60}\n",
        f"Pages Tested:              {aggregate['pages_tested']}",
        f"Total Characters:          {aggregate['total_chars']:,}",
        f"Total Words:               {aggregate['total_words']:,}",
        f"",
        f"Average CER:               {aggregate['avg_cer']:.2%}",
        f"Average Character Accuracy: {aggregate['avg_character_accuracy']:.2%}",
        f"",
        f"Average WER:               {aggregate['avg_wer']:.2%}",
        f"Average Word Accuracy:     {aggregate['avg_word_accuracy']:.2%}",
        f"",
        f"Best Page:  #{aggregate['best_page']} (CER: {aggregate['best_cer']:.2%})",
        f"Worst Page: #{aggregate['worst_page']} (CER: {aggregate['worst_cer']:.2%})",
        f"\n{'=' * 60}\n",
    ]

    return '\n'.join(report)
