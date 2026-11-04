from evals.bench.vad import iter_chunks


def test_iter_chunks_drops_tail():
    chunks = iter_chunks(b"\x00" * 2100, chunk_bytes=1024)
    assert len(chunks) == 2 and all(len(c) == 1024 for c in chunks)
