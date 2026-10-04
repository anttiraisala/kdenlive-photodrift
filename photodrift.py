#!/usr/bin/env python3
"""PhotoDrift command line entry point. Run with --help for options."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from photodrift.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
