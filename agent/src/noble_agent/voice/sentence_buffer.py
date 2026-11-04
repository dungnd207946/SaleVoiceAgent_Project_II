"""Sentence / Clause Buffer — bridges streaming LLM tokens → TTS.

Modes (controlled by settings.buffer_mode):
  "sentence" — yield at sentence endings .!? only (natural intonation, higher TTFA)
  "clause"   — yield also at ,;– when clause is long enough (~40% lower TTFA)

Switch via .env:  BUFFER_MODE=sentence  or  BUFFER_MODE=clause
"""

from __future__ import annotations

from dataclasses import dataclass

from noble_agent.config import settings


@dataclass
class SentenceChunk:
    id: int
    text: str
    is_final: bool = False
    # Pre-synthesized PCM16 (little-endian, mono) at the agent's
    # tts_sample_rate. When set, the TTS consumer plays these bytes
    # directly and skips the live TTS round-trip — used for cached
    # bridge phrases. `text` is kept for logging/UI display only.
    pcm_data: bytes | None = None


class SentenceBuffer:
    SENTENCE_ENDINGS = {".", "!", "?"}
    CLAUSE_ENDINGS = {",", ";", "–", "-"}
    ABBREVIATIONS = {
        # English
        "Dr.",
        "Mr.",
        "Mrs.",
        "Ms.",
        "Jr.",
        "Sr.",
        "Prof.",
        "PM.",
        "AM.",
        "vs.",
        "etc.",
        "e.g.",
        "i.e.",
        "No.",
        "Vol.",
        "Fig.",
        "Dept.",
        "Inc.",
        "Ltd.",
        "Corp.",
        "Co.",
        "St.",
        "Ave.",
        "Blvd.",
        "Rd.",
        "Jan.",
        "Feb.",
        "Mar.",
        "Apr.",
        "Jun.",
        "Jul.",
        "Aug.",
        "Sep.",
        "Oct.",
        "Nov.",
        "Dec.",
        # Vietnamese
        "TP.",
        "Tp.",
        "tp.",  # Thành phố
        "Q.",
        "q.",  # Quận
        "P.",
        "p.",  # Phường
        "Đ/c.",
        "đ/c.",  # Địa chỉ
        "Tr.",
        "tr.",  # Triệu / Trường
        "TS.",
        "Ts.",
        "PGS.",
        "GS.",  # Học hàm
        "KTS.",
        "KS.",  # Kiến trúc sư, Kỹ sư
        "UBND.",  # Ủy ban nhân dân
        # Real Estate / Noble
        "m2.",
        "M2.",  # mét vuông (85m2.)
        "tỷ.",  # giá (3.5 tỷ.)
    }
    MIN_LENGTH = settings.min_sentence_length
    MIN_CLAUSE = settings.min_clause_length
    _clause_mode = settings.buffer_mode == "clause"

    def __init__(self):
        self.buffer = ""
        self._next_id = 0

    def add(self, token: str) -> list[SentenceChunk]:
        """Add a token. Return list of complete chunks (0 or more)."""
        self.buffer += token
        chunks: list[SentenceChunk] = []
        while True:
            idx, is_hard = self._find_boundary()
            if idx == -1:
                break
            chunk = self.buffer[: idx + 1].strip()
            min_len = self.MIN_LENGTH if is_hard else self.MIN_CLAUSE
            if len(chunk) >= min_len:
                chunks.append(SentenceChunk(id=self._next_id, text=chunk))
                self._next_id += 1
                self.buffer = self.buffer[idx + 1 :].lstrip()
            else:
                # Chunk too short — stop searching, keep buffer intact
                break
        return chunks

    def flush(self) -> SentenceChunk | None:
        """Flush remaining text when LLM stream ends."""
        text = self.buffer.strip()
        self.buffer = ""
        if not text:
            return None
        sc = SentenceChunk(id=self._next_id, text=text, is_final=True)
        self._next_id += 1
        return sc

    def _find_boundary(self) -> tuple[int, bool]:
        """
        Returns (index, is_hard_boundary).
        is_hard=True  → sentence ending .!?
        is_hard=False → clause ending ,;–  (only in clause mode)
        Returns (-1, False) if no boundary found.
        """
        soft_candidate = (-1, False)

        for i, ch in enumerate(self.buffer):
            # ── Hard boundary: sentence endings ──────────────────────────────
            if ch in self.SENTENCE_ENDINGS:
                next_is_boundary = i + 1 >= len(self.buffer) or self.buffer[i + 1] in (" ", "\n", "\r")
                if not next_is_boundary:
                    continue
                word_start = self.buffer.rfind(" ", 0, i) + 1
                word = self.buffer[word_start : i + 1]
                if word in self.ABBREVIATIONS:
                    continue
                if (
                    ch == "."
                    and i > 0
                    and self.buffer[i - 1].isdigit()
                    and i + 1 < len(self.buffer)
                    and self.buffer[i + 1].isdigit()
                ):
                    continue
                # "." after a digit at the END of the buffer (mid-stream): the
                # next char may be the rest of a separated number ("7.200")
                # that hasn't streamed in yet. Defer the boundary until the
                # following token arrives to disambiguate (a real sentence end
                # like "phòng 3." is emitted by flush() if the stream ends, or
                # splits correctly once a non-digit follows). Prevents reading
                # "7.200" as "7" <pause> "200".
                if ch == "." and i > 0 and self.buffer[i - 1].isdigit() and i + 1 >= len(self.buffer):
                    continue
                # Mid-stream end-of-buffer inside a URL: rest of the link hasn't
                # arrived. Same defer as the digit case ("https://kuula." | "co/…").
                if i + 1 >= len(self.buffer) and "://" in self.buffer[word_start:]:
                    continue
                return (i, True)

            # ── Soft boundary: clause endings (clause mode only) ──────────────
            if self._clause_mode and ch in self.CLAUSE_ENDINGS:
                next_is_space = i + 1 >= len(self.buffer) or self.buffer[i + 1] in (" ", "\n", "\r")
                if next_is_space and soft_candidate[0] == -1:
                    soft_candidate = (i, False)

        # No hard boundary — return earliest soft candidate if any
        return soft_candidate
