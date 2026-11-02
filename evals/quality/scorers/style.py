"""Style axis — linter XÁC ĐỊNH cho mục Style của persona, không judge.

Mục Style ("nói như người thật, không như tổng đài") vừa được sửa bằng tay và đo bằng
tay (29/32 tin mở "Dạ" → 0/10; "ạ" cuối câu 50% → 21%). Không có scorer thì lần sửa
prompt kế tiếp kéo văn phong về tổng đài mà không ai thấy. Năm luật, mỗi luật một
regex, chấm MỌI reply không rỗng của case reviewed có trace:

- style_da_opener   : reply mở đầu bằng "Dạ" (persona: chỉ khi vừa trả lời CÓ/KHÔNG —
                      không phân biệt được bằng regex nên đếm hết; đọc kèm finding).
- style_a_overuse   : quá MỘT chữ "ạ" đứng riêng trong một reply.
- style_markdown    : ký hiệu markdown (**, #, gạch đầu dòng, bảng, backtick) — persona
                      cấm tuyệt đối; `MarkdownStripper` đã lọc stream nên metric này còn
                      là lưới bắt regression của chính stripper.
- style_multi_question : từ hai dấu hỏi trở lên trong một reply ("một tin một dấu hỏi").
- style_cliche      : câu sáo tổng đài ("cảm ơn … đã dành thời gian", "chúc … một ngày
                      tốt lành", "rất vui được hỗ trợ", "cần gì cứ nhắn em") khi KHÁCH
                      chưa chào kết — lời chúc chỉ hợp ở câu chào kết thật sự.

Mẫu số của mọi `*_rate` là `style_replies_checked`; rỗng → `None` (chưa đo, không
phải đạt — xem `scorers/tool_selection.py::_gated_rate`).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from evals.quality.cases import EvalCase
from evals.quality.scorers import AxisScore, Finding
from evals.quality.scorers.tool_selection import _gated_rate
from evals.quality.trace import TraceCase

AXIS = "style"

_DA_OPENER = re.compile(r"^\s*dạ\b", re.IGNORECASE)
# "ạ" đứng riêng — không bắt "lạ", "hạ", "tạ" (\w của Python khớp cả chữ có dấu).
_A_PARTICLE = re.compile(r"(?<!\w)ạ(?!\w)", re.IGNORECASE)
_MARKDOWN = re.compile(r"\*\*|__|`|^\s*[-*•]\s|^\s*#{1,6}\s|^\s*\|.*\|\s*$", re.MULTILINE)
_CLICHES = (
    re.compile(r"cảm ơn .{0,40}đã dành thời gian", re.IGNORECASE),
    re.compile(r"chúc .{0,40}một ngày (tốt lành|vui vẻ)", re.IGNORECASE),
    re.compile(r"rất vui được (hỗ trợ|phục vụ|tư vấn)", re.IGNORECASE),
    re.compile(r"cần gì .{0,10}cứ (nhắn|gọi|liên hệ)", re.IGNORECASE),
)
_GOODBYE = re.compile(
    r"cảm ơn|tạm biệt|chào (em|anh|chị)|để hôm khác|bận rồi|\bbye\b|hẹn gặp|ok vậy thôi|thôi nhé",
    re.IGNORECASE,
)


def _violations(user: str, reply: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if _DA_OPENER.search(reply):
        out.append(("style_da_opener", f"mở đầu bằng 'Dạ': {reply[:60]!r}"))
    n_a = len(_A_PARTICLE.findall(reply))
    if n_a > 1:
        out.append(("style_a_overuse", f"{n_a} chữ 'ạ' trong một tin (tối đa 1)"))
    if _MARKDOWN.search(reply):
        out.append(("style_markdown", "có ký hiệu markdown (**, #, gạch đầu dòng, bảng, `)"))
    if reply.count("?") >= 2:
        out.append(("style_multi_question", f"{reply.count('?')} dấu hỏi trong một tin (tối đa 1)"))
    if not _GOODBYE.search(user or ""):
        for pat in _CLICHES:
            m = pat.search(reply)
            if m:
                out.append(("style_cliche", f"câu sáo tổng đài khi khách chưa chào kết: {m.group(0)!r}"))
                break
    return out


def score_style(cases: Sequence[EvalCase], traces: Sequence[TraceCase]) -> AxisScore:
    by_id = {t.case_id: t for t in traces}
    findings: list[Finding] = []
    replies = bad_replies = 0
    per_kind = dict.fromkeys(
        ("style_da_opener", "style_a_overuse", "style_markdown", "style_multi_question", "style_cliche"), 0
    )

    for case in cases:
        if not case.reviewed:
            continue
        trace = by_id.get(case.id)
        if trace is None or trace.error:
            continue  # run_integrity đã tính crash/thiếu trace
        for i, turn in enumerate(trace.turns):
            reply = (turn.reply or "").strip()
            if not reply:
                continue
            replies += 1
            found = _violations(turn.user, reply)
            if not found:
                continue
            bad_replies += 1
            for kind, detail in found:
                per_kind[kind] += 1
                findings.append(Finding(case.id, i, kind, detail))

    return AxisScore(
        axis=AXIS,
        checks=replies,
        failures=bad_replies,
        findings=tuple(findings),
        metrics={
            "style_replies_checked": float(replies),
            "style_violation_rate": _gated_rate(bad_replies, replies),
            "style_da_opener_rate": _gated_rate(per_kind["style_da_opener"], replies),
            "style_a_overuse_rate": _gated_rate(per_kind["style_a_overuse"], replies),
            "style_markdown_rate": _gated_rate(per_kind["style_markdown"], replies),
            "style_multi_question_rate": _gated_rate(per_kind["style_multi_question"], replies),
            "style_cliche_rate": _gated_rate(per_kind["style_cliche"], replies),
        },
    )
