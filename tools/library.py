"""
Library-level tracking and management for book collection.

DEPRECATED: This module is deprecated. Use infra.storage.library_storage.LibraryStorage instead.

Maintained for backward compatibility only.
"""

# Re-export LibraryStorage as LibraryIndex for backward compatibility
from infra.storage.library_storage import LibraryStorage as LibraryIndex

# For convenience, also export as LibraryStorage
LibraryStorage = LibraryIndex

__all__ = ["LibraryIndex", "LibraryStorage"]
