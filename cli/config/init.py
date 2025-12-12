"""
shelf init command - Initialize library configuration.
"""

import os
from pathlib import Path

from infra.config import LibraryConfigManager, LibraryConfig
from infra.config import Config


def cmd_init(args):
    """Initialize library configuration."""
    storage_root = Config.book_storage_root
    manager = LibraryConfigManager(storage_root)

    if manager.exists() and not args.force:
        print(f"✗ Config already exists at: {manager.config_path}")
        print("  Use --force to overwrite")
        return

    # Start with defaults
    config = LibraryConfig.with_defaults()

    # Migrate from .env if requested
    if args.migrate:
        print("Migrating from environment variables...")
        migrated = _migrate_from_env(config)
        if migrated:
            print(f"  Migrated {len(migrated)} API keys: {', '.join(migrated)}")
        else:
            print("  No API keys found in environment")

    # Save config
    manager.save(config)
    print(f"✓ Created config at: {manager.config_path}")

    # Show summary
    print("\nConfiguration summary:")
    print(f"  Storage root: {storage_root}")
    print(f"  Default OCR providers: {', '.join(config.defaults.ocr_providers)}")
    print(f"  Default LLM provider: {config.defaults.llm_provider}")
    print(f"  Default max workers: {config.defaults.max_workers}")

    # Check API keys
    print("\nAPI keys:")
    for key_name, value in config.api_keys.items():
        resolved = config.resolve_api_key(key_name)
        if resolved:
            print(f"  ✓ {key_name}: configured")
        else:
            print(f"  ○ {key_name}: not set (using {value})")

    print("\nProviders:")
    for name, provider in config.providers.items():
        status = "enabled" if provider.enabled else "disabled"
        model_info = f" ({provider.model})" if provider.model else ""
        print(f"  {name}: {provider.type}{model_info} [{status}]")


def _migrate_from_env(config: LibraryConfig) -> list:
    """
    Migrate API keys from environment variables to config.

    Returns list of migrated key names.
    """
    migrated = []

    # Map of env vars to config key names
    env_mapping = {
        'OPENROUTER_API_KEY': 'openrouter',
        'MISTRAL_API_KEY': 'mistral',
        'DEEPINFRA_API_KEY': 'deepinfra',
        'DATALAB_API_KEY': 'datalab',
        'DEEPSEEK_API_KEY': 'deepseek',
    }

    for env_var, key_name in env_mapping.items():
        value = os.getenv(env_var)
        if value:
            # Store the literal value (not the env var reference)
            config.api_keys[key_name] = value
            migrated.append(key_name)

    return migrated
