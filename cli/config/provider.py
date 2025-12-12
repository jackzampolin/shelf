"""
shelf config provider commands - Manage OCR and LLM providers.
"""

from infra.config import LibraryConfigManager
from infra.config import Config


def cmd_provider_list(args):
    """List configured providers (OCR and LLM)."""
    storage_root = Config.book_storage_root
    manager = LibraryConfigManager(storage_root)

    if not manager.exists():
        print(f"✗ No config found at: {manager.config_path}")
        print("  Run 'shelf init' to create one")
        return

    config = manager.load()

    # OCR Providers
    print("\n📷 OCR Providers (text extraction):\n")
    if config.ocr_providers:
        print(f"{'Name':<15} {'Type':<15} {'Model':<35} {'Rate Limit':<12} {'Status'}")
        print("-" * 90)
        for name, provider in config.ocr_providers.items():
            model = provider.model or "-"
            rate = f"{provider.rate_limit}/s" if provider.rate_limit else "-"
            status = "enabled" if provider.enabled else "disabled"
            print(f"{name:<15} {provider.type:<15} {model:<35} {rate:<12} {status}")
        print(f"\nDefault OCR pipeline: {', '.join(config.defaults.ocr_providers)}")
    else:
        print("  (none configured)")

    # LLM Providers
    print("\n🤖 LLM Providers (inference):\n")
    if config.llm_providers:
        print(f"{'Name':<20} {'Type':<15} {'Model':<40} {'Rate Limit'}")
        print("-" * 90)
        for name, provider in config.llm_providers.items():
            rate = f"{provider.rate_limit}/s" if provider.rate_limit else "-"
            print(f"{name:<20} {provider.type:<15} {provider.model:<40} {rate}")
        print(f"\nDefault LLM provider: {config.defaults.llm_provider}")
    else:
        print("  (none configured)")

    print()


def cmd_provider_add(args):
    """Add or update a provider (OCR or LLM)."""
    storage_root = Config.book_storage_root
    manager = LibraryConfigManager(storage_root)

    if not manager.exists():
        print(f"✗ No config found at: {manager.config_path}")
        print("  Run 'shelf init' to create one")
        return

    name = args.name
    provider_type = args.type
    model = args.model
    rate_limit = args.rate_limit
    is_llm = args.llm

    config = manager.load()

    if is_llm:
        # LLM provider requires model
        if not model:
            print("✗ LLM providers require --model")
            print("  Example: shelf config provider add my-llm --llm --type openrouter --model google/gemini-2.0-flash-001")
            return

        is_update = name in config.llm_providers
        manager.add_llm_provider(
            name=name,
            provider_type=provider_type,
            model=model,
            rate_limit=rate_limit,
        )

        action = "Updated" if is_update else "Added"
        print(f"✓ {action} LLM provider: {name}")
        print(f"  Type: {provider_type}")
        print(f"  Model: {model}")
        if rate_limit:
            print(f"  Rate limit: {rate_limit}/s")

        if not is_update:
            print(f"\nTo use this provider by default, run:")
            print(f"  shelf config set defaults.llm_provider {name}")
    else:
        # OCR provider
        enabled = not args.disabled
        is_update = name in config.ocr_providers

        manager.add_ocr_provider(
            name=name,
            provider_type=provider_type,
            model=model,
            rate_limit=rate_limit,
            enabled=enabled,
        )

        action = "Updated" if is_update else "Added"
        print(f"✓ {action} OCR provider: {name}")
        print(f"  Type: {provider_type}")
        if model:
            print(f"  Model: {model}")
        if rate_limit:
            print(f"  Rate limit: {rate_limit}/s")
        print(f"  Status: {'enabled' if enabled else 'disabled'}")

        if not is_update:
            print(f"\nTo use this provider by default, run:")
            print(f"  shelf config set defaults.ocr_providers '[\"mistral\", \"paddle\", \"{name}\"]'")
