"""
Web application configuration.

Mirrors infra.config.Config for the web frontend.
"""

import os
from pathlib import Path


class Config:
    """Web app configuration."""

    BOOK_STORAGE_ROOT = Path(
        os.getenv("BOOK_STORAGE_ROOT", "~/Documents/shelf")
    ).expanduser()

    HOST = os.getenv("WEB_HOST", "127.0.0.1")
    PORT = int(os.getenv("WEB_PORT", "1337"))
    DEBUG = os.getenv("WEB_DEBUG", "true").lower() == "true"
