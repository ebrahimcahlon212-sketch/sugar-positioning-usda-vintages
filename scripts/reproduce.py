"""Rebuild committed report-ready tables without network access."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sugar_market_study.pipeline import build_outputs  # noqa: E402

if __name__ == "__main__":
    for path in build_outputs(ROOT):
        print(path.relative_to(ROOT))
