"""Fail release staging when its tag would disagree with runtime metadata."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def verify(root: Path, requested: str) -> str:
    version = requested.removeprefix("v")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise ValueError("Release version must be semantic, for example 1.0.43 or v1.0.43")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declared = project.get("project", {}).get("version")
    source = ast.parse((root / "modules/version.py").read_text(encoding="utf-8"))
    fallbacks = [node.value.value for node in source.body
                 if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "FALLBACK_VERSION" for target in node.targets)
                 and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    if declared != version or fallbacks != [version]:
        raise ValueError(f"Release version mismatch: requested={version}, pyproject={declared}, "
                         f"FALLBACK_VERSION={fallbacks}. Update both source versions before tagging.")
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    args = parser.parse_args(argv)
    try:
        version = verify(ROOT, args.version)
    except (OSError, ValueError, SyntaxError) as exc:
        print(f"Release version check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Release version verified: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
