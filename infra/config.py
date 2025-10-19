"""
Configuration management for Scanshelf pipeline.

Loads configuration from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()


class Config:
    """Pipeline configuration from environment variables."""

    # API Keys
    OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY') or os.getenv('OPEN_ROUTER_API_KEY')

    # OpenRouter site info (optional)
    OPENROUTER_SITE_URL = os.getenv('OPENROUTER_SITE_URL', 'https://github.com/jackzampolin/scanshelf')
    OPENROUTER_SITE_NAME = os.getenv('OPENROUTER_SITE_NAME', 'Scanshelf')

    # Storage
    BOOK_STORAGE_ROOT = Path(os.getenv('BOOK_STORAGE_ROOT', '~/Documents/book_scans')).expanduser()

    # PDF Extraction DPI
    # High-quality extraction for OCR (Tesseract benefits from high resolution)
    PDF_EXTRACTION_DPI_OCR = int(os.getenv('PDF_EXTRACTION_DPI_OCR', '600'))
    # Downsampled for vision models (balance quality vs token cost)
    PDF_EXTRACTION_DPI_VISION = int(os.getenv('PDF_EXTRACTION_DPI_VISION', '300'))

    # Vision Model
    # Default vision model for correction and labeling stages
    # Note: Must support vision (image) input via OpenRouter
    VISION_MODEL = os.getenv('VISION_MODEL', 'x-ai/grok-4-fast')

    # Model Fallback Chain
    # Comma-separated list of fallback models to try if primary fails
    # Example: FALLBACK_MODELS="anthropic/claude-3.5-sonnet,openai/gpt-4o"
    # Empty by default (no fallback)
    _fallback_models_str = os.getenv('FALLBACK_MODELS', '')
    FALLBACK_MODELS = [m.strip() for m in _fallback_models_str.split(',') if m.strip()]

    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        """
        Validate required configuration.

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        if not cls.OPENROUTER_API_KEY:
            errors.append("OPENROUTER_API_KEY not set in environment")

        if not cls.BOOK_STORAGE_ROOT.exists():
            errors.append(f"Book storage root does not exist: {cls.BOOK_STORAGE_ROOT}")

        return len(errors) == 0, errors
