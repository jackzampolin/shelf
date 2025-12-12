"""
OCR Provider Registry.

Auto-discovers and registers OCR providers for dynamic instantiation.
Providers can be:
1. Built-in (mistral, paddle, olmocr) - auto-registered on import
2. Config-defined (DeepInfra-based) - instantiated from library config

Usage:
    from pipeline.ocr_pages.provider.registry import get_provider, list_providers

    # Get a built-in provider
    provider = get_provider("mistral", stage_storage)

    # Get a provider from config
    provider = get_provider("qwen-vl", stage_storage, config=library_config)
"""

from typing import Dict, Type, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from infra.ocr import OCRProvider
    from infra.config import LibraryConfig


# Registry of provider classes by name
_PROVIDER_REGISTRY: Dict[str, Type["OCRProvider"]] = {}

# Registry of provider type → class for generic providers
_PROVIDER_TYPE_REGISTRY: Dict[str, Type["OCRProvider"]] = {}


def register_provider(name: str, provider_class: Type["OCRProvider"]) -> None:
    """Register a built-in provider class.

    Args:
        name: Provider name (e.g., "mistral", "paddle", "olmocr")
        provider_class: OCRProvider subclass
    """
    _PROVIDER_REGISTRY[name] = provider_class


def register_provider_type(provider_type: str, provider_class: Type["OCRProvider"]) -> None:
    """Register a provider type for config-based instantiation.

    Args:
        provider_type: Provider type (e.g., "deepinfra", "mistral-ocr")
        provider_class: OCRProvider subclass that handles this type
    """
    _PROVIDER_TYPE_REGISTRY[provider_type] = provider_class


def get_provider(
    name: str,
    stage_storage,
    config: Optional["LibraryConfig"] = None,
    **kwargs
) -> "OCRProvider":
    """Instantiate a provider by name.

    Looks up provider in this order:
    1. Built-in registry (mistral, paddle, olmocr)
    2. Config-defined providers (if config provided)

    Args:
        name: Provider name
        stage_storage: StageStorage instance for the provider
        config: Optional LibraryConfig for looking up config-defined providers
        **kwargs: Additional kwargs passed to provider constructor

    Returns:
        Instantiated OCRProvider

    Raises:
        ValueError: If provider not found
    """
    # Check built-in registry first
    if name in _PROVIDER_REGISTRY:
        provider_class = _PROVIDER_REGISTRY[name]
        return provider_class(stage_storage, **kwargs)

    # Check config for provider definition
    if config is not None:
        provider_config = config.get_ocr_provider(name)
        if provider_config is not None:
            return _create_from_config(name, provider_config, stage_storage, config, **kwargs)

    available = list_providers(config)
    raise ValueError(
        f"Unknown OCR provider: '{name}'. "
        f"Available: {', '.join(available)}"
    )


def _create_from_config(
    name: str,
    provider_config,
    stage_storage,
    library_config: "LibraryConfig",
    **kwargs
) -> "OCRProvider":
    """Create a provider from config definition.

    Args:
        name: Provider name
        provider_config: OCRProviderConfig from library config
        stage_storage: StageStorage instance
        library_config: Full library config (for API key resolution)
        **kwargs: Additional kwargs

    Returns:
        Instantiated OCRProvider
    """
    provider_type = provider_config.type

    if provider_type not in _PROVIDER_TYPE_REGISTRY:
        raise ValueError(
            f"Unknown provider type: '{provider_type}'. "
            f"Available types: {', '.join(_PROVIDER_TYPE_REGISTRY.keys())}"
        )

    provider_class = _PROVIDER_TYPE_REGISTRY[provider_type]

    # Build kwargs from config
    init_kwargs = dict(kwargs)

    # Add model if specified
    if provider_config.model:
        init_kwargs["model"] = provider_config.model

    # Add rate limit if specified
    if provider_config.rate_limit:
        init_kwargs["rate_limit"] = provider_config.rate_limit

    # Resolve API key if specified
    if provider_config.api_key_ref:
        api_key = library_config.resolve_api_key(provider_config.api_key_ref)
        if api_key:
            init_kwargs["api_key"] = api_key

    return provider_class(stage_storage, **init_kwargs)


def list_providers(config: Optional["LibraryConfig"] = None) -> list:
    """List all available providers.

    Args:
        config: Optional LibraryConfig to include config-defined providers

    Returns:
        List of provider names
    """
    providers = list(_PROVIDER_REGISTRY.keys())

    if config is not None:
        # Add config-defined providers that aren't built-in
        for name in config.ocr_providers.keys():
            if name not in providers:
                providers.append(name)

    return sorted(providers)


def list_provider_types() -> list:
    """List registered provider types for config-based instantiation."""
    return sorted(_PROVIDER_TYPE_REGISTRY.keys())


def is_registered(name: str) -> bool:
    """Check if a provider name is registered as built-in."""
    return name in _PROVIDER_REGISTRY


def is_type_registered(provider_type: str) -> bool:
    """Check if a provider type is registered."""
    return provider_type in _PROVIDER_TYPE_REGISTRY
