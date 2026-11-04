"""_load_hotwords của Soniox — bẫy env rỗng (SHERPA_HOTWORDS_FILE=).

Đường dẫn rỗng join với dirname ra chính thư mục voice/ → open(dir) nổ
IsADirectoryError → cả backend Soniox chết lúc start và fallback sang remote.
Sherpa đã có guard `if settings.sherpa_hotwords_file:` — Soniox phải tương đương.
"""

from __future__ import annotations

from unittest.mock import patch

from noble_agent.voice.stt.soniox import _load_hotwords


class TestLoadHotwords:
    def test_empty_setting_returns_empty_not_isadirectoryerror(self) -> None:
        with patch("noble_agent.voice.stt.soniox.settings") as s:
            s.sherpa_hotwords_file = ""
            assert _load_hotwords() == []

    def test_path_pointing_at_directory_returns_empty(self, tmp_path) -> None:
        with patch("noble_agent.voice.stt.soniox.settings") as s:
            s.sherpa_hotwords_file = str(tmp_path)  # tồn tại nhưng là thư mục
            assert _load_hotwords() == []

    def test_valid_file_loads_terms(self, tmp_path) -> None:
        f = tmp_path / "hotwords.txt"
        f.write_text("Noble Crystal\n\nAlluvia\n", encoding="utf-8")
        with patch("noble_agent.voice.stt.soniox.settings") as s:
            s.sherpa_hotwords_file = str(f)
            assert _load_hotwords() == ["Noble Crystal", "Alluvia"]

    def test_missing_file_returns_empty(self) -> None:
        with patch("noble_agent.voice.stt.soniox.settings") as s:
            s.sherpa_hotwords_file = "/nonexistent/hotwords.txt"
            assert _load_hotwords() == []
