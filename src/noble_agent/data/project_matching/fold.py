"""Deterministic text normalization + phonetic folding for project-name matching.

`fold_text` VN-folds (tone-strip + confusable-consonant fold — the #1 STT error
classes for VN voice) EVERY token, then runs Double Metaphone on the folded
result, unconditionally — there's no VN-vs-English token bifurcation. All
functions are pure and import-safe; metaphone degrades to the raw token if the
optional `metaphone` package is absent.
"""

from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")
_ASCII_ALPHA = re.compile(r"^[a-z0-9]+$")

# Initial-consonant clusters folded to a shared representative. Longest-first so
# multi-char clusters ("ch", "tr", "gi", "ph", "ng") match before single chars.
_INITIALS: tuple[tuple[str, str], ...] = (
    ("ch", "c"), ("tr", "c"),
    ("gi", "z"), ("ph", "f"),
    ("ng", "g"),  # handled again for finals below; harmless as initial
)
_SINGLE_INITIALS = {"x": "s", "s": "s", "r": "z", "d": "z", "l": "n", "n": "n"}


def normalize_text(s: str) -> str:
    """Lowercase, NFC-normalize, collapse whitespace."""
    s = unicodedata.normalize("NFC", (s or "").strip().lower())
    return _WS.sub(" ", s)


def is_ascii_token(tok: str) -> bool:
    return bool(_ASCII_ALPHA.match(tok))


def strip_tones(s: str) -> str:
    """Lowercase + remove Vietnamese tone/diacritic marks; đ -> d.

    Tone-strip ONLY — no consonant folding. Kept public because the Postgres KB
    provider folds region/address the same way in SQL (`translate()`), and that
    SQL cannot reproduce `fold_vietnamese`'s consonant folding.
    """
    s = (s or "").lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", s)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def fold_vietnamese(tok: str) -> str:
    """Tone-strip + fold confusable consonants for a single VN token."""
    t = strip_tones(tok)
    if not t:
        return t
    # fold initial cluster
    for cluster, rep in _INITIALS:
        if t.startswith(cluster):
            t = rep + t[len(cluster):]
            break
    else:
        if t[0] in _SINGLE_INITIALS:
            t = _SINGLE_INITIALS[t[0]] + t[1:]
    # fold finals: nh/ng -> g, trailing t/c -> k
    if t.endswith("nh") or t.endswith("ng"):
        t = t[:-2] + "g"
    if t.endswith("t") or t.endswith("c"):
        t = t[:-1] + "k"
    return t


def metaphone_en(tok: str) -> str:
    """Primary Double Metaphone code for an English token; raw token if lib absent."""
    try:
        from metaphone import doublemetaphone
    except ImportError:
        return tok  # degrade: fall back to the raw token
    primary, _secondary = doublemetaphone(tok)
    return primary or tok


def fold_text(s: str) -> str:
    """Per-token fold of a full string: VN-fold first, then metaphone the ascii result.

    VN-folding (tone-strip + consonant-fold) runs unconditionally on every token —
    it's a no-op for tokens with no VN consonant/tone patterns (e.g. English brand
    words), so it's always safe to apply. This matters because Vietnamese place
    names are frequently typed/transcribed WITHOUT diacritics (ascii "tay ho"),
    which would otherwise short-circuit straight to metaphone_en and diverge from
    the accented form's VN-fold + metaphone code. Running metaphone_en on top of
    the (always-ascii) VN-fold result then normalizes any remaining latin-spelling
    variance (e.g. "crystal"/"cristal").
    """
    toks = normalize_text(s).split(" ")
    out = []
    for t in toks:
        if not t:
            continue
        folded = fold_vietnamese(t)
        out.append(metaphone_en(folded) if is_ascii_token(folded) else folded)
    return " ".join(out)
