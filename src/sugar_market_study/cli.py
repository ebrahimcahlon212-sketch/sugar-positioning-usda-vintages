"""Command-line interface for the offline reproduction path."""

from __future__ import annotations

import argparse
from pathlib import Path

from sugar_market_study.pipeline import build_outputs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="repository root (default: current directory)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed derived artifacts instead of writing them",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    outputs = build_outputs(args.repo_root.resolve(), check=args.check)
    action = "verified" if args.check else "wrote"
    for output in outputs:
        print(f"{action}: {output}")
    return 0
