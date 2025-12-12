"""
OCR Provider package.

Provides pluggable OCR providers that can be:
1. Built-in (auto-registered on import)
2. Config-defined (instantiated from library config)

Usage:
    from pipeline.ocr_pages.provider import get_provider, list_providers

    # Get a provider by name
    provider = get_provider("mistral", stage_storage)

    # List available providers
    available = list_providers(library_config)
"""

from .registry import (
    register_provider,
    register_provider_type,
    get_provider,
    list_providers,
    list_provider_types,
    is_registered,
    is_type_registered,
)

# Import provider classes
from .mistral import MistralOCRProvider
from .olmocr import OlmOCRProvider
from .paddleocr import PaddleOCRProvider
from .deepinfra_generic import DeepInfraGenericProvider

# Auto-register built-in providers
register_provider("mistral", MistralOCRProvider)
register_provider("paddle", PaddleOCRProvider)
register_provider("olmocr", OlmOCRProvider)

# Register provider types for config-based instantiation
register_provider_type("mistral-ocr", MistralOCRProvider)
register_provider_type("deepinfra", DeepInfraGenericProvider)


__all__ = [
    # Registry functions
    "get_provider",
    "list_providers",
    "list_provider_types",
    "register_provider",
    "register_provider_type",
    "is_registered",
    "is_type_registered",
    # Provider classes (for direct instantiation if needed)
    "MistralOCRProvider",
    "OlmOCRProvider",
    "PaddleOCRProvider",
    "DeepInfraGenericProvider",
]
