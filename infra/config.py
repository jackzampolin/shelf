"""
Configuration management for Scanshelf pipeline.

Simplified 12-variable configuration with Pydantic validation.
Validates all settings on import (fail fast).
"""

import os
from pathlib import Path
from typing import List
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

# Load .env file before config initialization
load_dotenv()


class ScanshelfConfig(BaseModel):
    """
    Global configuration for Scanshelf pipeline.

    Short, focused set of 12 variables:
    - 1 required (openrouter_api_key)
    - 11 optional with good defaults

    All values loaded from environment variables.
    Pydantic validates types and constraints on initialization.
    """

    # ===== REQUIRED =====

    openrouter_api_key: str = Field(
        ...,
        description="OpenRouter API key (REQUIRED)"
    )

    # ===== MODEL TIERS =====

    vision_model_primary: str = Field(
        default="x-ai/grok-4-fast",
        description="Primary vision model (fast, cheap)"
    )

    vision_model_expensive: str = Field(
        default="anthropic/claude-3.5-sonnet",
        description="Expensive vision model (high quality)"
    )

    text_model_primary: str = Field(
        default="openai/gpt-4o-mini",
        description="Primary text-only model (cheap)"
    )

    text_model_expensive: str = Field(
        default="openai/gpt-4o",
        description="Expensive text-only model (high quality)"
    )

    fallback_models: List[str] = Field(
        default_factory=list,
        description="Fallback model list (parsed from comma-separated string)"
    )

    # ===== CORE SETTINGS =====

    book_storage_root: Path = Field(
        default=Path.home() / "Documents" / "book_scans",
        description="Root directory for book storage"
    )

    max_workers: int = Field(
        default=30,
        ge=1,
        le=100,
        description="Parallel workers for I/O-bound stages"
    )

    rate_limit_requests_per_minute: int = Field(
        default=150,
        ge=1,
        le=1000,
        description="OpenRouter rate limit (requests/min)"
    )

    # ===== OPTIONAL =====

    pdf_extraction_dpi_ocr: int = Field(
        default=600,
        ge=300,
        le=1200,
        description="DPI for OCR extraction"
    )

    pdf_extraction_dpi_vision: int = Field(
        default=300,
        ge=150,
        le=600,
        description="DPI for vision model extraction"
    )

    # ===== INTERNAL (OpenRouter metadata, rarely changed) =====

    openrouter_site_url: str = Field(
        default="https://github.com/jackzampolin/scanshelf",
        description="Site URL for OpenRouter tracking"
    )

    openrouter_site_name: str = Field(
        default="Scanshelf",
        description="Site name for OpenRouter tracking"
    )

    # ===== VALIDATORS =====

    @field_validator('openrouter_api_key')
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Ensure API key is not empty."""
        if not v or v.strip() == '':
            raise ValueError(
                "OPENROUTER_API_KEY is required. "
                "Get your key at: https://openrouter.ai/keys"
            )
        return v.strip()

    @field_validator('book_storage_root')
    @classmethod
    def validate_storage_root(cls, v: Path) -> Path:
        """Expand ~ and ensure absolute path."""
        return Path(v).expanduser().resolve()

    @field_validator('fallback_models', mode='before')
    @classmethod
    def parse_fallback_models(cls, v) -> List[str]:
        """Parse comma-separated string into list."""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [m.strip() for m in v.split(',') if m.strip()]
        return []

    model_config = {
        "frozen": True,  # Make config immutable
        "validate_assignment": True
    }


def _load_config() -> ScanshelfConfig:
    """
    Load configuration from environment variables.

    Pydantic validates all fields and constraints on initialization.
    This function is called once at module import time.

    Raises:
        ValidationError: If configuration is invalid (API key missing, out of range, etc.)
    """
    return ScanshelfConfig(
        # Required
        openrouter_api_key=(
            os.getenv('OPENROUTER_API_KEY') or
            os.getenv('OPEN_ROUTER_API_KEY') or
            ''
        ),

        # Model tiers
        vision_model_primary=os.getenv(
            'VISION_MODEL_PRIMARY',
            os.getenv('VISION_MODEL', 'x-ai/grok-4-fast')  # Backward compat
        ),
        vision_model_expensive=os.getenv(
            'VISION_MODEL_EXPENSIVE',
            'anthropic/claude-sonnet-4.5'
        ),
        text_model_primary=os.getenv(
            'TEXT_MODEL_PRIMARY',
            'openai/gpt-4o-mini'
        ),
        text_model_expensive=os.getenv(
            'TEXT_MODEL_EXPENSIVE',
            'openai/gpt-4o'
        ),
        fallback_models=os.getenv('FALLBACK_MODELS', ''),

        # Core settings
        book_storage_root=Path(os.getenv(
            'BOOK_STORAGE_ROOT',
            '~/Documents/book_scans'
        )),
        max_workers=int(os.getenv('MAX_WORKERS', '30')),
        rate_limit_requests_per_minute=int(os.getenv(
            'RATE_LIMIT_REQUESTS_PER_MINUTE',
            '150'
        )),

        # Optional
        pdf_extraction_dpi_ocr=int(os.getenv(
            'PDF_EXTRACTION_DPI_OCR',
            '600'
        )),
        pdf_extraction_dpi_vision=int(os.getenv(
            'PDF_EXTRACTION_DPI_VISION',
            '300'
        )),

        # Internal
        openrouter_site_url=os.getenv(
            'OPENROUTER_SITE_URL',
            'https://github.com/jackzampolin/scanshelf'
        ),
        openrouter_site_name=os.getenv(
            'OPENROUTER_SITE_NAME',
            'Scanshelf'
        ),
    )


# Singleton instance - validates on import (fail fast)
Config = _load_config()
