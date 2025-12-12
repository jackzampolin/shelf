"""
Per-book configuration loading and management.

Book config is stored at {storage_root}/books/{scan_id}/config.yaml
and inherits from the library config, allowing per-book overrides.
"""

from pathlib import Path
from typing import Optional
import yaml

from .schemas import BookConfig, LibraryConfig, ResolvedBookConfig
from .library_config import load_library_config


CONFIG_FILENAME = "config.yaml"


class BookConfigManager:
    """
    Manages per-book configuration.

    Book config inherits from library config and can override specific values.

    Usage:
        manager = BookConfigManager(storage_root, "my-book")
        config = manager.load()           # Returns BookConfig (overrides only)
        resolved = manager.resolve()      # Returns ResolvedBookConfig (merged)
        manager.save(config)              # Persists to disk
    """

    def __init__(self, storage_root: Path, scan_id: str):
        """
        Initialize the book config manager.

        Args:
            storage_root: Root directory for the library
            scan_id: Book identifier
        """
        self.storage_root = Path(storage_root).expanduser().resolve()
        self.scan_id = scan_id
        self.book_dir = self.storage_root / "books" / scan_id
        self.config_path = self.book_dir / CONFIG_FILENAME

    def exists(self) -> bool:
        """Check if book config file exists."""
        return self.config_path.exists()

    def load(self) -> BookConfig:
        """
        Load book config from disk.

        Returns empty BookConfig if file doesn't exist.
        """
        if not self.config_path.exists():
            return BookConfig()

        with open(self.config_path, "r") as f:
            data = yaml.safe_load(f) or {}

        return BookConfig.model_validate(data)

    def save(self, config: BookConfig) -> None:
        """
        Save book config to disk.

        Only saves non-None values (overrides).
        """
        self.book_dir.mkdir(parents=True, exist_ok=True)

        # Only save fields that are set (not None)
        data = config.model_dump(exclude_none=True, exclude_defaults=True)

        # Don't write empty config files
        if not data:
            if self.config_path.exists():
                self.config_path.unlink()
            return

        with open(self.config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def resolve(self, library_config: Optional[LibraryConfig] = None) -> ResolvedBookConfig:
        """
        Get fully resolved config for this book.

        Merges library defaults with book-specific overrides.

        Args:
            library_config: Optional LibraryConfig (loaded from disk if not provided)

        Returns:
            ResolvedBookConfig with all values resolved
        """
        if library_config is None:
            library_config = load_library_config(self.storage_root)

        book_config = self.load()
        return ResolvedBookConfig.from_configs(library_config, book_config)

    def set(self, **kwargs) -> BookConfig:
        """
        Set specific fields in the book config.

        Args:
            **kwargs: Fields to set (ocr_providers, blend_model, max_workers, etc.)

        Returns:
            Updated BookConfig
        """
        config = self.load()
        data = config.model_dump()
        data.update(kwargs)
        new_config = BookConfig.model_validate(data)
        self.save(new_config)
        return new_config

    def clear(self) -> None:
        """Remove book config (revert to library defaults)."""
        if self.config_path.exists():
            self.config_path.unlink()


def load_book_config(storage_root: Path, scan_id: str) -> BookConfig:
    """
    Convenience function to load book config.

    Args:
        storage_root: Root directory for the library
        scan_id: Book identifier

    Returns:
        BookConfig instance (may be empty if no overrides)
    """
    manager = BookConfigManager(storage_root, scan_id)
    return manager.load()


def resolve_book_config(
    storage_root: Path,
    scan_id: str,
    library_config: Optional[LibraryConfig] = None
) -> ResolvedBookConfig:
    """
    Convenience function to get resolved book config.

    Args:
        storage_root: Root directory for the library
        scan_id: Book identifier
        library_config: Optional LibraryConfig (loaded if not provided)

    Returns:
        ResolvedBookConfig with library defaults and book overrides merged
    """
    manager = BookConfigManager(storage_root, scan_id)
    return manager.resolve(library_config)
