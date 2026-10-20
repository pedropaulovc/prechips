"""Content-only recipe shared by native proof bindings and the host geometry cache."""


def _cache_recipe(job):
    """The job as the cache keys it: content digests, never absolute file paths."""

    def bare(spec):
        if isinstance(spec, dict) and spec.get("shape") == "profiled":
            return {key: value for key, value in spec.items() if key != "step_path"}
        return spec

    recipe = {name: value for name, value in job.items() if name != "step_path"}
    stock = recipe["stock"]
    components = stock.get("components") if isinstance(stock, dict) else None
    if isinstance(components, dict):
        recipe["stock"] = {
            **stock,
            "components": {name: bare(spec) for name, spec in components.items()},
        }
        return recipe
    recipe["stock"] = bare(stock)
    return recipe
