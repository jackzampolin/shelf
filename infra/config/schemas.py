"""
Configuration schemas for Shelf.

Defines the structure of library and book configuration files.
All config is stored in ~/Documents/shelf/ (or BOOK_STORAGE_ROOT).
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator
import os
import re


class ProviderConfig(BaseModel):
    """Configuration for an OCR provider."""
    type: str = Field(..., description="Provider type: mistral-ocr, deepinfra, openrouter")
    model: Optional[str] = Field(None, description="Model identifier (for deepinfra/openrouter)")
    rate_limit: Optional[float] = Field(None, description="Requests per second limit")
    enabled: bool = Field(True, description="Whether this provider is enabled")
    extra: Dict[str, Any] = Field(default_factory=dict, description="Provider-specific settings")


class DefaultsConfig(BaseModel):
    """Default settings for new books."""
    ocr_providers: List[str] = Field(
        default=["mistral", "paddle"],
        description="OCR providers to use by default"
    )
    blend_model: str = Field(
        default="google/gemini-2.0-flash-001",
        description="Model for blending OCR outputs"
    )
    max_workers: int = Field(
        default=10,
        description="Default parallel workers"
    )


class LibraryConfig(BaseModel):
    """
    Library-level configuration.

    Stored at: {storage_root}/config.yaml
    """
    api_keys: Dict[str, str] = Field(
        default_factory=dict,
        description="API keys (can use ${ENV_VAR} syntax)"
    )
    providers: Dict[str, ProviderConfig] = Field(
        default_factory=dict,
        description="OCR provider definitions"
    )
    defaults: DefaultsConfig = Field(
        default_factory=DefaultsConfig,
        description="Default settings for new books"
    )

    def resolve_api_key(self, key_name: str) -> Optional[str]:
        """
        Resolve an API key, expanding ${ENV_VAR} references.

        Returns None if key not found or env var not set.
        """
        if key_name not in self.api_keys:
            return None

        value = self.api_keys[key_name]
        return resolve_env_vars(value)

    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        """Get a provider config by name."""
        return self.providers.get(name)

    @classmethod
    def with_defaults(cls) -> "LibraryConfig":
        """Create a config with sensible defaults."""
        return cls(
            api_keys={
                "openrouter": "${OPENROUTER_API_KEY}",
                "mistral": "${MISTRAL_API_KEY}",
                "deepinfra": "${DEEPINFRA_API_KEY}",
            },
            providers={
                "mistral": ProviderConfig(
                    type="mistral-ocr",
                    rate_limit=6.0,
                ),
                "paddle": ProviderConfig(
                    type="deepinfra",
                    model="ds-paddleocr-vl",
                ),
                "olmocr": ProviderConfig(
                    type="deepinfra",
                    model="allenai/olmOCR-7B-0225-preview",
                    enabled=False,  # Not in default pipeline
                ),
            },
            defaults=DefaultsConfig(),
        )


class BookConfig(BaseModel):
    """
    Per-book configuration overrides.

    Stored at: {storage_root}/books/{scan_id}/config.yaml
    Inherits from library config, can override specific values.
    """
    ocr_providers: Optional[List[str]] = Field(
        None,
        description="Override OCR providers for this book"
    )
    blend_model: Optional[str] = Field(
        None,
        description="Override blend model for this book"
    )
    max_workers: Optional[int] = Field(
        None,
        description="Override max workers for this book"
    )
    extra: Dict[str, Any] = Field(
        default_factory=dict,
        description="Book-specific settings"
    )


class ResolvedBookConfig(BaseModel):
    """
    Fully resolved configuration for a book.

    Combines library defaults with book-specific overrides.
    All values are concrete (no Optional).
    """
    ocr_providers: List[str]
    blend_model: str
    max_workers: int
    extra: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_configs(
        cls,
        library_config: LibraryConfig,
        book_config: Optional[BookConfig] = None
    ) -> "ResolvedBookConfig":
        """
        Create resolved config by merging library defaults with book overrides.
        """
        defaults = library_config.defaults
        book = book_config or BookConfig()

        return cls(
            ocr_providers=book.ocr_providers or defaults.ocr_providers,
            blend_model=book.blend_model or defaults.blend_model,
            max_workers=book.max_workers or defaults.max_workers,
            extra=book.extra,
        )


def resolve_env_vars(value: str) -> str:
    """
    Resolve ${ENV_VAR} references in a string.

    Examples:
        "${OPENROUTER_API_KEY}" -> actual value from environment
        "literal-value" -> "literal-value"
        "${MISSING_VAR}" -> "" (empty string if not set)
    """
    if not isinstance(value, str):
        return value

    # Pattern matches ${VAR_NAME}
    pattern = r'\$\{([^}]+)\}'

    def replace(match):
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return re.sub(pattern, replace, value)
