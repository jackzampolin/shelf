"""
Config routes blueprint.

Settings UI for managing library configuration.
"""

import json
from flask import Blueprint, render_template, request, jsonify
from web.config import Config
from web.data.config_data import (
    get_library_config_for_display,
    get_api_key_names,
    validate_config_section,
    get_config_preview,
    apply_config_update,
    mask_api_key,
)

config_bp = Blueprint('config', __name__, url_prefix='/settings')


@config_bp.route('/')
def settings_index():
    """
    Main settings page.

    Shows all config sections with current values.
    """
    config_data = get_library_config_for_display(Config.BOOK_STORAGE_ROOT)

    return render_template(
        'settings/index.html',
        config=config_data,
        active='settings',
    )


@config_bp.route('/api/<section>')
def get_section(section: str):
    """
    Get editable form for a config section (HTMX partial).
    """
    config_data = get_library_config_for_display(Config.BOOK_STORAGE_ROOT)
    api_key_names = get_api_key_names(Config.BOOK_STORAGE_ROOT)

    template_map = {
        'api-keys': 'settings/sections/api_keys.html',
        'ocr-providers': 'settings/sections/ocr_providers.html',
        'llm-providers': 'settings/sections/llm_providers.html',
        'defaults': 'settings/sections/defaults.html',
    }

    template = template_map.get(section)
    if not template:
        return f"Unknown section: {section}", 404

    return render_template(
        template,
        config=config_data,
        api_key_names=api_key_names,
        section=section,
    )


@config_bp.route('/api/validate', methods=['POST'])
def validate_changes():
    """
    Validate config changes and return preview (HTMX).
    """
    section = request.form.get('section')
    if not section:
        return render_template(
            'settings/components/validation_error.html',
            errors=['Missing section parameter']
        )

    # Parse form data into section-specific structure
    data = _parse_form_data(request.form, section)

    # Validate
    is_valid, validated, errors = validate_config_section(section, data)

    if not is_valid:
        return render_template(
            'settings/components/validation_error.html',
            errors=errors
        )

    # Generate preview
    preview = get_config_preview(Config.BOOK_STORAGE_ROOT, section, validated)

    return render_template(
        'settings/components/preview_modal.html',
        changes=preview['changes'],
        has_changes=preview['has_changes'],
        section=section,
        pending_data=json.dumps(validated),
    )


@config_bp.route('/api/save', methods=['POST'])
def save_changes():
    """
    Save validated config changes (HTMX).
    """
    section = request.form.get('section')
    data_json = request.form.get('data')

    if not section or not data_json:
        return render_template(
            'settings/components/validation_error.html',
            errors=['Missing section or data']
        )

    try:
        data = json.loads(data_json)
    except json.JSONDecodeError:
        return render_template(
            'settings/components/validation_error.html',
            errors=['Invalid JSON data']
        )

    # Re-validate before saving
    is_valid, validated, errors = validate_config_section(section, data)

    if not is_valid:
        return render_template(
            'settings/components/validation_error.html',
            errors=errors
        )

    # Apply update
    try:
        apply_config_update(Config.BOOK_STORAGE_ROOT, section, validated)
    except Exception as e:
        return render_template(
            'settings/components/validation_error.html',
            errors=[f'Save failed: {str(e)}']
        )

    return render_template(
        'settings/components/save_success.html',
        section=section,
    )


def _parse_form_data(form, section: str) -> dict:
    """
    Parse flat form data into nested structure for section.

    Form fields are named like:
    - api_keys.openrouter
    - ocr_providers.mistral.type
    - defaults.max_workers
    """
    if section == 'api-keys':
        # api_keys.{name} = value
        data = {}
        for key, value in form.items():
            if key.startswith('api_keys.'):
                key_name = key.replace('api_keys.', '')
                if value:  # Only include non-empty values
                    data[key_name] = value
        # Handle new key if provided
        new_name = form.get('new_key_name', '').strip()
        new_value = form.get('new_key_value', '').strip()
        if new_name and new_value:
            data[new_name] = new_value
        return data

    elif section == 'ocr-providers':
        # ocr_providers.{name}.{field} = value
        data = {}
        for key, value in form.items():
            if key.startswith('ocr_providers.'):
                parts = key.replace('ocr_providers.', '').split('.', 1)
                if len(parts) == 2:
                    name, field = parts
                    if name not in data:
                        data[name] = {}
                    # Type conversions
                    if field == 'enabled':
                        value = value.lower() in ('true', 'on', '1', 'yes')
                    elif field == 'rate_limit' and value:
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                    if value or field == 'enabled':  # Keep enabled even if False
                        data[name][field] = value
        return data

    elif section == 'llm-providers':
        # llm_providers.{name}.{field} = value
        data = {}
        for key, value in form.items():
            if key.startswith('llm_providers.'):
                parts = key.replace('llm_providers.', '').split('.', 1)
                if len(parts) == 2:
                    name, field = parts
                    if name not in data:
                        data[name] = {}
                    # Type conversions
                    if field == 'rate_limit' and value:
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                    if value:
                        data[name][field] = value
        return data

    elif section == 'defaults':
        # defaults.{field} = value
        data = {}
        # Handle ocr_providers as list (multiple checkboxes)
        ocr_providers = form.getlist('defaults.ocr_providers')
        if ocr_providers:
            data['ocr_providers'] = ocr_providers

        # Single values
        if form.get('defaults.llm_provider'):
            data['llm_provider'] = form.get('defaults.llm_provider')
        if form.get('defaults.max_workers'):
            try:
                data['max_workers'] = int(form.get('defaults.max_workers'))
            except ValueError:
                data['max_workers'] = 10
        return data

    return {}
