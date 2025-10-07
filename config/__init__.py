"""
Centralized configuration management for Scanshelf pipeline.

Loads configuration from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()


class Config:
    """Pipeline configuration from environment variables."""

    # =========================================================================
    # API Keys
    # =========================================================================
    OPEN_ROUTER_API_KEY = os.getenv('OPEN_ROUTER_API_KEY') or os.getenv('OPENROUTER_API_KEY')

    # OpenRouter site info (optional)
    OPEN_ROUTER_SITE_URL = os.getenv('OPEN_ROUTER_SITE_URL', 'https://github.com/jackzampolin/scanshelf')
    OPEN_ROUTER_SITE_NAME = os.getenv('OPEN_ROUTER_SITE_NAME', 'Scanshelf')

    # =========================================================================
    # Storage Paths
    # =========================================================================
    BOOK_STORAGE_ROOT = Path(os.getenv('BOOK_STORAGE_ROOT', '~/Documents/book_scans')).expanduser()

    # =========================================================================
    # Model Configuration
    # =========================================================================

    # OCR Stage
    OCR_WORKERS = int(os.getenv('OCR_WORKERS', '8'))

    # Correction Stage (3-agent pipeline)
    CORRECT_MODEL = os.getenv('CORRECT_MODEL', 'openai/gpt-4o-mini')
    CORRECT_WORKERS = int(os.getenv('CORRECT_WORKERS', '30'))
    CORRECT_RATE_LIMIT = int(os.getenv('CORRECT_RATE_LIMIT', '150'))

    # Fix Stage (Agent 4)
    FIX_MODEL = os.getenv('FIX_MODEL', 'anthropic/claude-sonnet-4.5')

    # Structure Stage - Extract Phase
    EXTRACT_MODEL = os.getenv('EXTRACT_MODEL', 'openai/gpt-4o-mini')

    # Structure Stage - Assemble Phase (Chunking)
    CHUNK_MODEL = os.getenv('CHUNK_MODEL', 'openai/gpt-4o-mini')

    # Backward compatibility - STRUCTURE_MODEL defaults to EXTRACT_MODEL
    STRUCTURE_MODEL = os.getenv('STRUCTURE_MODEL', EXTRACT_MODEL)

    # Quality Review Stage
    QUALITY_MODEL = os.getenv('QUALITY_MODEL', 'anthropic/claude-sonnet-4.5')

    # =========================================================================
    # Debug & Logging
    # =========================================================================
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    SAVE_DEBUG_FILES = os.getenv('SAVE_DEBUG_FILES', 'true').lower() == 'true'

    # =========================================================================
    # Processing Options
    # =========================================================================
    SKIP_COMPLETED_STAGES = os.getenv('SKIP_COMPLETED_STAGES', 'true').lower() == 'true'
    AUTO_FIX = os.getenv('AUTO_FIX', 'true').lower() == 'true'
    MIN_CONFIDENCE_THRESHOLD = float(os.getenv('MIN_CONFIDENCE_THRESHOLD', '0.8'))

    # =========================================================================
    # Cost Tracking
    # =========================================================================
    TRACK_COSTS = os.getenv('TRACK_COSTS', 'true').lower() == 'true'
    COST_WARNING_THRESHOLD = float(os.getenv('COST_WARNING_THRESHOLD', '10.0'))

    @classmethod
    def get_model_for_stage(cls, stage: str) -> str:
        """Get configured model for a pipeline stage."""
        stage_models = {
            'correct': cls.CORRECT_MODEL,
            'fix': cls.FIX_MODEL,
            'structure': cls.STRUCTURE_MODEL,
            'extract': cls.EXTRACT_MODEL,
            'assemble': cls.CHUNK_MODEL,
            'quality': cls.QUALITY_MODEL
        }
        return stage_models.get(stage, cls.CORRECT_MODEL)

    @classmethod
    def get_processing_metadata(cls) -> dict:
        """
        Get metadata about current configuration for tracking in book metadata.

        Returns dict with model choices, settings used for this pipeline run.
        """
        return {
            'models': {
                'ocr': 'tesseract',  # OCR is always Tesseract
                'correct': cls.CORRECT_MODEL,
                'fix': cls.FIX_MODEL,
                'extract': cls.EXTRACT_MODEL,
                'chunk': cls.CHUNK_MODEL,
                'quality': cls.QUALITY_MODEL
            },
            'settings': {
                'ocr_workers': cls.OCR_WORKERS,
                'correct_workers': cls.CORRECT_WORKERS,
                'correct_rate_limit': cls.CORRECT_RATE_LIMIT,
                'min_confidence_threshold': cls.MIN_CONFIDENCE_THRESHOLD
            }
        }

    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        """
        Validate configuration.

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        # Check for API key
        if not cls.OPEN_ROUTER_API_KEY:
            errors.append("OPEN_ROUTER_API_KEY not set in environment")

        # Check storage root exists
        if not cls.BOOK_STORAGE_ROOT.exists():
            errors.append(f"Book storage root does not exist: {cls.BOOK_STORAGE_ROOT}")

        # Validate numeric ranges
        if cls.OCR_WORKERS < 1:
            errors.append(f"OCR_WORKERS must be >= 1, got {cls.OCR_WORKERS}")

        if cls.CORRECT_WORKERS < 1:
            errors.append(f"CORRECT_WORKERS must be >= 1, got {cls.CORRECT_WORKERS}")

        if cls.CORRECT_RATE_LIMIT < 1:
            errors.append(f"CORRECT_RATE_LIMIT must be >= 1, got {cls.CORRECT_RATE_LIMIT}")

        if not (0.0 <= cls.MIN_CONFIDENCE_THRESHOLD <= 1.0):
            errors.append(f"MIN_CONFIDENCE_THRESHOLD must be 0.0-1.0, got {cls.MIN_CONFIDENCE_THRESHOLD}")

        return len(errors) == 0, errors

    @classmethod
    def print_config(cls):
        """Print current configuration (for debugging)."""
        print("=" * 70)
        print("Scanshelf Configuration")
        print("=" * 70)
        print(f"Book Storage: {cls.BOOK_STORAGE_ROOT}")
        print(f"\nModels:")
        print(f"  Correction:  {cls.CORRECT_MODEL}")
        print(f"  Fix:         {cls.FIX_MODEL}")
        print(f"  Extract:     {cls.EXTRACT_MODEL}")
        print(f"  Chunk:       {cls.CHUNK_MODEL}")
        print(f"  Quality:     {cls.QUALITY_MODEL}")
        print(f"\nConcurrency:")
        print(f"  OCR Workers: {cls.OCR_WORKERS}")
        print(f"  Correction Workers: {cls.CORRECT_WORKERS}")
        print(f"  Correction Rate Limit: {cls.CORRECT_RATE_LIMIT}/min")
        print(f"\nOptions:")
        print(f"  Skip Completed: {cls.SKIP_COMPLETED_STAGES}")
        print(f"  Auto Fix: {cls.AUTO_FIX}")
        print(f"  Min Confidence: {cls.MIN_CONFIDENCE_THRESHOLD}")
        print(f"  Cost Tracking: {cls.TRACK_COSTS}")
        print("=" * 70)
