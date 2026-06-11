#!/usr/bin/env python3
"""Migrate ``state.db`` only — delegates to ``migrate_hermes_to_postgres.py --only state``."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    script = Path(__file__).resolve().parent / "migrate_hermes_to_postgres.py"
    sys.argv = [str(script), "--only", "state", *sys.argv[1:]]
    runpy.run_path(str(script), run_name="__main__")
