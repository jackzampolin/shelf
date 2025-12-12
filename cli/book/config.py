"""
Book-level config commands.

shelf book <scan-id> config show
shelf book <scan-id> config set <key> <value>
shelf book <scan-id> config clear
"""

import json

from infra.config import BookConfigManager, resolve_book_config
from infra.config.legacy import Config


def cmd_book_config_show(args):
    """Show book configuration (overrides + resolved)."""
    storage_root = Config.book_storage_root
    scan_id = args.scan_id

    manager = BookConfigManager(storage_root, scan_id)

    # Check book exists
    if not manager.book_dir.exists():
        print(f"✗ Book not found: {scan_id}")
        return

    book_config = manager.load()
    resolved = manager.resolve()

    if args.json:
        data = {
            "overrides": book_config.model_dump(exclude_none=True),
            "resolved": resolved.model_dump(),
        }
        print(json.dumps(data, indent=2))
        return

    # Pretty print
    print(f"\n📖 Book Configuration: {scan_id}\n")

    # Show overrides (if any)
    overrides = book_config.model_dump(exclude_none=True, exclude_defaults=True)
    if overrides:
        print("Overrides (book-specific):")
        for key, value in overrides.items():
            print(f"  {key}: {value}")
    else:
        print("Overrides: (none - using library defaults)")

    # Show resolved config
    print("\nResolved configuration:")
    print(f"  ocr_providers: {', '.join(resolved.ocr_providers)}")
    print(f"  blend_model: {resolved.blend_model}")
    print(f"  max_workers: {resolved.max_workers}")

    if resolved.extra:
        print(f"  extra: {resolved.extra}")

    print()


def cmd_book_config_set(args):
    """Set a book configuration value."""
    storage_root = Config.book_storage_root
    scan_id = args.scan_id

    manager = BookConfigManager(storage_root, scan_id)

    # Check book exists
    if not manager.book_dir.exists():
        print(f"✗ Book not found: {scan_id}")
        return

    key = args.key
    value = args.value

    # Parse value
    parsed_value = _parse_value(value)

    # Valid keys for book config
    valid_keys = ['ocr_providers', 'blend_model', 'max_workers']
    if key not in valid_keys:
        print(f"✗ Invalid key: {key}")
        print(f"  Valid keys: {', '.join(valid_keys)}")
        return

    # Set the value
    try:
        manager.set(**{key: parsed_value})
        print(f"✓ Set {key} = {parsed_value} for book '{scan_id}'")

        # Show resolved config
        resolved = manager.resolve()
        print(f"\nResolved configuration:")
        print(f"  ocr_providers: {', '.join(resolved.ocr_providers)}")
        print(f"  blend_model: {resolved.blend_model}")
        print(f"  max_workers: {resolved.max_workers}")

    except Exception as e:
        print(f"✗ Failed to set {key}: {e}")


def cmd_book_config_clear(args):
    """Clear book configuration (revert to library defaults)."""
    storage_root = Config.book_storage_root
    scan_id = args.scan_id

    manager = BookConfigManager(storage_root, scan_id)

    # Check book exists
    if not manager.book_dir.exists():
        print(f"✗ Book not found: {scan_id}")
        return

    if not manager.exists():
        print(f"✓ Book '{scan_id}' has no overrides (already using library defaults)")
        return

    if not args.yes:
        print(f"This will remove all configuration overrides for '{scan_id}'.")
        print("The book will use library defaults.")
        response = input("Continue? [y/N] ")
        if response.lower() != 'y':
            print("Cancelled.")
            return

    manager.clear()
    print(f"✓ Cleared configuration for book '{scan_id}'")
    print("  Book will now use library defaults")


def _parse_value(value: str):
    """Parse a string value into appropriate Python type."""
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
