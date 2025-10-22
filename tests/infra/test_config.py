"""Tests for infra/config.py"""

import pytest
from pathlib import Path
from infra.config import Config


def test_config_validation_with_valid_setup(tmp_path, monkeypatch):
    """Test that validation passes with API key and existing storage."""
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setenv('BOOK_STORAGE_ROOT', str(tmp_path))

    from importlib import reload
    import infra.config
    reload(infra.config)

    is_valid, errors = infra.config.Config.validate()
    assert is_valid
    assert len(errors) == 0


def test_config_validation_catches_missing_requirements(monkeypatch):
    """Test that validation catches missing API key and nonexistent storage."""
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('OPEN_ROUTER_API_KEY', raising=False)
    monkeypatch.setenv('BOOK_STORAGE_ROOT', '/nonexistent/path')

    from importlib import reload
    import infra.config
    reload(infra.config)

    is_valid, errors = infra.config.Config.validate()
    assert not is_valid
    assert len(errors) > 0
