"""
Tests for infra/config/ module.

Tests the hierarchical configuration system:
- Library config loading/saving
- Book config with inheritance
- Env var expansion
- Provider definitions

All tests use temporary directories - no production data touched.
"""

import os
import pytest
import yaml
from pathlib import Path

from infra.config import (
    LibraryConfig,
    BookConfig,
    ResolvedBookConfig,
    OCRProviderConfig,
    LLMProviderConfig,
    ProviderConfig,
    DefaultsConfig,
    LibraryConfigManager,
    BookConfigManager,
    resolve_env_vars,
    load_library_config,
    resolve_book_config,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def tmp_storage(tmp_path):
    """Create a temporary storage root directory."""
    storage = tmp_path / "shelf"
    storage.mkdir()
    return storage


@pytest.fixture
def library_manager(tmp_storage):
    """Create a LibraryConfigManager with temp storage."""
    return LibraryConfigManager(tmp_storage)


@pytest.fixture
def book_manager(tmp_storage):
    """Create a BookConfigManager for a test book."""
    # Create book directory
    book_dir = tmp_storage / "books" / "test-book"
    book_dir.mkdir(parents=True)
    return BookConfigManager(tmp_storage, "test-book")


# =============================================================================
# Schema Tests
# =============================================================================

class TestResolveEnvVars:
    """Test environment variable resolution."""

    def test_resolves_single_var(self, monkeypatch):
        """${VAR} should be replaced with env value."""
        monkeypatch.setenv("TEST_KEY", "secret123")
        result = resolve_env_vars("${TEST_KEY}")
        assert result == "secret123"

    def test_resolves_multiple_vars(self, monkeypatch):
        """Multiple ${VAR} in string should all be resolved."""
        monkeypatch.setenv("USER", "alice")
        monkeypatch.setenv("HOST", "example.com")
        result = resolve_env_vars("${USER}@${HOST}")
        assert result == "alice@example.com"

    def test_missing_var_becomes_empty(self, monkeypatch):
        """Missing env var should become empty string."""
        monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
        result = resolve_env_vars("${DEFINITELY_NOT_SET}")
        assert result == ""

    def test_literal_string_unchanged(self):
        """String without ${} should be unchanged."""
        result = resolve_env_vars("literal-api-key")
        assert result == "literal-api-key"

    def test_mixed_literal_and_var(self, monkeypatch):
        """Mix of literal and ${VAR} should work."""
        monkeypatch.setenv("VERSION", "v2")
        result = resolve_env_vars("api-${VERSION}-key")
        assert result == "api-v2-key"


class TestOCRProviderConfig:
    """Test OCRProviderConfig schema."""

    def test_minimal_provider(self):
        """Provider only needs type."""
        config = OCRProviderConfig(type="mistral-ocr")
        assert config.type == "mistral-ocr"
        assert config.enabled is True
        assert config.model is None

    def test_full_provider(self):
        """Provider with all fields."""
        config = OCRProviderConfig(
            type="deepinfra",
            model="org/model-name",
            rate_limit=10.0,
            enabled=False,
            extra={"custom": "value"},
        )
        assert config.type == "deepinfra"
        assert config.model == "org/model-name"
        assert config.rate_limit == 10.0
        assert config.enabled is False
        assert config.extra == {"custom": "value"}

    def test_backward_compat_alias(self):
        """ProviderConfig should be alias for OCRProviderConfig."""
        config = ProviderConfig(type="mistral-ocr")
        assert isinstance(config, OCRProviderConfig)


class TestLLMProviderConfig:
    """Test LLMProviderConfig schema."""

    def test_minimal_provider(self):
        """LLM provider needs type and model."""
        config = LLMProviderConfig(type="openrouter", model="google/gemini-2.0-flash-001")
        assert config.type == "openrouter"
        assert config.model == "google/gemini-2.0-flash-001"
        assert config.api_key_ref is None

    def test_full_provider(self):
        """LLM provider with all fields."""
        config = LLMProviderConfig(
            type="openrouter",
            model="anthropic/claude-3.5-sonnet",
            api_key_ref="openrouter",
            rate_limit=5.0,
            extra={"custom": "value"},
        )
        assert config.type == "openrouter"
        assert config.model == "anthropic/claude-3.5-sonnet"
        assert config.api_key_ref == "openrouter"
        assert config.rate_limit == 5.0


class TestLibraryConfig:
    """Test LibraryConfig schema."""

    def test_empty_config_valid(self):
        """Empty config should be valid with defaults."""
        config = LibraryConfig()
        assert config.api_keys == {}
        assert config.ocr_providers == {}
        assert config.llm_providers == {}
        assert config.defaults.ocr_providers == ["mistral", "paddle"]
        assert config.defaults.llm_provider == "gemini-flash"

    def test_with_defaults_creates_sensible_config(self):
        """with_defaults() should create usable config."""
        config = LibraryConfig.with_defaults()

        # Has api key placeholders
        assert "openrouter" in config.api_keys
        assert "${OPENROUTER_API_KEY}" in config.api_keys["openrouter"]

        # Has OCR providers
        assert "mistral" in config.ocr_providers
        assert "paddle" in config.ocr_providers
        assert config.ocr_providers["mistral"].type == "mistral-ocr"

        # Has LLM providers
        assert "gemini-flash" in config.llm_providers
        assert "claude-sonnet" in config.llm_providers
        assert config.llm_providers["gemini-flash"].model == "google/gemini-2.0-flash-001"

        # Has defaults
        assert config.defaults.ocr_providers == ["mistral", "paddle"]
        assert config.defaults.llm_provider == "gemini-flash"

    def test_backward_compat_providers_property(self):
        """providers property should map to ocr_providers."""
        config = LibraryConfig.with_defaults()
        assert config.providers == config.ocr_providers

    def test_resolve_api_key_from_env(self, monkeypatch):
        """resolve_api_key should expand env vars."""
        monkeypatch.setenv("MY_API_KEY", "secret123")

        config = LibraryConfig(
            api_keys={"myservice": "${MY_API_KEY}"}
        )
        result = config.resolve_api_key("myservice")
        assert result == "secret123"

    def test_resolve_api_key_literal(self):
        """resolve_api_key should return literal values."""
        config = LibraryConfig(
            api_keys={"myservice": "literal-key"}
        )
        result = config.resolve_api_key("myservice")
        assert result == "literal-key"

    def test_resolve_api_key_missing(self):
        """resolve_api_key should return None for missing key."""
        config = LibraryConfig()
        result = config.resolve_api_key("nonexistent")
        assert result is None

    def test_get_ocr_provider(self):
        """get_ocr_provider should return OCR provider config."""
        config = LibraryConfig.with_defaults()
        provider = config.get_ocr_provider("mistral")

        assert provider is not None
        assert provider.type == "mistral-ocr"

    def test_get_ocr_provider_missing(self):
        """get_ocr_provider should return None for missing provider."""
        config = LibraryConfig()
        assert config.get_ocr_provider("nonexistent") is None

    def test_get_llm_provider(self):
        """get_llm_provider should return LLM provider config."""
        config = LibraryConfig.with_defaults()
        provider = config.get_llm_provider("gemini-flash")

        assert provider is not None
        assert provider.type == "openrouter"
        assert provider.model == "google/gemini-2.0-flash-001"

    def test_get_llm_provider_missing(self):
        """get_llm_provider should return None for missing provider."""
        config = LibraryConfig()
        assert config.get_llm_provider("nonexistent") is None

    def test_backward_compat_get_provider(self):
        """get_provider should be alias for get_ocr_provider."""
        config = LibraryConfig.with_defaults()
        assert config.get_provider("mistral") == config.get_ocr_provider("mistral")


class TestBookConfig:
    """Test BookConfig schema."""

    def test_empty_book_config(self):
        """Empty book config means use library defaults."""
        config = BookConfig()
        assert config.ocr_providers is None
        assert config.llm_provider is None
        assert config.max_workers is None

    def test_book_config_with_overrides(self):
        """Book config can override specific values."""
        config = BookConfig(
            ocr_providers=["mistral", "paddle", "olmocr"],
            llm_provider="claude-sonnet",
        )
        assert config.ocr_providers == ["mistral", "paddle", "olmocr"]
        assert config.llm_provider == "claude-sonnet"
        assert config.max_workers is None  # Not overridden


class TestResolvedBookConfig:
    """Test ResolvedBookConfig merging."""

    def test_uses_library_defaults_when_no_book_config(self):
        """Without book config, library defaults apply."""
        library = LibraryConfig.with_defaults()
        resolved = ResolvedBookConfig.from_configs(library, None)

        assert resolved.ocr_providers == ["mistral", "paddle"]
        assert resolved.llm_provider == "gemini-flash"
        assert resolved.max_workers == 10

    def test_book_config_overrides_library(self):
        """Book config values should override library defaults."""
        library = LibraryConfig.with_defaults()
        book = BookConfig(
            ocr_providers=["mistral"],
            max_workers=5,
        )
        resolved = ResolvedBookConfig.from_configs(library, book)

        assert resolved.ocr_providers == ["mistral"]  # Overridden
        assert resolved.llm_provider == "gemini-flash"  # Default
        assert resolved.max_workers == 5  # Overridden

    def test_partial_override(self):
        """Only specified values should be overridden."""
        library = LibraryConfig(
            defaults=DefaultsConfig(
                ocr_providers=["a", "b"],
                llm_provider="provider-x",
                max_workers=20,
            )
        )
        book = BookConfig(llm_provider="provider-y")
        resolved = ResolvedBookConfig.from_configs(library, book)

        assert resolved.ocr_providers == ["a", "b"]  # Not overridden
        assert resolved.llm_provider == "provider-y"  # Overridden
        assert resolved.max_workers == 20  # Not overridden


# =============================================================================
# Library Config Manager Tests
# =============================================================================

class TestLibraryConfigManager:
    """Test LibraryConfigManager operations."""

    def test_exists_false_initially(self, library_manager):
        """exists() should return False before config created."""
        assert library_manager.exists() is False

    def test_load_returns_defaults_when_no_file(self, library_manager):
        """load() should return defaults if no config file."""
        config = library_manager.load()

        assert isinstance(config, LibraryConfig)
        # Should have default OCR providers from with_defaults()
        assert "mistral" in config.ocr_providers
        # Should have default LLM providers
        assert "gemini-flash" in config.llm_providers

    def test_save_creates_file(self, library_manager, tmp_storage):
        """save() should create config file."""
        config = LibraryConfig.with_defaults()
        library_manager.save(config)

        assert library_manager.exists() is True
        assert (tmp_storage / "config.yaml").exists()

    def test_save_and_load_roundtrip(self, library_manager):
        """Saved config should load identically."""
        original = LibraryConfig(
            api_keys={"test": "value"},
            ocr_providers={
                "custom-ocr": OCRProviderConfig(type="custom-type", model="custom-model")
            },
            llm_providers={
                "custom-llm": LLMProviderConfig(type="openrouter", model="org/model")
            },
            defaults=DefaultsConfig(
                ocr_providers=["custom-ocr"],
                llm_provider="custom-llm",
                max_workers=5,
            ),
        )

        library_manager.save(original)
        loaded = library_manager.load()

        assert loaded.api_keys == original.api_keys
        assert loaded.ocr_providers["custom-ocr"].type == "custom-type"
        assert loaded.llm_providers["custom-llm"].model == "org/model"
        assert loaded.defaults.ocr_providers == ["custom-ocr"]
        assert loaded.defaults.llm_provider == "custom-llm"

    def test_update_merges_changes(self, library_manager):
        """update() should merge changes into existing config."""
        # Start with defaults
        library_manager.save(LibraryConfig.with_defaults())

        # Update one field
        library_manager.update({"defaults": {"max_workers": 50}})

        config = library_manager.load()
        assert config.defaults.max_workers == 50
        # Other defaults preserved
        assert config.defaults.ocr_providers == ["mistral", "paddle"]

    def test_set_api_key(self, library_manager):
        """set_api_key() should add/update API key."""
        library_manager.save(LibraryConfig())
        library_manager.set_api_key("newservice", "newkey")

        config = library_manager.load()
        assert config.api_keys["newservice"] == "newkey"

    def test_add_ocr_provider(self, library_manager):
        """add_ocr_provider() should add new OCR provider config."""
        library_manager.save(LibraryConfig())
        library_manager.add_ocr_provider(
            name="new-ocr",
            provider_type="deepinfra",
            model="org/new-model",
            rate_limit=5.0,
        )

        config = library_manager.load()
        provider = config.ocr_providers["new-ocr"]
        assert provider.type == "deepinfra"
        assert provider.model == "org/new-model"
        assert provider.rate_limit == 5.0

    def test_add_llm_provider(self, library_manager):
        """add_llm_provider() should add new LLM provider config."""
        library_manager.save(LibraryConfig())
        library_manager.add_llm_provider(
            name="my-claude",
            provider_type="openrouter",
            model="anthropic/claude-3.5-sonnet",
            rate_limit=10.0,
        )

        config = library_manager.load()
        provider = config.llm_providers["my-claude"]
        assert provider.type == "openrouter"
        assert provider.model == "anthropic/claude-3.5-sonnet"
        assert provider.rate_limit == 10.0

    def test_add_provider_backward_compat(self, library_manager):
        """add_provider() should be alias for add_ocr_provider."""
        library_manager.save(LibraryConfig())
        library_manager.add_provider(
            name="compat-test",
            provider_type="deepinfra",
            model="org/model",
        )

        config = library_manager.load()
        assert "compat-test" in config.ocr_providers

    def test_config_file_is_valid_yaml(self, library_manager, tmp_storage):
        """Saved config should be valid, readable YAML."""
        library_manager.save(LibraryConfig.with_defaults())

        config_path = tmp_storage / "config.yaml"
        with open(config_path) as f:
            data = yaml.safe_load(f)

        assert "api_keys" in data
        assert "ocr_providers" in data
        assert "llm_providers" in data
        assert "defaults" in data


# =============================================================================
# Book Config Manager Tests
# =============================================================================

class TestBookConfigManager:
    """Test BookConfigManager operations."""

    def test_exists_false_initially(self, book_manager):
        """exists() should return False before config created."""
        assert book_manager.exists() is False

    def test_load_returns_empty_when_no_file(self, book_manager):
        """load() should return empty BookConfig if no file."""
        config = book_manager.load()

        assert isinstance(config, BookConfig)
        assert config.ocr_providers is None
        assert config.llm_provider is None

    def test_save_creates_file(self, book_manager):
        """save() should create config file."""
        config = BookConfig(ocr_providers=["mistral"])
        book_manager.save(config)

        assert book_manager.exists() is True

    def test_save_empty_config_removes_file(self, book_manager):
        """save() with empty config should remove file."""
        # First create a config
        book_manager.save(BookConfig(ocr_providers=["mistral"]))
        assert book_manager.exists() is True

        # Save empty config
        book_manager.save(BookConfig())
        assert book_manager.exists() is False

    def test_resolve_uses_library_defaults(self, tmp_storage):
        """resolve() should use library defaults for unset values."""
        # Create library config
        lib_manager = LibraryConfigManager(tmp_storage)
        lib_manager.save(LibraryConfig.with_defaults())

        # Create book manager (no book config)
        book_dir = tmp_storage / "books" / "test-book"
        book_dir.mkdir(parents=True)
        book_manager = BookConfigManager(tmp_storage, "test-book")

        resolved = book_manager.resolve()

        assert resolved.ocr_providers == ["mistral", "paddle"]
        assert resolved.llm_provider == "gemini-flash"

    def test_resolve_with_book_overrides(self, tmp_storage):
        """resolve() should merge book overrides with library defaults."""
        # Create library config
        lib_manager = LibraryConfigManager(tmp_storage)
        lib_manager.save(LibraryConfig.with_defaults())

        # Create book with overrides
        book_dir = tmp_storage / "books" / "test-book"
        book_dir.mkdir(parents=True)
        book_manager = BookConfigManager(tmp_storage, "test-book")
        book_manager.save(BookConfig(
            ocr_providers=["mistral", "paddle", "olmocr"],
            max_workers=20,
        ))

        resolved = book_manager.resolve()

        assert resolved.ocr_providers == ["mistral", "paddle", "olmocr"]  # Overridden
        assert resolved.llm_provider == "gemini-flash"  # Library default
        assert resolved.max_workers == 20  # Overridden

    def test_set_updates_config(self, book_manager):
        """set() should update specific fields."""
        book_manager.set(llm_provider="new-provider", max_workers=15)

        config = book_manager.load()
        assert config.llm_provider == "new-provider"
        assert config.max_workers == 15

    def test_clear_removes_config(self, book_manager):
        """clear() should remove book config file."""
        book_manager.save(BookConfig(ocr_providers=["mistral"]))
        assert book_manager.exists() is True

        book_manager.clear()
        assert book_manager.exists() is False


# =============================================================================
# Convenience Function Tests
# =============================================================================

class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_load_library_config(self, tmp_storage):
        """load_library_config() should load config from path."""
        # Create config
        manager = LibraryConfigManager(tmp_storage)
        manager.save(LibraryConfig(
            api_keys={"test": "testvalue"}
        ))

        # Load via convenience function
        config = load_library_config(tmp_storage)
        assert config.api_keys["test"] == "testvalue"

    def test_resolve_book_config(self, tmp_storage):
        """resolve_book_config() should return merged config."""
        # Create library config
        lib_manager = LibraryConfigManager(tmp_storage)
        lib_manager.save(LibraryConfig.with_defaults())

        # Create book directory
        book_dir = tmp_storage / "books" / "test-book"
        book_dir.mkdir(parents=True)

        # Resolve via convenience function
        resolved = resolve_book_config(tmp_storage, "test-book")

        assert isinstance(resolved, ResolvedBookConfig)
        assert resolved.ocr_providers == ["mistral", "paddle"]


# =============================================================================
# Integration Tests
# =============================================================================

class TestConfigIntegration:
    """Integration tests for the full config system."""

    def test_full_workflow(self, tmp_storage):
        """Test complete workflow: init -> configure -> use."""
        # 1. Initialize library config
        lib_manager = LibraryConfigManager(tmp_storage)
        lib_manager.save(LibraryConfig.with_defaults())

        # 2. Add custom OCR provider
        lib_manager.add_ocr_provider(
            name="qwen-vl",
            provider_type="deepinfra",
            model="Qwen/Qwen2-VL-72B-Instruct",
        )

        # 3. Add custom LLM provider
        lib_manager.add_llm_provider(
            name="my-claude",
            provider_type="openrouter",
            model="anthropic/claude-3.5-sonnet",
        )

        # 4. Create book with custom config
        book_dir = tmp_storage / "books" / "my-book"
        book_dir.mkdir(parents=True)
        book_manager = BookConfigManager(tmp_storage, "my-book")
        book_manager.set(
            ocr_providers=["mistral", "qwen-vl"],
            llm_provider="my-claude",
        )

        # 5. Resolve final config
        resolved = book_manager.resolve()

        assert resolved.ocr_providers == ["mistral", "qwen-vl"]
        assert resolved.llm_provider == "my-claude"
        assert resolved.max_workers == 10  # Library default

        # 6. Verify library has the new providers
        lib_config = lib_manager.load()
        assert "qwen-vl" in lib_config.ocr_providers
        assert "my-claude" in lib_config.llm_providers

    def test_multiple_books_independent_configs(self, tmp_storage):
        """Different books can have different configs."""
        # Setup library
        lib_manager = LibraryConfigManager(tmp_storage)
        lib_manager.save(LibraryConfig.with_defaults())

        # Book A: custom OCR providers
        book_a_dir = tmp_storage / "books" / "book-a"
        book_a_dir.mkdir(parents=True)
        book_a = BookConfigManager(tmp_storage, "book-a")
        book_a.set(ocr_providers=["mistral"])

        # Book B: default providers, custom LLM provider
        book_b_dir = tmp_storage / "books" / "book-b"
        book_b_dir.mkdir(parents=True)
        book_b = BookConfigManager(tmp_storage, "book-b")
        book_b.set(llm_provider="claude-sonnet")

        # Book C: no overrides
        book_c_dir = tmp_storage / "books" / "book-c"
        book_c_dir.mkdir(parents=True)
        book_c = BookConfigManager(tmp_storage, "book-c")

        # Resolve all
        resolved_a = book_a.resolve()
        resolved_b = book_b.resolve()
        resolved_c = book_c.resolve()

        # Verify independence
        assert resolved_a.ocr_providers == ["mistral"]
        assert resolved_a.llm_provider == "gemini-flash"

        assert resolved_b.ocr_providers == ["mistral", "paddle"]
        assert resolved_b.llm_provider == "claude-sonnet"

        assert resolved_c.ocr_providers == ["mistral", "paddle"]
        assert resolved_c.llm_provider == "gemini-flash"
