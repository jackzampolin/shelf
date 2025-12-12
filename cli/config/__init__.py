"""
Config CLI commands.

Commands for managing library and book configuration.
"""

from cli.config.init import cmd_init
from cli.config.show import cmd_config_show
from cli.config.set import cmd_config_set
from cli.config.provider import cmd_provider_add, cmd_provider_list


def setup_parser(subparsers):
    """Setup config command parser."""
    # shelf init
    init_parser = subparsers.add_parser(
        'init',
        help='Initialize library configuration'
    )
    init_parser.add_argument(
        '--migrate',
        action='store_true',
        help='Migrate existing .env values to config.yaml'
    )
    init_parser.add_argument(
        '--force',
        action='store_true',
        help='Overwrite existing config'
    )
    init_parser.set_defaults(func=cmd_init)

    # shelf config ...
    config_parser = subparsers.add_parser(
        'config',
        help='Manage library configuration'
    )
    config_subparsers = config_parser.add_subparsers(
        dest='config_command',
        help='Config command'
    )
    config_subparsers.required = True

    # shelf config show
    show_parser = config_subparsers.add_parser(
        'show',
        help='Show library configuration'
    )
    show_parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )
    show_parser.add_argument(
        '--reveal-keys',
        action='store_true',
        help='Show API key values (default: hidden)'
    )
    show_parser.set_defaults(func=cmd_config_show)

    # shelf config set <key> <value>
    set_parser = config_subparsers.add_parser(
        'set',
        help='Set a configuration value'
    )
    set_parser.add_argument(
        'key',
        help='Config key (e.g., defaults.max_workers, api_keys.openrouter)'
    )
    set_parser.add_argument(
        'value',
        help='Value to set'
    )
    set_parser.set_defaults(func=cmd_config_set)

    # shelf config provider ...
    provider_parser = config_subparsers.add_parser(
        'provider',
        help='Manage OCR providers'
    )
    provider_subparsers = provider_parser.add_subparsers(
        dest='provider_command',
        help='Provider command'
    )
    provider_subparsers.required = True

    # shelf config provider list
    provider_list_parser = provider_subparsers.add_parser(
        'list',
        help='List configured providers'
    )
    provider_list_parser.set_defaults(func=cmd_provider_list)

    # shelf config provider add <name> --type <type> [--model <model>] [--rate-limit <n>]
    provider_add_parser = provider_subparsers.add_parser(
        'add',
        help='Add or update a provider'
    )
    provider_add_parser.add_argument(
        'name',
        help='Provider name (e.g., qwen-vl, my-claude)'
    )
    provider_add_parser.add_argument(
        '--llm',
        action='store_true',
        help='Add as LLM provider (default: OCR provider)'
    )
    provider_add_parser.add_argument(
        '--type',
        required=True,
        help='Provider type (OCR: mistral-ocr, deepinfra; LLM: openrouter, anthropic, ollama)'
    )
    provider_add_parser.add_argument(
        '--model',
        help='Model identifier (required for LLM, optional for OCR)'
    )
    provider_add_parser.add_argument(
        '--rate-limit',
        type=float,
        help='Rate limit (requests per second)'
    )
    provider_add_parser.add_argument(
        '--disabled',
        action='store_true',
        help='Add OCR provider in disabled state'
    )
    provider_add_parser.set_defaults(func=cmd_provider_add)


__all__ = [
    'setup_parser',
    'cmd_init',
    'cmd_config_show',
    'cmd_config_set',
    'cmd_provider_add',
    'cmd_provider_list',
]
