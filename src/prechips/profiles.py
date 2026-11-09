"""Small profiles selecting rendering features and explicit requirements."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ProfileError(ValueError):
    """A rendering profile is not supported or is inconsistent."""


@dataclass(frozen=True)
class Profile:
    name: str
    features: frozenset[str]
    enforce: frozenset[str]
    turning_config: Path | None = None


PRO = Profile("pro", frozenset(), frozenset({"stock_fit", "turning_deflection"}))
HOBBY = Profile(
    "hobby",
    frozenset({"setup_diagrams", "detailed_instructions"}),
    frozenset({"setup_diagrams", "stock_fit", "turning_deflection"}),
)


def load_profile(value: str) -> Profile:
    """Select a built-in preset or read an explicitly authored TOML profile."""
    if value == "pro":
        return PRO
    if value == "hobby":
        return HOBBY
    path = Path(value)
    try:
        with path.open("rb") as source:
            data = tomllib.load(source)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ProfileError(f"profile {value!r}: {error}") from error
    unknown = data.keys() - {"name", "features", "enforce", "turning_config"}
    if unknown:
        raise ProfileError(f"profile: unknown field(s): {', '.join(sorted(unknown))}")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProfileError("profile.name: expected a nonempty string")
    lists = {}
    for key in ("features", "enforce"):
        items = data.get(key)
        if not isinstance(items, list) or any(
            not isinstance(item, str) for item in items
        ):
            raise ProfileError(f"profile.{key}: expected an array of names")
        supported = (
            {"setup_diagrams", "stock_fit", "turning_deflection"}
            if key == "enforce"
            else {"setup_diagrams", "detailed_instructions"}
        )
        unsupported = set(items) - supported
        if unsupported:
            raise ProfileError(
                f"profile.{key}: unknown requirement(s): {', '.join(sorted(unsupported))}"
            )
        lists[key] = frozenset(items)
    if "setup_diagrams" in lists["enforce"] - lists["features"]:
        raise ProfileError(
            "profile.enforce: setup_diagrams must also be enabled in features"
        )
    turning_config = data.get("turning_config")
    if turning_config is not None:
        if not isinstance(turning_config, str) or not turning_config.strip():
            raise ProfileError("profile.turning_config: expected a nonempty path")
        turning_config = (path.parent / turning_config).resolve()
    return Profile(name, lists["features"], lists["enforce"], turning_config)
