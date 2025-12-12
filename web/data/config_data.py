"""
Config data access functions for settings UI.

Ground truth from disk (ADR 001).
"""

from typing import Dict, Any, List, Tuple, Optional
from pathlib import Path
from copy import deepcopy

from infra.config import LibraryConfigManager, LibraryConfig
from infra.config.schemas import OCRProviderConfig, LLMProviderConfig, DefaultsConfig
from pydantic import ValidationError


def mask_api_key(value: str) -> str:
    """
    Mask an API key for display.

    Reuses pattern from cli/config/show.py:_mask_key()
    """
    if not value:
        return "(not set)"
    # Check if it's an env var reference
    if value.startswith("${") and value.endswith("}"):
        return value  # Show env var syntax as-is
    if len(value) <= 8:
        return "****"
    return value[:4] + "..." + value[-4:]


def get_library_config_for_display(storage_root: Path) -> Dict[str, Any]:
    """
    Load library config and prepare for display.

    Returns dict with:
    - config_path: str
    - api_keys: dict with masked values
    - api_keys_raw: dict with original values (for form hidden fields)
    - ocr_providers: dict
    - llm_providers: dict
    - defaults: dict
    """
    manager = LibraryConfigManager(storage_root)

    if not manager.exists():
        return {
            'config_path': str(manager.config_path),
            'exists': False,
            'api_keys': {},
            'api_keys_raw': {},
            'ocr_providers': {},
            'llm_providers': {},
            'defaults': {
                'ocr_providers': [],
                'llm_provider': '',
                'max_workers': 10,
            },
        }

    config = manager.load()

    # Mask API keys for display
    masked_keys = {}
    for key_name, value in config.api_keys.items():
        resolved = config.resolve_api_key(key_name)
        masked_keys[key_name] = mask_api_key(resolved) if resolved else "(not set)"

    # Convert providers to dicts
    ocr_providers = {}
    for name, provider in config.ocr_providers.items():
        ocr_providers[name] = provider.model_dump()

    llm_providers = {}
    for name, provider in config.llm_providers.items():
        llm_providers[name] = provider.model_dump()

    return {
        'config_path': str(manager.config_path),
        'exists': True,
        'api_keys': masked_keys,
        'api_keys_raw': dict(config.api_keys),
        'ocr_providers': ocr_providers,
        'llm_providers': llm_providers,
        'defaults': config.defaults.model_dump(),
    }


def get_api_key_names(storage_root: Path) -> List[str]:
    """Get list of API key names for dropdowns."""
    manager = LibraryConfigManager(storage_root)
    if not manager.exists():
        return []
    config = manager.load()
    return list(config.api_keys.keys())


def validate_api_keys(data: Dict[str, str]) -> Tuple[bool, Dict[str, str], List[str]]:
    """
    Validate API keys section update.

    Returns: (is_valid, validated_data, error_messages)
    """
    errors = []
    validated = {}

    for key_name, value in data.items():
        if not key_name:
            continue
        # Allow empty values (to remove keys)
        # Allow env var syntax ${VAR}
        validated[key_name] = value

    return len(errors) == 0, validated, errors


def validate_ocr_providers(data: Dict[str, Dict]) -> Tuple[bool, Dict, List[str]]:
    """
    Validate OCR providers section update.

    Returns: (is_valid, validated_data, error_messages)
    """
    errors = []
    validated = {}

    for name, provider_data in data.items():
        if not name:
            continue
        try:
            provider = OCRProviderConfig(**provider_data)
            validated[name] = provider.model_dump(exclude_none=True)
        except ValidationError as e:
            for err in e.errors():
                field = '.'.join(str(x) for x in err['loc'])
                errors.append(f"{name}.{field}: {err['msg']}")

    return len(errors) == 0, validated, errors


def validate_llm_providers(data: Dict[str, Dict]) -> Tuple[bool, Dict, List[str]]:
    """
    Validate LLM providers section update.

    Returns: (is_valid, validated_data, error_messages)
    """
    errors = []
    validated = {}

    for name, provider_data in data.items():
        if not name:
            continue
        try:
            provider = LLMProviderConfig(**provider_data)
            validated[name] = provider.model_dump(exclude_none=True)
        except ValidationError as e:
            for err in e.errors():
                field = '.'.join(str(x) for x in err['loc'])
                errors.append(f"{name}.{field}: {err['msg']}")

    return len(errors) == 0, validated, errors


def validate_defaults(data: Dict) -> Tuple[bool, Dict, List[str]]:
    """
    Validate defaults section update.

    Returns: (is_valid, validated_data, error_messages)
    """
    errors = []

    try:
        defaults = DefaultsConfig(**data)
        validated = defaults.model_dump()
    except ValidationError as e:
        validated = data
        for err in e.errors():
            field = '.'.join(str(x) for x in err['loc'])
            errors.append(f"{field}: {err['msg']}")

    return len(errors) == 0, validated, errors


def validate_config_section(section: str, data: Dict) -> Tuple[bool, Dict, List[str]]:
    """
    Validate a config section update using Pydantic.

    Returns: (is_valid, validated_data, error_messages)
    """
    validators = {
        'api_keys': validate_api_keys,
        'ocr_providers': validate_ocr_providers,
        'llm_providers': validate_llm_providers,
        'defaults': validate_defaults,
    }

    validator = validators.get(section)
    if not validator:
        return False, data, [f"Unknown section: {section}"]

    return validator(data)


def get_config_preview(
    storage_root: Path,
    section: str,
    updates: Dict
) -> Dict[str, Any]:
    """
    Generate preview of what config will look like after update.

    Returns dict with:
    - changes: list of {field, old, new} dicts
    - has_changes: bool
    """
    manager = LibraryConfigManager(storage_root)
    current = manager.load() if manager.exists() else LibraryConfig.with_defaults()

    changes = []

    if section == 'api_keys':
        current_keys = dict(current.api_keys)
        for key_name, new_value in updates.items():
            old_value = current_keys.get(key_name, '')
            if old_value != new_value:
                changes.append({
                    'field': f'api_keys.{key_name}',
                    'old': mask_api_key(old_value) if old_value else '(not set)',
                    'new': mask_api_key(new_value) if new_value else '(removed)',
                })
        # Check for removed keys
        for key_name in current_keys:
            if key_name not in updates:
                changes.append({
                    'field': f'api_keys.{key_name}',
                    'old': mask_api_key(current_keys[key_name]),
                    'new': '(removed)',
                })

    elif section == 'ocr_providers':
        current_providers = {k: v.model_dump() for k, v in current.ocr_providers.items()}
        for name, new_data in updates.items():
            old_data = current_providers.get(name, {})
            if old_data != new_data:
                # Summarize the change
                if not old_data:
                    changes.append({
                        'field': f'ocr_providers.{name}',
                        'old': '(new)',
                        'new': f"type={new_data.get('type')}, enabled={new_data.get('enabled', True)}",
                    })
                else:
                    for field in set(list(old_data.keys()) + list(new_data.keys())):
                        if old_data.get(field) != new_data.get(field):
                            changes.append({
                                'field': f'ocr_providers.{name}.{field}',
                                'old': str(old_data.get(field, '(not set)')),
                                'new': str(new_data.get(field, '(removed)')),
                            })
        # Check for removed providers
        for name in current_providers:
            if name not in updates:
                changes.append({
                    'field': f'ocr_providers.{name}',
                    'old': f"type={current_providers[name].get('type')}",
                    'new': '(removed)',
                })

    elif section == 'llm_providers':
        current_providers = {k: v.model_dump() for k, v in current.llm_providers.items()}
        for name, new_data in updates.items():
            old_data = current_providers.get(name, {})
            if old_data != new_data:
                if not old_data:
                    changes.append({
                        'field': f'llm_providers.{name}',
                        'old': '(new)',
                        'new': f"model={new_data.get('model')}",
                    })
                else:
                    for field in set(list(old_data.keys()) + list(new_data.keys())):
                        if old_data.get(field) != new_data.get(field):
                            changes.append({
                                'field': f'llm_providers.{name}.{field}',
                                'old': str(old_data.get(field, '(not set)')),
                                'new': str(new_data.get(field, '(removed)')),
                            })
        for name in current_providers:
            if name not in updates:
                changes.append({
                    'field': f'llm_providers.{name}',
                    'old': f"model={current_providers[name].get('model')}",
                    'new': '(removed)',
                })

    elif section == 'defaults':
        current_defaults = current.defaults.model_dump()
        for field, new_value in updates.items():
            old_value = current_defaults.get(field)
            if old_value != new_value:
                # Format lists nicely
                if isinstance(old_value, list):
                    old_value = ', '.join(old_value) if old_value else '(none)'
                if isinstance(new_value, list):
                    new_value = ', '.join(new_value) if new_value else '(none)'
                changes.append({
                    'field': f'defaults.{field}',
                    'old': str(old_value),
                    'new': str(new_value),
                })

    return {
        'changes': changes,
        'has_changes': len(changes) > 0,
    }


def apply_config_update(
    storage_root: Path,
    section: str,
    data: Dict
) -> LibraryConfig:
    """
    Apply validated update to config and save.

    Uses LibraryConfigManager.update() for deep merge.

    Returns: Updated LibraryConfig
    """
    manager = LibraryConfigManager(storage_root)

    # Build the update dict
    update = {section: data}

    # Apply update
    manager.update(update)

    return manager.load()
