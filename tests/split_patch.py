"""Patch or read a name across the files a module was split into.

Written by scripts/split_modules.py; re-running ``apply`` updates ``SPLITS``. Before a
split, one ``monkeypatch.setattr(module, name, value)`` replaced the only binding every
caller read. After it, the name is bound in each file that defines or imports it, so
``patch_split`` replaces it in all of them, which is the same patch.
"""

import importlib

SPLITS = {
    "prechips.rules.zero_recipe": (
        "prechips.rules.zero_recipe.rule",
        "prechips.rules.zero_recipe.touch",
        "prechips.rules.zero_recipe.native",
        "prechips.rules.zero_recipe.faces",
        "prechips.rules.zero_recipe.tool_setting",
    )
}


def _bindings(source, name):
    if name.startswith("__") and name.endswith("__"):
        # Every split file has its own __name__, __dict__…; none is the old module's.
        raise AttributeError(f"{name} of {source} has no single split-file binding")
    modules = [importlib.import_module(m) for m in SPLITS[source]]
    found = [m for m in modules if name in vars(m)]
    if not found:
        raise AttributeError(f"no file split from {source} binds {name!r}")
    return found


def patch_split(monkeypatch, source, name, value, raising=True):
    for module in _bindings(source, name):
        monkeypatch.setattr(module, name, value, raising=raising)


def split_attr(source, name):
    """``name`` from the file that defines it (an importer's binding is the same object)."""
    modules = _bindings(source, name)
    for module in modules:
        value = vars(module)[name]
        if getattr(value, "__module__", None) == module.__name__:
            return value
    return vars(modules[0])[name]
