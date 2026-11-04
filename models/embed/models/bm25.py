"""BM25 sparse — kind `sparse`."""

from embed import settings


class Bm25:
    def __init__(self) -> None:
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name=settings.SPARSE_MODEL, cache_dir=settings.CACHE_DIR)

    def encode_sparse(self, texts: list[str]) -> list[dict]:
        return [
            {"indices": [int(i) for i in v.indices], "values": [float(x) for x in v.values]}
            for v in self._model.embed(texts)
        ]
