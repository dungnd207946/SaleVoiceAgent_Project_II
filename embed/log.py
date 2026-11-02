"""Cấu hình log dùng chung."""

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_NOISY = ("httpx", "httpcore", "huggingface_hub", "filelock", "urllib3")


def setup(level: str = "INFO") -> None:
    resolved = getattr(logging, level.upper(), None)
    if not isinstance(resolved, int):
        resolved = logging.INFO
    logging.basicConfig(level=resolved, format=_FORMAT, force=True)
    logging.getLogger().setLevel(resolved)
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
