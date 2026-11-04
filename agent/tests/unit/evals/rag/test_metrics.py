from evals.rag.metrics import aggregate


def test_single_chunk_case_matches_old_recall():
    out = aggregate([[0], [None], [2]], [10.0, 20.0, 30.0])
    assert out["recall_at_1"] == 1 / 3
    assert out["recall_at_3"] == 2 / 3
    assert out["mrr"] == (1.0 + 0.0 + 1 / 3) / 3


def test_context_recall_and_precision():
    # case 1: 2 golden, cả 2 trong top-3 (rank 0,2); case 2: 2 golden, 1 hit rank 1
    out = aggregate([[0, 2], [1, None]], [1.0, 1.0])
    assert out["context_recall_at_3"] == (2 / 2 + 1 / 2) / 2
    assert out["context_precision_at_3"] == (2 / 3 + 1 / 3) / 2
    assert out["recall_at_3"] == 1.0


def test_empty_input_none():
    out = aggregate([], [])
    assert out["recall_at_1"] is None and out["mrr"] is None
