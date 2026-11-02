from noble_agent.agent.catalog import VALID_CODES
from noble_agent.agent.rag.flat_store import FlatStore


def test_load_chunks_only_loads_chunks_and_project_idx_without_embeddings():
    s = FlatStore()
    s.load_chunks_only()
    assert len(s.chunks) > 0
    assert s.embeddings is None
    # project_idx covers every canonical code present in the corpus
    assert set(s.project_idx) == set(VALID_CODES)
    # indices map back to chunks of that project
    for code, idx in s.project_idx.items():
        if len(idx):
            assert s.chunks[int(idx[0])].project == code
