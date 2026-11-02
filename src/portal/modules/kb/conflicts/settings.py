"""Tham số của bộ dò mâu thuẫn — chỉnh sau khi đo trên dữ liệu thật (spec §4.3)."""

from portal.modules.kb.contracts import DEFAULT_DOC_TYPE, TITLE_PREFIXES

TOP_K = 3
MIN_SCORE = 0.75
BATCH = 8
DOC_TYPES = frozenset({*TITLE_PREFIXES.values(), DEFAULT_DOC_TYPE})
FIELD_ANCHOR = "tong_quan"
