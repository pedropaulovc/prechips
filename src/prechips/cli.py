"""Command-line interface for printable travelers."""

import argparse
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

from prechips import checks
from prechips.profiles import ProfileError, load_profile
from prechips.stock import StockError, check_stock_fit
from prechips.traveler import (
    PlanError,
    load_plan,
    load_standing,
    render_placeholder,
    render_standing,
    render_traveler,
    used_diagrams,
)
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
    traveler.add_argument(
        "--placeholder",
        metavar="PART",
        help=(
            "render one part of a family plan's placeholder sheet, which "
            "points to the shared traveler, in place of the traveler"
        ),
    )
    traveler.add_argument(
        "--shared-file",
        metavar="NAME",
        help="with --placeholder: the shared traveler's file name, printed on it",
    )
    standing = commands.add_parser(
        "standing",
        help="render a shop's [standing] instructions page as printable HTML",
    )
    standing.add_argument("shop", type=Path, metavar="SHOP")
    standing.add_argument("--out", type=Path, required=True, metavar="page.html")
    args = parser.parse_args(argv)
    if args.command == "standing":
        return _standing(args.shop, args.out)
    try:
        if args.shared_file is not None and args.placeholder is None:
            raise PlanError("--shared-file: requires --placeholder")
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
        # A placeholder passes every check of the traveler it points to,
        # the rendering's own (its pictures) included.
        html = render_traveler(plan, profile=profile)
        if args.placeholder is not None:
            html = render_placeholder(
                plan, args.placeholder, shared_file=args.shared_file
            )
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


def _standing(shop: Path, out: Path) -> int:
    try:
        page, files = load_standing(shop)
        # The same guards as `prechips traveler`: never overwrite a shop file,
        # and no new .toml that would join the shop directory.
        if out.exists() and any(path.exists() and out.samefile(path) for path in files):
            raise PlanError("output must not overwrite a shop file")
        folder = out.resolve().parent
        if (
            shop.is_dir()
            and out.suffix.lower() == ".toml"
            and folder.exists()
            and folder.samefile(shop)
        ):
            raise PlanError("output must not be a .toml file in the shop directory")
        html = render_standing(page)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, PlanError) as error:
        print(f"prechips: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {out}")
    return 0
