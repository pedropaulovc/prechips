"""Maintain and audit CI's duration-balanced test shards.

CI splits the suite with pytest-split over the committed ``.test_durations``.
Each shard uploads a JUnit report whose per-case ``time`` is the measured
setup + call + teardown.

``durations`` rebuilds ``.test_durations`` from the JUnit reports of one green
CI run (all shards), keyed by collected pytest node id:

    uv run scripts/ci_shards.py durations pytest-*-shard*/pytest.xml

``check`` asserts the shards' JUnit cases together are exactly the full
collection: no collected test is missing and none ran in two shards:

    uv run scripts/ci_shards.py check pytest-*-shard*/pytest.xml
"""

import argparse
import collections
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collected_nodeids():
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if "::" in line]


def junit_key(nodeid):
    path, *scopes = nodeid.split("::")
    module = path.removesuffix(".py").replace("/", ".")
    return ".".join([module, *scopes[:-1]]), scopes[-1]


def junit_cases(path):
    for case in ET.parse(path).getroot().iter("testcase"):
        yield (case.get("classname"), case.get("name")), float(case.get("time") or 0.0)


def durations(reports, output):
    times = {}
    for report in reports:
        for key, seconds in junit_cases(report):
            times[key] = times.get(key, 0.0) + seconds
    nodeids = collected_nodeids()
    keys = {nodeid: junit_key(nodeid) for nodeid in nodeids}
    timed = {nodeid: round(times[key], 3) for nodeid, key in keys.items() if key in times}
    output.write_text(json.dumps(timed, indent=0, sort_keys=True) + "\n", "utf-8")
    print(f"{len(timed)} of {len(nodeids)} collected tests timed")
    return 0


def check(reports):
    ran = collections.Counter()
    for report in reports:
        cases = [key for key, _ in junit_cases(report)]
        print(f"{report}: {len(cases)} tests")
        ran.update(cases)
    expected = collections.Counter(junit_key(nodeid) for nodeid in collected_nodeids())
    total = sum(ran.values())
    print(f"shards ran {total} tests; full collection is {sum(expected.values())}")
    duplicated = sorted(key for key, count in ran.items() if count > 1)
    missing = sorted((expected - ran).elements())
    extra = sorted(key for key in ran if key not in expected)
    problems = (("ran in two shards", duplicated), ("missing", missing), ("unexpected", extra))
    for label, keys in problems:
        for classname, name in keys[:20]:
            print(f"  {label}: {classname}::{name}")
    if duplicated or missing or extra:
        print(f"{len(duplicated)} duplicated, {len(missing)} missing, {len(extra)} unexpected")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    rebuild = commands.add_parser("durations", help="rebuild .test_durations from CI JUnit")
    rebuild.add_argument("junit", nargs="+", type=Path)
    rebuild.add_argument("--output", type=Path, default=ROOT / ".test_durations")
    audit = commands.add_parser("check", help="assert shards cover the full collection once")
    audit.add_argument("junit", nargs="+", type=Path)
    args = parser.parse_args()
    if args.command == "durations":
        return durations(args.junit, args.output)
    return check(args.junit)


if __name__ == "__main__":
    sys.exit(main())
