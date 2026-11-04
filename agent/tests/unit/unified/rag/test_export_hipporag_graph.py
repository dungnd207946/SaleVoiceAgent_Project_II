"""Tests for the GEXF/CSV exporter (pure builders — escaping + structure)."""

from __future__ import annotations

import csv
import importlib.util
import pathlib

# The exporter lives under scripts/ (not an importable package) — load by path.
_SPEC = importlib.util.spec_from_file_location(
    "export_hipporag_graph",
    pathlib.Path(__file__).resolve().parents[4] / "scripts" / "export_hipporag_graph.py",
)
export = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(export)


def _graph():
    return {
        "nodes": {
            "passage::p1": {"type": "passage", "label": "NCTH", "project": "NCTH", "text": "A & B <tag> \"q\""},
            "phrase::noble crystal": {"type": "phrase", "label": "Noble Crystal", "project": "", "text": ""},
            "phrase::tay ho": {"type": "phrase", "label": "Tây Hồ", "project": "", "text": ""},
        },
        "edges": [
            ["passage::p1", "phrase::noble crystal", 2.0],  # contains
            ["phrase::noble crystal", "phrase::tay ho", 1.0],  # relation "ở"
        ],
        "triples": [
            {"s": "phrase::noble crystal", "o": "phrase::tay ho", "rel": "ở", "text": "x", "passage": "p1"},
        ],
    }


def test_gexf_escapes_special_chars_and_has_structure():
    xml = export.build_gexf(_graph())
    assert xml.startswith("<?xml")
    assert "<gexf" in xml and "</gexf>" in xml
    # special characters in the passage text must be XML-escaped, never raw
    assert "A &amp; B &lt;tag&gt;" in xml
    assert "<tag>" not in xml
    # attributes present
    assert 'title="project"' in xml
    # phrase↔phrase edge carries the relation label; passage↔phrase edge → "contains"
    assert 'label="ở"' in xml
    assert 'label="contains"' in xml


def test_edge_csv_has_relation_column(tmp_path):
    p = tmp_path / "edges.csv"
    export.write_edge_csv(_graph(), str(p))
    with open(p, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    rels = {(r["source"], r["target"]): r["relation"] for r in rows}
    assert rels[("phrase::noble crystal", "phrase::tay ho")] == "ở"
    assert rels[("passage::p1", "phrase::noble crystal")] == "contains"


def test_node_csv(tmp_path):
    p = tmp_path / "nodes.csv"
    export.write_node_csv(_graph(), str(p))
    with open(p, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["id"] for r in rows} == {"passage::p1", "phrase::noble crystal", "phrase::tay ho"}
    p1 = next(r for r in rows if r["id"] == "passage::p1")
    assert p1["type"] == "passage" and p1["project"] == "NCTH" and p1["degree"] == "1"


def test_edge_csv(tmp_path):
    p = tmp_path / "edges.csv"
    export.write_edge_csv(_graph(), str(p))
    with open(p, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["source"] == "passage::p1" and rows[0]["weight"] == "2.0"
    assert set(rows[0].keys()) == {"source", "target", "weight", "relation"}
