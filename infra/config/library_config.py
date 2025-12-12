"""
Library configuration loading and management.

The library config is stored at {storage_root}/config.yaml and contains:
- API keys (with env var expansion)
- Provider definitions
- Default settings for new books
"""

from pathlib import Path
from typing import Optional
import yaml

from .schemas import LibraryConfig


CONFIG_FILENAME = "config.yaml"


class LibraryConfigManager:
    """
    Manages the library-level configuration.

    Usage:
        manager = LibraryConfigManager(storage_root)
        config = manager.load()  # Returns LibraryConfig
        manager.save(config)     # Persists to disk
    """

    def __init__(self, storage_root: Path):
        """
        Initialize the config manager.

        Args:
            storage_root: Root directory for the library (e.g., ~/Documents/shelf)
        """
        self.storage_root = Path(storage_root).expanduser().resolve()
        self.config_path = self.storage_root / CONFIG_FILENAME

    def exists(self) -> bool:
        """Check if config file exists."""
        return self.config_path.exists()

    def load(self) -> LibraryConfig:
        """
        Load library config from disk.

        Returns LibraryConfig with defaults if file doesn't exist.
        """
        if not self.config_path.exists():
            return LibraryConfig.with_defaults()

        with open(self.config_path, "r") as f:
            data = yaml.safe_load(f) or {}

        return LibraryConfig.model_validate(data)

    def save(self, config: LibraryConfig) -> None:
        """
        Save library config to disk.

        Creates storage_root directory if needed.
        """
        self.storage_root.mkdir(parents=True, exist_ok=True)

        # Convert to dict, excluding None values
        data = config.model_dump(exclude_none=True)

        # Convert ProviderConfig objects to dicts
        if "providers" in data:
            for name, provider in data["providers"].items():
                if hasattr(provider, "model_dump"):
                    data["providers"][name] = provider.model_dump(exclude_none=True)

        with open(self.config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def update(self, updates: dict) -> LibraryConfig:
        """
        Update specific fields in the config.

        Args:
            updates: Dict of fields to update (can be nested)

        Returns:
            Updated LibraryConfig
        """
        config = self.load()
        data = config.model_dump()

        # Deep merge updates
        _deep_merge(data, updates)

        new_config = LibraryConfig.model_validate(data)
        self.save(new_config)
        return new_config

    def set_api_key(self, key_name: str, value: str) -> None:
        """Set an API key in the config."""
        config = self.load()
        config.api_keys[key_name] = value
        self.save(config)

    def add_ocr_provider(
        self,
        name: str,
        provider_type: str,
        model: Optional[str] = None,
        rate_limit: Optional[float] = None,
        enabled: bool = True,
        **extra
    ) -> None:
        """Add or update an OCR provider in the config."""
        from .schemas import OCRProviderConfig

        config = self.load()
        config.ocr_providers[name] = OCRProviderConfig(
            type=provider_type,
            model=model,
            rate_limit=rate_limit,
            enabled=enabled,
            extra=extra,
        )
        self.save(config)

    def add_llm_provider(
        self,
        name: str,
        provider_type: str,
        model: str,
        api_key_ref: Optional[str] = None,
        rate_limit: Optional[float] = None,
        **extra
    ) -> None:
        """Add or update an LLM provider in the config."""
        from .schemas import LLMProviderConfig

        config = self.load()
        config.llm_providers[name] = LLMProviderConfig(
            type=provider_type,
            model=model,
            api_key_ref=api_key_ref,
            rate_limit=rate_limit,
            extra=extra,
        )
        self.save(config)

    # Backward compatibility
    def add_provider(
        self,
        name: str,
        provider_type: str,
        model: Optional[str] = None,
        rate_limit: Optional[float] = None,
        enabled: bool = True,
        **extra
    ) -> None:
        """Backward compatibility alias for add_ocr_provider."""
        self.add_ocr_provider(
            name=name,
            provider_type=provider_type,
            model=model,
            rate_limit=rate_limit,
            enabled=enabled,
            **extra
        )


def _deep_merge(base: dict, updates: dict) -> None:
    """
    Deep merge updates into base dict (mutates base).
    """
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_library_config(storage_root: Path) -> LibraryConfig:
    """
    Convenience function to load library config.

    Args:
        storage_root: Root directory for the library

    Returns:
        LibraryConfig instance
    """
    manager = LibraryConfigManager(storage_root)
    return manager.load()
