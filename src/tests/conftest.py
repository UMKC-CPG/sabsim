"""Shared pytest fixtures and import-path setup.

The pipeline package ``sabsim`` lives under ``src/`` alongside this
tests tree, and the project runs from a source checkout rather than an
installed wheel, so we put ``src/`` on the import path here. That lets
every test simply ``import sabsim`` without repeating the path dance.
"""

import os
import sys

# This file is src/tests/conftest.py, so its parent's parent is src/,
# the directory that contains the importable ``sabsim`` package.
_SRC_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), ".."))

if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)
