"""Logging setup — structured JSON (file) + color console handlers.

Production: LOG_FORMAT=json  → both handlers emit JSON lines (machine-readable).
Development: LOG_FORMAT=text → color console + JSON file (default).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time


class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line — suitable for log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "file": record.filename,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _ColorFormatter(logging.Formatter):
    _COLORS = {
        "DEBUG": "\033[90m",
        "INFO": "\033[92m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "CRITICAL": "\033[1;91m",
    }
    _RESET = "\033[0m"

    # Phân loại theo (icon, màu, tag) — khớp theo THỨ TỰ: message-tag trước
    # (cụ thể hơn logger-name: base_session phát cả [STT]/[Speaker]/[Addressee]),
    # rồi mới tới logger-name substring. Màu = ANSI 256 để các loại tách nhau
    # rõ; WARNING trở lên vẫn đè bằng màu level (lỗi phải nổi hơn phân loại).
    _MSG_TAGS: list[tuple[str, tuple[str, str, str]]] = [
        ("[Speaker]", ("🗣️ ", "\033[38;5;220m", "SPK")),
        ("[STT]", ("🎤", "\033[38;5;51m", "STT")),
        ("[VAD]", ("👂", "\033[38;5;114m", "VAD")),
        ("[Addressee]", ("🚦", "\033[38;5;208m", "ADR")),
        ("[SmartTurn]", ("🔄", "\033[38;5;114m", "TRN")),
        ("[SERVER]", ("🌐", "\033[38;5;245m", "SRV")),
    ]
    # SPK tách làm hai màu để soi đường barge-in bằng mắt: verdict khớp danh
    # tính giữ vàng (màu SPK mặc định ở trên), không khớp đổi sang tím. Bắt
    # theo dấu hiệu KHÔNG-khớp chứ không bắt "speaker" — chuỗi "non-speaker"
    # chứa nguyên "speaker", kiểm xuôi sẽ tô mọi verdict thành khớp.
    _SPK_NOMATCH_COLOR = "\033[38;5;141m"
    _SPK_NOMATCH_MARKS = ("non-speaker", "unknown")

    _NAME_PARTS: list[tuple[str, tuple[str, str, str]]] = [
        (".voice.stt", ("🎤", "\033[38;5;51m", "STT")),
        (".voice.tts", ("🔊", "\033[38;5;213m", "TTS")),
        (".voice.vad", ("👂", "\033[38;5;114m", "VAD")),
        (".voice.speaker", ("🗣️ ", "\033[38;5;220m", "SPK")),
        (".agent.llm", ("🧠", "\033[38;5;75m", "LLM")),
        (".agent.tools", ("🔧", "\033[38;5;180m", "TOOL")),
        (".agent.rag", ("📚", "\033[38;5;150m", "RAG")),
        (".agent.", ("🧠", "\033[38;5;75m", "AGENT")),
        (".transport.livekit", ("📡", "\033[38;5;245m", "LK")),
        (".telephony", ("☎️ ", "\033[38;5;245m", "TEL")),
        (".server.", ("🌐", "\033[38;5;245m", "SRV")),
        (".storage", ("💾", "\033[38;5;138m", "DB")),
        (".billing", ("🧾", "\033[38;5;138m", "BILL")),
        ("livekit", ("📡", "\033[38;5;240m", "LK")),
    ]

    @classmethod
    def _category(cls, name: str, msg: str) -> tuple[str, str, str] | None:
        for tag, cat in cls._MSG_TAGS:
            if msg.startswith(tag):
                return cat
        for part, cat in cls._NAME_PARTS:
            if part in name:
                return cat
        return None

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        cat = self._category(record.name, msg)
        level_color = self._COLORS.get(record.levelname, self._RESET)
        if cat is not None:
            icon, cat_color, tag = cat
            if tag == "SPK" and any(mark in msg for mark in self._SPK_NOMATCH_MARKS):
                cat_color = self._SPK_NOMATCH_COLOR
            # WARNING+ giữ màu level cho phần message — lỗi phải nổi hơn loại.
            body_color = level_color if record.levelno >= logging.WARNING else cat_color
            prefix = f"{cat_color}{icon} {tag:<5}{self._RESET}"
            colored = f"{prefix} {body_color}{msg}{self._RESET}"
        else:
            colored = f"{level_color}{msg}{self._RESET}"
        # KHÔNG mutate record.msg/args — record dùng chung với file handler
        # (JSON); mutate ở đây từng là bug tiềm ẩn phụ thuộc thứ tự handler.
        clone = logging.makeLogRecord(record.__dict__)
        clone.msg = colored
        clone.args = None
        return super().format(clone)


_logging_configured = False
_TEXT_FORMAT = "%(asctime)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s"


def setup_logging() -> None:
    """Configure root logger. Safe to call multiple times — configures once.

    Env vars:
      LOG_FORMAT=json   force JSON on console too (CI / container stdout)
      LOG_LEVEL=DEBUG   override default INFO
    """
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True

    log_format = os.environ.get("LOG_FORMAT", "text").lower()
    log_level = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO)

    os.makedirs("logs", exist_ok=True)

    # File handler — always JSON for structured log aggregation
    file_handler = logging.handlers.RotatingFileHandler(
        "logs/agent.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(_JsonFormatter())

    # Console handler — JSON in CI/prod, color text in dev
    console_handler = logging.StreamHandler()
    if log_format == "json":
        console_handler.setFormatter(_JsonFormatter())
    else:
        console_handler.setFormatter(_ColorFormatter(_TEXT_FORMAT))

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
    # Bịt các logger hệ thống ồn ào — chúng nhấn chìm log phiên (STT/SPK/LLM):
    # - httpx in INFO một dòng cho MỌI request (embed, LLM, TTS...)
    # - opentelemetry exporter xả full traceback mỗi lần collector không với tới
    # - urllib3 retry noise đi kèm chuỗi OTEL ở trên
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)
