"""e5-large 1024d — kind `dense`."""

from embed import settings


class E5:
    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(settings.DENSE_MODEL, device=settings.DEVICE)
        self.dim = self._model.get_sentence_embedding_dimension()

    def encode(self, texts: list[str], *, is_query: bool) -> list[list[float]]:
        # e5 bất đối xứng: query và passage phải khác prefix, sai là degrade âm thầm.
        tag = "query: " if is_query else "passage: "
        vecs = self._model.encode(
            [tag + t for t in texts],
            batch_size=settings.BATCH_SIZE,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in v] for v in vecs]
