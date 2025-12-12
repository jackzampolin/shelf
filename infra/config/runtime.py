"""
Runtime configuration access.

Single source of truth: {storage_root}/config.yaml

The only environment variable used is BOOK_STORAGE_ROOT to locate the library.
All other configuration comes from config.yaml.
"""

import os
from pathlib import Path
from functools import lru_cache
from typing import Optional

from .schemas import LibraryConfig


def get_storage_root() -> Path:
    """Get the library storage root from environment."""
    return Path(os.getenv('BOOK_STORAGE_ROOT', '~/Documents/shelf')).expanduser().resolve()


@lru_cache(maxsize=1)
def get_library_config() -> LibraryConfig:
    """
    Load and cache the library configuration.

    Returns LibraryConfig with defaults if config.yaml doesn't exist.
    """
    from .library_config import load_library_config
    return load_library_config(get_storage_root())


def get_api_key(name: str) -> str:
    """
    Get an API key by name, resolving ${ENV_VAR} references.

    Args:
        name: Key name (e.g., "openrouter", "mistral", "deepinfra")

    Returns:
        Resolved API key value, or empty string if not found
    """
    config = get_library_config()
    return config.resolve_api_key(name) or ""


def get_default_model() -> str:
    """Get the default LLM model from library config."""
    config = get_library_config()
    default_provider = config.defaults.llm_provider
    provider = config.get_llm_provider(default_provider)
    if provider:
        return provider.model
    return ""


def reload_config() -> LibraryConfig:
    """Force reload of library config (clears cache)."""
    get_library_config.cache_clear()
    return get_library_config()


class _ConfigCompat:
    """
    Backward-compatible Config object.

    Provides attribute access to config values for code that hasn't
    been migrated to use the new functions directly.
    """

    @property
    def book_storage_root(self) -> Path:
        return get_storage_root()

    @property
    def openrouter_api_key(self) -> str:
        key = get_api_key("openrouter")
        if not key:
            raise ValueError(
                "openrouter API key not configured. "
                "Run: shelf config init"
            )
        return key

    @property
    def mistral_api_key(self) -> str:
        return get_api_key("mistral")

    @property
    def deepinfra_api_key(self) -> str:
        return get_api_key("deepinfra")

    @property
    def datalab_api_key(self) -> str:
        return get_api_key("datalab")

    @property
    def deepseek_api_key(self) -> str:
        return get_api_key("deepseek")

    @property
    def vision_model_primary(self) -> str:
        return get_default_model()

    @property
    def library_config(self) -> LibraryConfig:
        return get_library_config()


# Singleton for backward compatibility
Config = _ConfigCompat()

# Also export ShelfConfig as alias for type hints
ShelfConfig = _ConfigCompat
