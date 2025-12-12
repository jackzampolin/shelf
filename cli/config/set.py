"""
shelf config set command - Set configuration values.
"""

import json

from infra.config import LibraryConfigManager
from infra.config.legacy import Config


def cmd_config_set(args):
    """Set a configuration value."""
    storage_root = Config.book_storage_root
    manager = LibraryConfigManager(storage_root)

    if not manager.exists():
        print(f"✗ No config found at: {manager.config_path}")
        print("  Run 'shelf init' to create one")
        return

    key = args.key
    value = args.value

    # Parse value (try to convert to appropriate type)
    parsed_value = _parse_value(value)

    # Handle nested keys (e.g., "defaults.max_workers")
    parts = key.split('.')

    if len(parts) == 1:
        # Top-level key
        print(f"✗ Cannot set top-level key '{key}' directly")
        print("  Use nested keys like 'defaults.max_workers' or 'api_keys.openrouter'")
        return

    # Build nested update dict
    updates = {}
    current = updates
    for part in parts[:-1]:
        current[part] = {}
        current = current[part]
    current[parts[-1]] = parsed_value

    # Apply update
    try:
        config = manager.update(updates)
        print(f"✓ Set {key} = {parsed_value}")

        # Show the updated value
        result = config.model_dump()
        for part in parts:
            result = result.get(part, {})
        print(f"  Current value: {result}")

    except Exception as e:
        print(f"✗ Failed to set {key}: {e}")


def _parse_value(value: str):
    """
    Parse a string value into appropriate Python type.

    Handles:
    - Numbers (int, float)
    - Booleans (true, false)
    - JSON arrays and objects
    - Strings (default)
    """
    # Boolean
    if value.lower() == 'true':
        return True
    if value.lower() == 'false':
        return False

    # Number
    try:
        if '.' in value:
            return float(value)
        return int(value)
    except ValueError:
        pass

    # JSON (arrays, objects)
    if value.startswith('[') or value.startswith('{'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

    # Default: string
    return value
