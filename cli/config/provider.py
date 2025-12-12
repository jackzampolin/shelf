"""
shelf config provider commands - Manage OCR providers.
"""

from infra.config import LibraryConfigManager
from infra.config.legacy import Config


def cmd_provider_list(args):
    """List configured OCR providers."""
    storage_root = Config.book_storage_root
    manager = LibraryConfigManager(storage_root)

    if not manager.exists():
        print(f"✗ No config found at: {manager.config_path}")
        print("  Run 'shelf init' to create one")
        return

    config = manager.load()

    if not config.providers:
        print("No providers configured.")
        print("  Use 'shelf config provider add <name> --type <type>' to add one")
        return

    print("\nConfigured OCR Providers:\n")
    print(f"{'Name':<15} {'Type':<15} {'Model':<35} {'Rate Limit':<12} {'Status'}")
    print("-" * 90)

    for name, provider in config.providers.items():
        model = provider.model or "-"
        rate = f"{provider.rate_limit}/s" if provider.rate_limit else "-"
        status = "enabled" if provider.enabled else "disabled"
        print(f"{name:<15} {provider.type:<15} {model:<35} {rate:<12} {status}")

    # Show which are in default pipeline
    print(f"\nDefault pipeline: {', '.join(config.defaults.ocr_providers)}")
    print()


def cmd_provider_add(args):
    """Add or update an OCR provider."""
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
    enabled = not args.disabled

    # Check if updating existing
    config = manager.load()
    is_update = name in config.providers

    # Add/update provider
    manager.add_provider(
        name=name,
        provider_type=provider_type,
        model=model,
        rate_limit=rate_limit,
        enabled=enabled,
    )

    action = "Updated" if is_update else "Added"
    print(f"✓ {action} provider: {name}")
    print(f"  Type: {provider_type}")
    if model:
        print(f"  Model: {model}")
    if rate_limit:
        print(f"  Rate limit: {rate_limit}/s")
    print(f"  Status: {'enabled' if enabled else 'disabled'}")

    if not is_update:
        print(f"\nTo use this provider by default, run:")
        print(f"  shelf config set defaults.ocr_providers '[\"{name}\", ...]'")
