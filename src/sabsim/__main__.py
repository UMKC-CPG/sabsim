"""Enable ``python -m sabsim ...`` (delegates to the CLI entry point).

This is the no-install invocation, working with ``PYTHONPATH=src`` on any
machine; ``pip install -e .`` additionally registers the bare ``sabsim``
console command (see :mod:`sabsim.cli`).
"""

import sys

from sabsim.cli import main

if __name__ == "__main__":
    sys.exit(main())
