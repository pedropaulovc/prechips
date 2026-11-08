"""Command-line interface for printable travelers."""

import argparse
import sys
import tomllib
from pathlib import Path

from prechips.traveler import PlanError, load_plan, render_traveler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prechips")
    commands = parser.add_subparsers(dest="command", required=True)
    traveler = commands.add_parser(
        "traveler", help="render a TOML plan as printable HTML"
    )
    traveler.add_argument("plan", type=Path, metavar="PLAN.toml")
    traveler.add_argument("--out", type=Path, required=True, metavar="traveler.html")
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.plan)
        html = render_traveler(plan)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(html, encoding="utf-8")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, PlanError) as error:
        print(f"prechips: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {args.out}")
    return 0
