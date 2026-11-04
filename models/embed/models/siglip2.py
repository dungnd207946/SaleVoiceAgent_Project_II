"""SigLIP2 768d — kind `visual_text` (query) + `visual_image` (ingest)."""

import io

from embed import settings


class Siglip2:
    def __init__(self) -> None:
        import torch
        from transformers import AutoModel, AutoProcessor

        self._torch = torch
        self._model = AutoModel.from_pretrained(settings.VISUAL_MODEL)
        self._model.eval().to(settings.DEVICE)
        self._processor = AutoProcessor.from_pretrained(settings.VISUAL_MODEL)
        self.dim = int(self._model.config.text_config.hidden_size)

    def _norm(self, feats):
        return feats / feats.norm(dim=-1, keepdim=True).clamp_min(1e-12)

    def _out(self, feats) -> list[list[float]]:
        return [[float(x) for x in row] for row in self._norm(feats).detach().cpu().numpy()]

    def encode(self, texts: list[str], *, is_query: bool = True) -> list[list[float]]:
        """Text tower. `is_query` không dùng: SigLIP không có prefix bất đối xứng."""
        with self._torch.no_grad():
            inp = self._processor(
                text=texts,
                return_tensors="pt",
                padding="max_length",
                max_length=settings.VISUAL_MAXLEN,
                truncation=True,
            ).to(settings.DEVICE)
            out = self._model.get_text_features(**inp)
        return self._out(out if self._torch.is_tensor(out) else out.pooler_output)

    def encode_images(self, images: list[bytes]) -> list[list[float]]:
        from PIL import Image

        pils = [Image.open(io.BytesIO(raw)).convert("RGB") for raw in images]
        with self._torch.no_grad():
            inp = self._processor(images=pils, return_tensors="pt").to(settings.DEVICE)
            out = self._model.get_image_features(**inp)
        return self._out(out if self._torch.is_tensor(out) else out.pooler_output)
