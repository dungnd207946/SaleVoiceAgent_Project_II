from noble_agent.agent.rag import sparse_encoder as se


def test_encode_document_is_deterministic():
    a = se.encode_document("căn hộ Noble Crystal Tây Hồ giá bao nhiêu")
    b = se.encode_document("căn hộ Noble Crystal Tây Hồ giá bao nhiêu")
    assert a == b
    idx, val = a
    assert len(idx) == len(val) > 0
    assert all(isinstance(i, int) and i >= 0 for i in idx)
    assert all(v > 0 for v in val)


def test_query_encoding_is_unit_weighted():
    idx, val = se.encode_query("giá căn hộ giá")
    assert all(v == 1.0 for v in val)
    # duplicate token collapses to one index
    assert len(idx) == len(set(idx))


def test_repeated_term_saturates_below_linear():
    idx1, val1 = se.encode_document("giá")
    idx3, val3 = se.encode_document("giá giá giá")
    w1 = dict(zip(idx1, val1, strict=True))
    w3 = dict(zip(idx3, val3, strict=True))
    term = idx1[0]
    # tf=3 weight is higher than tf=1 but less than 3x (BM25 saturation)
    assert w3[term] > w1[term]
    assert w3[term] < 3 * w1[term]
