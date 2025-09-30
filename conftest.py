"""
Pytest configuration for project root.

Ensures project modules can be imported in tests.
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
