#!/usr/bin/env python3
"""Run the test suite via pytest."""

import os
import sys
import pytest

if __name__ == '__main__':
    sys.exit(pytest.main([
        os.path.dirname(__file__),
        '-v'] + sys.argv[1:]))
