"""
Tests for OCR provider registry.
"""

import pytest
from unittest.mock import MagicMock, patch

from pipeline.ocr_pages.provider import (
    get_provider,
    list_providers,
    list_provider_types,
    is_registered,
    is_type_registered,
    MistralOCRProvider,
    OlmOCRProvider,
    PaddleOCRProvider,
    DeepInfraGenericProvider,
)
from pipeline.ocr_pages.provider.registry import (
    register_provider,
    register_provider_type,
    _PROVIDER_REGISTRY,
    _PROVIDER_TYPE_REGISTRY,
)
from infra.config import LibraryConfig, OCRProviderConfig


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_stage_storage():
    """Create a mock stage storage."""
    storage = MagicMock()
    storage.metrics_manager = MagicMock()
    return storage


@pytest.fixture
def library_config_with_providers():
    """Create a library config with custom providers."""
    return LibraryConfig(
        api_keys={"deepinfra": "test-key"},
        ocr_providers={
            "qwen-vl": OCRProviderConfig(
                type="deepinfra",
                model="Qwen/Qwen2-VL-72B-Instruct",
                rate_limit=5.0,
            ),
            "custom-ocr": OCRProviderConfig(
                type="deepinfra",
                model="some/custom-model",
                api_key_ref="deepinfra",
            ),
        },
        llm_providers={},
    )


# =============================================================================
# Built-in Provider Tests
# =============================================================================

class TestBuiltinProviders:
    """Tests for built-in provider registration."""

    def test_mistral_registered(self):
        """Mistral provider should be registered."""
        assert is_registered("mistral") is True
        assert "mistral" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["mistral"] is MistralOCRProvider

    def test_paddle_registered(self):
        """Paddle provider should be registered."""
        assert is_registered("paddle") is True
        assert "paddle" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["paddle"] is PaddleOCRProvider

    def test_olmocr_registered(self):
        """OlmOCR provider should be registered."""
        assert is_registered("olmocr") is True
        assert "olmocr" in _PROVIDER_REGISTRY
        assert _PROVIDER_REGISTRY["olmocr"] is OlmOCRProvider

    def test_unknown_not_registered(self):
        """Unknown providers should not be registered."""
        assert is_registered("unknown-provider") is False
        assert is_registered("qwen-vl") is False  # Config-defined, not built-in


class TestProviderTypes:
    """Tests for provider type registration."""

    def test_mistral_ocr_type_registered(self):
        """mistral-ocr type should be registered."""
        assert is_type_registered("mistral-ocr") is True
        assert _PROVIDER_TYPE_REGISTRY["mistral-ocr"] is MistralOCRProvider

    def test_deepinfra_type_registered(self):
        """deepinfra type should be registered."""
        assert is_type_registered("deepinfra") is True
        assert _PROVIDER_TYPE_REGISTRY["deepinfra"] is DeepInfraGenericProvider

    def test_unknown_type_not_registered(self):
        """Unknown types should not be registered."""
        assert is_type_registered("unknown-type") is False


# =============================================================================
# list_providers Tests
# =============================================================================

class TestListProviders:
    """Tests for list_providers function."""

    def test_list_builtin_providers(self):
        """Should list built-in providers without config."""
        providers = list_providers()
        assert "mistral" in providers
        assert "paddle" in providers
        assert "olmocr" in providers

    def test_list_includes_config_providers(self, library_config_with_providers):
        """Should include config-defined providers."""
        providers = list_providers(library_config_with_providers)
        assert "mistral" in providers
        assert "paddle" in providers
        assert "olmocr" in providers
        assert "qwen-vl" in providers
        assert "custom-ocr" in providers

    def test_list_provider_types(self):
        """Should list registered provider types."""
        types = list_provider_types()
        assert "mistral-ocr" in types
        assert "deepinfra" in types


# =============================================================================
# get_provider Tests
# =============================================================================

class TestGetProvider:
    """Tests for get_provider function."""

    @patch.dict('os.environ', {'MISTRAL_API_KEY': 'test-key'})
    def test_get_builtin_mistral(self, mock_stage_storage):
        """Should instantiate Mistral provider."""
        provider = get_provider("mistral", mock_stage_storage)
        assert isinstance(provider, MistralOCRProvider)

    @patch.dict('os.environ', {'DEEPINFRA_API_KEY': 'test-key'})
    def test_get_builtin_paddle(self, mock_stage_storage):
        """Should instantiate Paddle provider."""
        provider = get_provider("paddle", mock_stage_storage)
        assert isinstance(provider, PaddleOCRProvider)

    @patch.dict('os.environ', {'DEEPINFRA_API_KEY': 'test-key'})
    def test_get_builtin_olmocr(self, mock_stage_storage):
        """Should instantiate OlmOCR provider."""
        provider = get_provider("olmocr", mock_stage_storage)
        assert isinstance(provider, OlmOCRProvider)

    def test_get_unknown_raises(self, mock_stage_storage):
        """Should raise for unknown provider."""
        with pytest.raises(ValueError) as exc:
            get_provider("unknown-provider", mock_stage_storage)
        assert "Unknown OCR provider" in str(exc.value)
        assert "unknown-provider" in str(exc.value)

    @patch.dict('os.environ', {'DEEPINFRA_API_KEY': 'test-key'})
    def test_get_config_defined_provider(self, mock_stage_storage, library_config_with_providers):
        """Should instantiate config-defined provider."""
        provider = get_provider(
            "qwen-vl",
            mock_stage_storage,
            config=library_config_with_providers
        )
        assert isinstance(provider, DeepInfraGenericProvider)
        assert provider.model == "Qwen/Qwen2-VL-72B-Instruct"
        assert provider._rate_limit == 5.0

    @patch.dict('os.environ', {})
    def test_get_config_provider_with_api_key_ref(self, mock_stage_storage, library_config_with_providers):
        """Should resolve API key from config."""
        provider = get_provider(
            "custom-ocr",
            mock_stage_storage,
            config=library_config_with_providers
        )
        assert isinstance(provider, DeepInfraGenericProvider)
        # API key should be resolved from library config
        # (test-key from api_keys.deepinfra)


# =============================================================================
# Custom Registration Tests
# =============================================================================

class TestCustomRegistration:
    """Tests for custom provider registration."""

    def test_register_custom_provider(self, mock_stage_storage):
        """Should allow registering custom providers."""
        # Create a mock provider class
        class CustomProvider(MagicMock):
            def __init__(self, stage_storage, **kwargs):
                pass

        # Register it
        register_provider("custom-test", CustomProvider)

        # Should be listed
        assert is_registered("custom-test") is True
        assert "custom-test" in list_providers()

        # Cleanup
        del _PROVIDER_REGISTRY["custom-test"]

    def test_register_custom_type(self):
        """Should allow registering custom provider types."""
        class CustomTypeProvider(MagicMock):
            pass

        register_provider_type("custom-type", CustomTypeProvider)

        assert is_type_registered("custom-type") is True
        assert "custom-type" in list_provider_types()

        # Cleanup
        del _PROVIDER_TYPE_REGISTRY["custom-type"]


# =============================================================================
# DeepInfraGenericProvider Tests
# =============================================================================

class TestDeepInfraGenericProvider:
    """Tests for the generic DeepInfra provider."""

    @patch.dict('os.environ', {'DEEPINFRA_API_KEY': 'test-key'})
    def test_init_with_model(self, mock_stage_storage):
        """Should initialize with model."""
        provider = DeepInfraGenericProvider(
            mock_stage_storage,
            model="test/model-7B"
        )
        assert provider.model == "test/model-7B"

    @patch.dict('os.environ', {'DEEPINFRA_API_KEY': 'test-key'})
    def test_init_with_custom_prompt(self, mock_stage_storage):
        """Should accept custom prompt."""
        provider = DeepInfraGenericProvider(
            mock_stage_storage,
            model="test/model",
            prompt="Custom OCR prompt"
        )
        assert provider.prompt == "Custom OCR prompt"

    @patch.dict('os.environ', {'DEEPINFRA_API_KEY': 'test-key'})
    def test_init_with_rate_limit(self, mock_stage_storage):
        """Should accept rate limit."""
        provider = DeepInfraGenericProvider(
            mock_stage_storage,
            model="test/model",
            rate_limit=5.0
        )
        assert provider.requests_per_second == 5.0

    @patch.dict('os.environ', {'DEEPINFRA_API_KEY': 'test-key'})
    def test_name_derived_from_model(self, mock_stage_storage):
        """Provider name should be derived from model."""
        provider = DeepInfraGenericProvider(
            mock_stage_storage,
            model="Qwen/Qwen2-VL-72B-Instruct"
        )
        assert "qwen2-vl" in provider.name.lower()

    @patch.dict('os.environ', {'DEEPINFRA_API_KEY': 'test-key'})
    def test_default_rate_limit_is_infinite(self, mock_stage_storage):
        """Default rate limit should be infinite."""
        provider = DeepInfraGenericProvider(
            mock_stage_storage,
            model="test/model"
        )
        assert provider.requests_per_second == float('inf')
