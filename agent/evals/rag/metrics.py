"""Aggregate retrieval metrics v2 — thuần, test được không cần Qdrant.

context_precision_at_k là LOWER BOUND: mẫu số là k chứ không phải số chunk
thật-sự-liên-quan trong top-k (golden set không phủ hết chunk liên quan).
Đọc nó như "ít nhất bao nhiêu phần top-k chắc chắn liên quan".
"""

from __future__ import annotations

from evals.common import percentiles_ms


def aggregate(per_case: list[list[int | None]], latencies_ms: list[float], *, ks: tuple[int, ...] = (1, 3, 5)) -> dict:
    n = len(per_case)
    out: dict[str, float | None] = {}
    for k in ks:
        hits_any: list[float] = []
        c_recall: list[float] = []
        c_precision: list[float] = []
        for ranks in per_case:
            found = [r for r in ranks if r is not None and r < k]
            hits_any.append(1.0 if found else 0.0)
            c_recall.append(len(found) / len(ranks))
            c_precision.append(len(found) / k)
        out[f"recall_at_{k}"] = (sum(hits_any) / n) if n else None
        out[f"context_recall_at_{k}"] = (sum(c_recall) / n) if n else None
        out[f"context_precision_at_{k}"] = (sum(c_precision) / n) if n else None
    rrs = []
    for ranks in per_case:
        found = [r for r in ranks if r is not None]
        rrs.append(1.0 / (min(found) + 1) if found else 0.0)
    out["mrr"] = (sum(rrs) / n) if n else None
    pcts = percentiles_ms(latencies_ms)
    out["retrieval_p50_ms"] = pcts.get("p50")
    out["retrieval_p95_ms"] = pcts.get("p95")
    return out
