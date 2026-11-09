"""Command-line interface for printable travelers."""

import argparse
import sys
import tomllib
from pathlib import Path

from prechips.profiles import ProfileError, load_profile
from prechips.traveler import PlanError, load_plan, render_traveler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prechips")
    commands = parser.add_subparsers(dest="command", required=True)
    traveler = commands.add_parser(
        "traveler", help="render a TOML plan as printable HTML"
    )
    traveler.add_argument("plan", type=Path, metavar="PLAN.toml")
    traveler.add_argument("--out", type=Path, required=True, metavar="traveler.html")
    traveler.add_argument(
        "--profile",
        default="pro",
        metavar="pro|hobby|FILE.toml",
        help="rendering features and completeness requirements (default: pro)",
    )
    args = parser.parse_args(argv)
    try:
        if args.out.exists() and args.out.samefile(args.plan):
            raise PlanError("output must not overwrite the input plan")
        profile = load_profile(args.profile)
        plan = load_plan(args.plan)
        inputs = []
        if plan.cad is not None:
            inputs.append(plan.cad.source)
        if args.profile not in {"pro", "hobby"}:
            inputs.append(Path(args.profile))
        if "setup_diagrams" in profile.features:
            inputs.extend(
                args.plan.parent / setup["diagram"]["file"]
                for setup in plan.data["setups"]
                if "diagram" in setup
            )
        if args.out.exists() and any(args.out.samefile(path) for path in inputs):
            raise PlanError(
                "output must not overwrite an input CAD source, profile or diagram"
            )
        html = render_traveler(plan, profile=profile)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(html, encoding="utf-8")
    except (
        OSError,
        UnicodeError,
        tomllib.TOMLDecodeError,
        PlanError,
        ProfileError,
    ) as error:
        print(f"prechips: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {args.out}")
    return 0
