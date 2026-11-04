#!/usr/bin/env python3
"""Export the HippoRAG graph.json to standard formats for off-the-shelf viewers.

Emits:
  - graph.gexf        → open in Gephi / Gephi Lite / Cytoscape / yEd
  - graph_nodes.csv   → node metadata (id, label, type, project, degree)
  - graph_edges.csv   → edge list (source, target, weight)  → drag into cosmograph.app

Node attributes (type / project / degree / text) are carried into the GEXF so
Gephi can colour by `project`, size by `degree`, and filter phrase↔passage
without any extra setup.

Usage:
    python scripts/export_hipporag_graph.py                      # uses settings.hipporag_graph_path
    python scripts/export_hipporag_graph.py --graph path/to/graph.json --out-dir /tmp/viz
    python scripts/export_hipporag_graph.py --emit gexf          # gexf | csv | both (default both)

This is a read-only dev/ops helper — it never mutates the graph.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from xml.sax.saxutils import escape, quoteattr

_TEXT_CAP = 240  # truncate passage text in the GEXF attribute so files stay small


def _degrees(nodes: dict, edges: list) -> dict[str, int]:
    deg = dict.fromkeys(nodes, 0)
    for e in edges:
        if len(e) < 2:
            continue
        a, b = e[0], e[1]
        if a in deg:
            deg[a] += 1
        if b in deg:
            deg[b] += 1
    return deg


def _relation_map(graph: dict) -> dict[tuple[str, str], str]:
    """Undirected phrase-pair → relation label(s) from the ``triples`` list.
    Multiple relations between the same pair are joined with ' | '."""
    rels: dict[tuple[str, str], list[str]] = {}
    for t in graph.get("triples", []):
        a, b = t.get("s"), t.get("o")
        rel = (t.get("rel") or "").strip()
        if not a or not b or not rel:
            continue
        pair = (a, b) if a < b else (b, a)
        bucket = rels.setdefault(pair, [])
        if rel not in bucket:
            bucket.append(rel)
    return {pair: " | ".join(v) for pair, v in rels.items()}


def _edge_label(src: str, tgt: str, nodes: dict, relmap: dict[tuple[str, str], str]) -> str:
    """Relation text for a phrase↔phrase edge; 'contains' for a passage↔phrase edge."""
    pair = (src, tgt) if src < tgt else (tgt, src)
    if pair in relmap:
        return relmap[pair]
    types = {nodes.get(src, {}).get("type"), nodes.get(tgt, {}).get("type")}
    return "contains" if "passage" in types else ""


def build_gexf(graph: dict) -> str:
    """Render the graph dict (nodes/edges) as a GEXF 1.2 document string."""
    nodes: dict = graph.get("nodes", {})
    edges: list = graph.get("edges", [])
    deg = _degrees(nodes, edges)
    relmap = _relation_map(graph)

    out: list[str] = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append('<gexf xmlns="http://www.gexf.net/1.2draft" version="1.2">')
    out.append('  <meta><creator>noble_agent</creator><description>HippoRAG knowledge graph</description></meta>')
    out.append('  <graph mode="static" defaultedgetype="undirected">')
    out.append('    <attributes class="node">')
    out.append('      <attribute id="0" title="type" type="string"/>')
    out.append('      <attribute id="1" title="project" type="string"/>')
    out.append('      <attribute id="2" title="degree" type="integer"/>')
    out.append('      <attribute id="3" title="text" type="string"/>')
    out.append("    </attributes>")

    out.append("    <nodes>")
    for key, node in nodes.items():
        label = node.get("label") or key
        ntype = node.get("type", "")
        project = node.get("project", "") or ""
        text = (node.get("text", "") or "")[:_TEXT_CAP]
        out.append(f"      <node id={quoteattr(key)} label={quoteattr(label)}>")
        out.append("        <attvalues>")
        out.append(f'          <attvalue for="0" value={quoteattr(ntype)}/>')
        out.append(f'          <attvalue for="1" value={quoteattr(project)}/>')
        out.append(f'          <attvalue for="2" value="{deg.get(key, 0)}"/>')
        out.append(f'          <attvalue for="3" value={quoteattr(text)}/>')
        out.append("        </attvalues>")
        out.append("      </node>")
    out.append("    </nodes>")

    out.append("    <edges>")
    for i, e in enumerate(edges):
        if len(e) < 2:
            continue
        src, tgt = e[0], e[1]
        weight = float(e[2]) if len(e) > 2 else 1.0
        label = _edge_label(src, tgt, nodes, relmap)
        out.append(
            f'      <edge id="{i}" source={quoteattr(src)} target={quoteattr(tgt)} '
            f"weight=\"{weight}\" label={quoteattr(label)}/>"
        )
    out.append("    </edges>")

    out.append("  </graph>")
    out.append("</gexf>")
    return "\n".join(out) + "\n"


def write_node_csv(graph: dict, path: str) -> None:
    nodes: dict = graph.get("nodes", {})
    deg = _degrees(nodes, graph.get("edges", []))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "label", "type", "project", "degree"])
        for key, node in nodes.items():
            w.writerow(
                [key, node.get("label") or key, node.get("type", ""), node.get("project", "") or "", deg.get(key, 0)]
            )


def write_edge_csv(graph: dict, path: str) -> None:
    nodes: dict = graph.get("nodes", {})
    relmap = _relation_map(graph)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "target", "weight", "relation"])
        for e in graph.get("edges", []):
            if len(e) < 2:
                continue
            w.writerow(
                [e[0], e[1], float(e[2]) if len(e) > 2 else 1.0, _edge_label(e[0], e[1], nodes, relmap)]
            )


def _stats(graph: dict) -> str:
    nodes = graph.get("nodes", {})
    passages = sum(1 for v in nodes.values() if v.get("type") == "passage")
    phrases = sum(1 for v in nodes.values() if v.get("type") == "phrase")
    projects = len({v.get("project", "") for v in nodes.values() if v.get("type") == "passage"})
    n_edges = len(graph.get("edges", []))
    return f"{len(nodes)} nodes ({passages} passages, {phrases} phrases), {n_edges} edges, {projects} projects"


def main() -> None:
    from noble_agent.config import settings

    parser = argparse.ArgumentParser(description="Export HippoRAG graph.json to GEXF + CSV for external viewers.")
    parser.add_argument("--graph", default=settings.hipporag_graph_path, help="Path to graph.json")
    parser.add_argument("--out-dir", default="", help="Output dir (default: next to the graph.json)")
    parser.add_argument("--emit", choices=["gexf", "csv", "both"], default="both")
    args = parser.parse_args()

    if not os.path.isfile(args.graph):
        raise SystemExit(f"graph not found: {args.graph} (run `noble-rag-sync --renew-graph` first)")

    with open(args.graph, encoding="utf-8") as fh:
        graph = json.load(fh)

    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.graph))
    os.makedirs(out_dir, exist_ok=True)

    print(f"Loaded: {escape(_stats(graph))}")
    written: list[str] = []

    if args.emit in ("gexf", "both"):
        gexf_path = os.path.join(out_dir, "graph.gexf")
        with open(gexf_path, "w", encoding="utf-8") as fh:
            fh.write(build_gexf(graph))
        written.append(gexf_path)

    if args.emit in ("csv", "both"):
        nodes_path = os.path.join(out_dir, "graph_nodes.csv")
        edges_path = os.path.join(out_dir, "graph_edges.csv")
        write_node_csv(graph, nodes_path)
        write_edge_csv(graph, edges_path)
        written.extend([nodes_path, edges_path])

    print("Wrote:")
    for p in written:
        print(f"  {p}")
    print()
    print("Next:")
    print("  • Gephi (desktop): File → Open → graph.gexf. Layout: ForceAtlas 2.")
    print("    Appearance → Nodes → Color → Partition → 'project'; Size → Ranking → 'degree'.")
    print("    Filters → Attributes → 'type' to isolate phrase vs passage.")
    print("  • Cosmograph (web, no install): open https://cosmograph.app → drop graph_edges.csv")
    print("    (source/target/weight) and graph_nodes.csv as metadata (id → label/project).")


if __name__ == "__main__":
    main()
