"""Canonical local and CI checks; no provider turns are started."""

from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def lint() -> int:
    """Validate owned Python syntax without scanning runtime directories."""
    files = [ROOT / "bridge.py"]
    for folder in ("modules", "tests", "tools", "plugins/overlord/scripts"):
        files.extend((ROOT / folder).rglob("*.py"))
    failed = False
    for path in sorted(files):
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            print(f"{path}: {exc}", file=sys.stderr)
            failed = True
    if failed:
        return 1
    return subprocess.run(
        [sys.executable, str(ROOT / "tools/wsp_inventory.py")],
        cwd=ROOT, check=False,
    ).returncode


def run(stage: str) -> int:
    """Propagate failures, including missing required dependencies."""
    if stage == "lint":
        return lint()
    if stage == "build":
        # setuptools reuses build/lib and can silently package modules removed
        # by a branch switch. Clear only this generated staging directory.
        staging = ROOT / "build" / "lib"
        if staging.exists():
            if staging.resolve() != ROOT.resolve() / "build" / "lib":
                raise RuntimeError("Build staging directory resolves outside its expected workspace path")
            shutil.rmtree(staging)
        command = [
            sys.executable, "-m", "build", "--wheel", "--no-isolation",
            "--outdir", str(ROOT / "out/checks/wheels"),
        ]
    else:
        output = ROOT / "out/checks"
        output.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, "-m", "pytest", "tests", "-q",
            "-m", "not live", f"--junitxml={output / 'tests.xml'}",
        ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["lint", "build", "test", "all"])
    args = parser.parse_args()
    stages = ("lint", "build", "test") if args.stage == "all" else (args.stage,)
    for stage in stages:
        result = run(stage)
        if result:
            return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
