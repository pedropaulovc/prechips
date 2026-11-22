"""Command-line interface for printable travelers."""

import argparse
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

from prechips import checks
from prechips.profiles import ProfileError, load_profile
from prechips.stock import StockError, check_stock_fit
from prechips.traveler import PlanError, load_plan, render_traveler, used_diagrams
from prechips.turning import (
    DEFAULT_CONFIG,
    TurningError,
    check_turning_deflection,
    load_config,
)


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
            "override turning, milling, drilling and drill-pecking coefficients and limits "
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
        inputs.extend(cad.source for cad, _ in plan.parts.values())
        inputs.extend(plan.shop_files)
        # A new .toml beside a shop directory's files would join that shop.
        folder = args.out.resolve().parent
        if (
            plan.shop is not None
            and plan.shop.is_dir()
            and args.out.suffix.lower() == ".toml"
            and folder.exists()
            and folder.samefile(plan.shop)
        ):
            raise PlanError("output must not be a .toml file in the shop directory")
        if args.profile not in {"pro", "hobby"}:
            inputs.append(Path(args.profile))
        # Turning, milling and drill pecking read the same packaged/override file.
        readers = [
            name
            for name in ("turning_deflection", *checks.CHECKS)
            if name in profile.enforce
            and (
                name == "turning_deflection" or checks.CHECKS[name].config == "turning"
            )
        ]
        if readers:
            inputs.append(DEFAULT_CONFIG)
            if profile.turning_config is not None:
                inputs.append(profile.turning_config)
        inputs.extend(
            args.plan.parent / diagram["file"]
            for setup in plan.data["setups"]
            for diagram in used_diagrams(setup, profile).values()
        )
        # A missing input cannot be the output; the render names it instead.
        if args.out.exists() and any(
            path.exists() and args.out.samefile(path) for path in inputs
        ):
            raise PlanError(
                "output must not overwrite an input CAD source, profile, diagram, "
                "shop or turning config"
            )
        config = None
        if readers:
            try:
                config = load_config(profile.turning_config)
            except TurningError as error:
                opt_out = " ".join(f"--disable-check {name}" for name in readers)
                raise TurningError(
                    f"{', '.join(readers)}: {error}. Use {opt_out} or a custom "
                    "profile to opt out."
                ) from error
        if "turning_deflection" in profile.enforce:
            check_turning_deflection(plan, config)
        for name in checks.CHECKS:
            if name in profile.enforce:
                checks.run(name, plan, config)
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
