"""Nạp prompts.yaml. Một lần, cache module-level.

`importlib.resources` chứ không `Path(__file__).parent`: đường thứ hai gãy khi chạy
từ wheel — tức ở production, không phải ở máy người viết.
"""

from dataclasses import dataclass
from functools import cache

import yaml


@dataclass(frozen=True, slots=True)
class PromptSpec:
    name: str
    model: str
    prompt: str
    max_tokens: int
    temperature: float


@cache
def load() -> dict[str, PromptSpec]:
    from importlib.resources import files

    raw = yaml.safe_load(files("portal.modules.kb").joinpath("prompts.yaml").read_text(encoding="utf-8"))
    return {
        name: PromptSpec(
            name=name,
            model=str(cfg["model"]),
            prompt=str(cfg.get("prompt", "")),
            max_tokens=int(cfg.get("max_tokens", 300)),
            temperature=float(cfg.get("temperature", 0.2)),
        )
        for name, cfg in (raw or {}).items()
    }


def get(name: str) -> PromptSpec:
    """KeyError chứ không rơi về mặc định: một profile gõ sai rơi về `caption`
    nghĩa là ảnh sơ đồ được mô tả bằng prompt của ảnh phối cảnh, và không ai thấy."""
    try:
        return load()[name]
    except KeyError:
        raise KeyError(f"profile {name!r} không có trong prompts.yaml — có: {sorted(load())}") from None
