"""Adoption inventory integrity is distinct from WSP conformance."""

import json
from pathlib import Path

import pytest

from tools.wsp_inventory import catalog, verify


ROOT = Path(__file__).resolve().parents[1]


def test_controlled_inventory_matches_pinned_wsp():
    verify(ROOT)


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "title", "source_sha256",
                                    "owner", "review_status", "schema"])
def test_missing_changed_or_false_coverage_fails(tmp_path, mutation):
    source = tmp_path / "wsp/requirements"
    source.mkdir(parents=True)
    (source / "requirements.md").write_text(
        "### WSP-TEST-0001 — Example\n\nThe project shall retain evidence.\n", encoding="utf-8")
    row = {"id": "WSP-TEST-0001", **catalog(tmp_path)["WSP-TEST-0001"],
           "review_status": "pending", "owner": "maintainer",
           "rationale": "review required", "completion_condition": "review evidence"}
    doc = {"schema": 1, "requirements": [row]}
    if mutation == "omit":
        doc["requirements"] = []
    elif mutation == "duplicate":
        doc["requirements"].append(row)
    elif mutation == "schema":
        doc["schema"] = 2
    else:
        row[mutation] = "satisfied" if mutation == "review_status" else ""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/wsp-inventory.json").write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError):
        verify(tmp_path)
