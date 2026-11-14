"""Command-line interface for printable travelers."""

import argparse
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

from prechips import checks
from prechips.profiles import ProfileError, load_profile
from prechips.stock import StockError, check_stock_fit
from prechips.traveler import PlanError, load_plan, render_traveler
from prechips.turning import DEFAULT_CONFIG, TurningError, check_turning_deflection


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
    traveler.add_argument(
        "--disable-check",
        action="append",
        default=[],
        choices=("setup_diagrams", "stock_fit", "turning_deflection", *checks.CHECKS),
        help="disable an enforced check (repeatable; no sheet warning)",
    )
    traveler.add_argument(
        "--turning-config",
        type=Path,
        metavar="FILE.toml",
        help=(
            "override turning, milling and drilling coefficients and limits "
            "(partial TOML config)"
        ),
    )
    args = parser.parse_args(argv)
    try:
        if args.out.exists() and args.out.samefile(args.plan):
            raise PlanError("output must not overwrite the input plan")
        profile = load_profile(args.profile)
        profile = replace(
            profile,
            enforce=profile.enforce - frozenset(args.disable_check),
            turning_config=args.turning_config or profile.turning_config,
        )
        plan = load_plan(args.plan)
        if "stock_fit" in profile.enforce:
            check_stock_fit(plan)
        inputs = []
        if plan.cad is not None:
            inputs.append(plan.cad.source)
        if plan.shop is not None:
            inputs.append(plan.shop)
        if args.profile not in {"pro", "hobby"}:
            inputs.append(Path(args.profile))
        # Turning and milling read the same packaged/override coefficient file.
        if "turning_deflection" in profile.enforce or any(
            checks.CHECKS[name].config == "turning"
            for name in profile.enforce & checks.CHECKS.keys()
        ):
            inputs.append(DEFAULT_CONFIG)
            if profile.turning_config is not None:
                inputs.append(profile.turning_config)
        if "setup_diagrams" in profile.features:
            inputs.extend(
                args.plan.parent / setup["diagram"]["file"]
                for setup in plan.data["setups"]
                if "diagram" in setup
            )
        if args.out.exists() and any(args.out.samefile(path) for path in inputs):
            raise PlanError(
                "output must not overwrite an input CAD source, profile, diagram, "
                "shop or turning config"
            )
        if "turning_deflection" in profile.enforce:
            check_turning_deflection(plan, config_path=profile.turning_config)
        for name in checks.CHECKS:
            if name in profile.enforce:
                checks.run(name, plan, profile.turning_config)
        html = render_traveler(plan, profile=profile)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(html, encoding="utf-8")
    except (
        OSError,
        UnicodeError,
        tomllib.TOMLDecodeError,
        PlanError,
        checks.CheckError,
        ProfileError,
        StockError,
        TurningError,
    ) as error:
        print(f"prechips: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {args.out}")
    return 0
