"""
Identifier generation for scan folders.

Supports slugified titles (default) or Docker-style {adjective}-{scientist} format.
"""

import re
import random

ADJECTIVES = [
    "admiring", "adoring", "affectionate", "agitated", "amazing",
    "angry", "awesome", "blissful", "bold", "brave",
    "charming", "clever", "cool", "compassionate", "competent",
    "confident", "dazzling", "determined", "eager", "ecstatic",
    "elastic", "elated", "elegant", "eloquent", "epic",
    "fervent", "festive", "flamboyant", "focused", "friendly",
    "frosty", "gallant", "gifted", "goofy", "gracious",
    "happy", "hardcore", "heuristic", "hopeful", "hungry",
    "infallible", "inspiring", "jolly", "jovial", "keen",
    "kind", "laughing", "loving", "lucid", "magical",
    "mystifying", "modest", "musing", "naughty", "nervous",
    "nifty", "nostalgic", "objective", "optimistic", "peaceful",
    "pedantic", "pensive", "practical", "priceless", "quirky",
    "quizzical", "recursing", "relaxed", "reverent", "romantic",
    "serene", "sharp", "silly", "sleepy", "stoic",
    "strange", "stupefied", "suspicious", "sweet", "tender",
    "thirsty", "trusting", "unruffled", "upbeat", "vibrant",
    "vigilant", "vigorous", "wizardly", "wonderful", "xenodochial",
    "youthful", "zealous", "zen"
]

SCIENTISTS = [
    "archimedes", "aristotle", "babbage", "banach", "bardeen",
    "bernoulli", "bohr", "born", "boyle", "brahmagupta",
    "cantor", "carson", "chandrasekhar", "curie", "darwin",
    "davinci", "descartes", "dirac", "edison", "einstein",
    "euclid", "euler", "faraday", "fermat", "fibonacci",
    "franklin", "galileo", "gauss", "goodall", "herschel",
    "heisenberg", "hopper", "huygens", "hypatia", "johnson",
    "kepler", "lamarr", "lavoisier", "leibniz", "lovelace",
    "maxwell", "mendel", "mendeleev", "newton", "nobel",
    "noether", "pasteur", "pauling", "planck", "ptolemy",
    "pythagias", "ramanujan", "ride", "riemann", "rutherford",
    "sagan", "shannon", "tesla", "tharp", "turing",
    "volta", "wiles", "wright", "yalow"
]


def generate_scan_id() -> str:
    """
    Generate a random Docker-style scan identifier.

    Returns:
        String in format "{adjective}-{scientist}"
    """
    adj = random.choice(ADJECTIVES)
    sci = random.choice(SCIENTISTS)
    return f"{adj}-{sci}"


def ensure_unique_scan_id(existing_ids: list[str]) -> str:
    """
    Generate scan ID, re-rolling if collision occurs.

    Args:
        existing_ids: List of already-used scan IDs

    Returns:
        Unique scan ID not in existing_ids
    """
    max_attempts = 100
    for _ in range(max_attempts):
        scan_id = generate_scan_id()
        if scan_id not in existing_ids:
            return scan_id

    # Fallback with number suffix if we exhaust attempts
    return f"{generate_scan_id()}-{random.randint(1000, 9999)}"


def slugify_title(title: str) -> str:
    """
    Convert book title to URL-safe slug.

    Examples:
        "The Accidental President" → "accidental-president"
        "FDR & the New Deal" → "fdr-new-deal"
        "MacArthur: 1941-1951" → "macarthur-1941-1951"

    Args:
        title: Book title

    Returns:
        Lowercase slug with hyphens
    """
    # Convert to lowercase
    slug = title.lower()

    # Remove leading articles
    slug = re.sub(r'^(the|a|an)\s+', '', slug)

    # Keep only alphanumeric, spaces, and hyphens
    slug = re.sub(r'[^\w\s-]', '', slug)

    # Convert spaces to hyphens
    slug = re.sub(r'\s+', '-', slug)

    # Remove multiple consecutive hyphens
    slug = re.sub(r'-+', '-', slug)

    # Remove leading/trailing hyphens
    slug = slug.strip('-')

    # Limit length
    return slug[:50]


def ensure_unique_slug(base_slug: str, existing_ids: list[str]) -> str:
    """
    Ensure slug is unique, raising error if collision occurs.

    Args:
        base_slug: Slugified title
        existing_ids: List of already-used scan IDs

    Returns:
        The slug if unique

    Raises:
        ValueError: If slug already exists
    """
    if base_slug in existing_ids:
        raise ValueError(
            f"Scan ID '{base_slug}' already exists in library.\n"
            f"Use --id to specify a different name:\n"
            f"  ar add <pdfs> --id {base_slug}-2"
        )
    return base_slug
