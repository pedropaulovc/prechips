"""Frozen geometry bytes and bound digests survive a Git archive/checkout."""

import hashlib
import io
import json
import subprocess
import tarfile
import tomllib
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("source_distribution", [False, True], ids=["git-archive", "source"])
def test_frozen_geometry_bundle_preserves_binary_bytes(source_distribution):
    if not source_distribution:
        if not (ROOT / ".git").exists():
            pytest.skip("the Git archive route requires a checkout")
        result = subprocess.run(
            ["git", "archive", "--format=tar", "HEAD", "examples"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        )
        with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
            files = {
                member.name: archive.extractfile(member).read()
                for member in archive.getmembers()
                if member.isfile()
            }
    else:
        # Source distributions already contain the exported/checked-out bytes.
        files = {
            path.relative_to(ROOT).as_posix(): path.read_bytes()
            for path in (ROOT / "examples").rglob("*")
            if path.is_file()
        }
    pngs = []
    known_steps = []
    bound_reports = []
    for name, raw in files.items():
        if name.endswith(".png"):
            pngs.append(name)
            assert raw.startswith(b"\x89PNG\r\n\x1a\n"), name
        elif name.endswith("/features.toml"):
            manifest = tomllib.loads(raw.decode("utf-8"))
            step = manifest.get("step", "unknown")
            if step != "unknown":
                known_steps.append(name)
                path = str(PurePosixPath(name).parent / step)
                assert hashlib.sha256(files[path]).hexdigest() == manifest["step_sha256"], path
        elif name.endswith("/report.json"):
            report = json.loads(raw)
            if report.get("renders"):
                bound_reports.append(name)
            for render in report.get("renders", {}).values():
                path = str(PurePosixPath(name).parent / render["path"])
                assert hashlib.sha256(files[path]).hexdigest() == render["sha256"], path
    assert pngs, "the exported bundle must contain PNG assets"
    assert known_steps, "the exported bundle must contain manifests bound to known STEP bytes"
    assert bound_reports, "the exported bundle must contain reports bound to renders"
