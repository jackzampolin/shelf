"""
shelf config show command - Display library configuration.
"""

import json
import yaml

from infra.config import LibraryConfigManager
from infra.config.legacy import Config


def cmd_config_show(args):
    """Show library configuration."""
    storage_root = Config.book_storage_root
    manager = LibraryConfigManager(storage_root)

    if not manager.exists():
        print(f"✗ No config found at: {manager.config_path}")
        print("  Run 'shelf init' to create one")
        return

    config = manager.load()

    if args.json:
        data = config.model_dump()
        # Hide API keys unless requested
        if not args.reveal_keys:
            data['api_keys'] = {
                k: _mask_key(v) for k, v in data['api_keys'].items()
            }
        print(json.dumps(data, indent=2, default=str))
        return

    # Pretty print
    print(f"\n📋 Library Configuration")
    print(f"   Path: {manager.config_path}\n")

    # API Keys
    print("API Keys:")
    for key_name, value in config.api_keys.items():
        resolved = config.resolve_api_key(key_name)
        if args.reveal_keys:
            display = resolved or "(not set)"
        else:
            display = _mask_key(resolved) if resolved else "(not set)"
        print(f"  {key_name}: {display}")

    # Providers
    print("\nProviders:")
    for name, provider in config.providers.items():
        status = "✓" if provider.enabled else "○"
        model_info = f" model={provider.model}" if provider.model else ""
        rate_info = f" rate={provider.rate_limit}/s" if provider.rate_limit else ""
        print(f"  {status} {name}: type={provider.type}{model_info}{rate_info}")

    # Defaults
    print("\nDefaults:")
    print(f"  ocr_providers: {', '.join(config.defaults.ocr_providers)}")
    print(f"  blend_model: {config.defaults.blend_model}")
    print(f"  max_workers: {config.defaults.max_workers}")
    print()


def _mask_key(value: str) -> str:
    """Mask an API key for display."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "****"
    return value[:4] + "..." + value[-4:]
