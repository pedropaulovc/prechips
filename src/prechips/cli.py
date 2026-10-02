"""Command-line entry point. Subcommands land with the milestones in PLAN.md."""

from __future__ import annotations

import argparse
import sys

from prechips import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prechips", description="Checks before chips.")
    parser.add_argument("--version", action="version", version=f"prechips {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
