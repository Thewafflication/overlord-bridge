"""Verify WSP baseline and complete numbered requirement review coverage.

This checks inventory integrity, never conformance or approval of dispositions.
"""

import hashlib
import json
import re
import subprocess
from pathlib import Path


HEADING = re.compile(r"^#{2,4} (WSP-[A-Z]+-\d{4})[^\w\n]+([^\n]+)", re.M)


def catalog(root: Path) -> dict:
    entries = {}
    for path in sorted((root / "wsp").rglob("*.md")):
        relative = path.relative_to(root)
        if (any(part in ("templates", "examples") for part in relative.parts)
                or "template" in path.name or path.name == "README.md"):
            continue
        source = path.read_text(encoding="utf-8")
        for identifier, title in HEADING.findall(source):
            if identifier in entries:
                raise ValueError(f"Duplicate WSP identifier: {identifier}")
            entries[identifier] = {
                "title": title.strip(), "source": relative.as_posix(),
                "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            }
    if not entries:
        raise ValueError("WSP baseline is missing or has no requirements")
    return entries


def verify(root: Path) -> None:
    document = json.loads((root / "docs/wsp-inventory.json").read_text(encoding="utf-8"))
    if document.get("schema") != 1:
        raise ValueError("Unsupported WSP inventory schema")
    actual = catalog(root)
    rows = document["requirements"]
    controlled = {row["id"]: row for row in rows}
    if len(controlled) != len(rows) or set(controlled) != set(actual):
        raise ValueError("WSP requirement inventory is incomplete or duplicated")
    for identifier, expected in actual.items():
        row = controlled[identifier]
        for field, value in expected.items():
            if row.get(field) != value:
                raise ValueError(f"Changed WSP requirement source: {identifier}")
        if row.get("review_status") != "pending":
            raise ValueError(f"Unsupported review status: {identifier}; review schema must be revised")
        for field in ("owner", "completion_condition", "rationale"):
            if not row.get(field):
                raise ValueError(f"Missing {field}: {identifier}")
    revision = subprocess.run(["git", "-C", str(root / "wsp"), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()
    if revision != document["pinned_commit"]:
        raise ValueError("WSP checkout does not match the controlled baseline")
    gitlink = subprocess.run(["git", "-C", str(root), "ls-files", "--stage", "wsp"],
                             check=True, capture_output=True, text=True).stdout.split()
    if len(gitlink) != 4 or gitlink[0] != "160000" or gitlink[1] != revision:
        raise ValueError("WSP gitlink does not match the controlled baseline")


if __name__ == "__main__":
    verify(Path(__file__).resolve().parents[1])
