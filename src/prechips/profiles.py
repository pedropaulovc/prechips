"""Small rendering profiles, independent of shop or geometry checks."""

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


PRO = Profile("pro", frozenset(), frozenset())
HOBBY = Profile("hobby", frozenset({"setup_diagrams"}), frozenset({"setup_diagrams"}))


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
    unknown = data.keys() - {"name", "features", "enforce"}
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
            raise ProfileError(f"profile.{key}: expected an array of feature names")
        unsupported = set(items) - {"setup_diagrams"}
        if unsupported:
            raise ProfileError(
                f"profile.{key}: unknown requirement(s): {', '.join(sorted(unsupported))}"
            )
        lists[key] = frozenset(items)
    if not lists["enforce"] <= lists["features"]:
        raise ProfileError(
            "profile.enforce: setup_diagrams must also be enabled in features"
        )
    return Profile(name, lists["features"], lists["enforce"])
