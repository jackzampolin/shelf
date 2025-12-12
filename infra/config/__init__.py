"""
Configuration management for Shelf.

Hierarchical config system:
- Library config: {storage_root}/config.yaml
- Book config: {storage_root}/books/{scan_id}/config.yaml

Usage:
    from infra.config import LibraryConfigManager, BookConfigManager

    # Library config
    lib_manager = LibraryConfigManager(storage_root)
    lib_config = lib_manager.load()

    # Book config (inherits from library)
    book_manager = BookConfigManager(storage_root, "my-book")
    resolved = book_manager.resolve()  # Merged config

Legacy usage (backward compatible):
    from infra.config import Config
    api_key = Config.openrouter_api_key
"""

from .schemas import (
    OCRProviderConfig,
    LLMProviderConfig,
    ProviderConfig,  # Backward compat alias for OCRProviderConfig
    DefaultsConfig,
    LibraryConfig,
    BookConfig,
    ResolvedBookConfig,
    resolve_env_vars,
)

from .library_config import (
    LibraryConfigManager,
    load_library_config,
)

from .book_config import (
    BookConfigManager,
    load_book_config,
    resolve_book_config,
)

# Legacy config - backward compatibility with .env-based config
from .legacy import Config, ShelfConfig


__all__ = [
    # Legacy (backward compatible)
    "Config",
    "ShelfConfig",
    # Schemas
    "OCRProviderConfig",
    "LLMProviderConfig",
    "ProviderConfig",  # Backward compat alias
    "DefaultsConfig",
    "LibraryConfig",
    "BookConfig",
    "ResolvedBookConfig",
    "resolve_env_vars",
    # Library config
    "LibraryConfigManager",
    "load_library_config",
    # Book config
    "BookConfigManager",
    "load_book_config",
    "resolve_book_config",
]
