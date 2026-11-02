"""Style linter — xác định, không judge. Bắt regression của mục Style trong persona
(mở "Dạ", quá một "ạ"/tin, markdown, hai dấu hỏi/tin, câu sáo tổng đài giữa chừng)."""

from __future__ import annotations

from evals.quality.cases import parse_case
from evals.quality.scorers.style import score_style
from evals.quality.trace import TraceCase, TraceTurn


def _case(users: list[str], case_id: str = "STY-1", reviewed: bool = True):
    return parse_case(
        {
            "id": case_id,
            "tags": ["qa"],
            "origin": "handwritten",
            "tenant": "noble",
            "channel": "chat",
            "reviewed": reviewed,
            "turns": [{"user": u} for u in users],
        }
    )


def _trace(replies: list[str], users: list[str] | None = None, case_id: str = "STY-1") -> TraceCase:
    users = users or ["u"] * len(replies)
    return TraceCase(
        case_id=case_id,
        tags=("qa",),
        tenant="noble",
        channel="chat",
        reviewed=True,
        turns=tuple(TraceTurn(user=u, reply=r) for u, r in zip(users, replies, strict=True)),
    )


def _metrics(replies: list[str], users: list[str] | None = None):
    users = users or ["u"] * len(replies)
    return score_style([_case(users)], [_trace(replies, users)])


def test_clean_reply_has_no_findings():
    s = _metrics(["Căn này hướng Đông Nam, giá 3 tỷ 2. Anh muốn em nói kỹ căn này không ạ?"])
    assert s.axis == "style"
    assert s.findings == ()
    assert s.metrics["style_violation_rate"] == 0.0
    assert s.metrics["style_replies_checked"] == 1.0


def test_da_opener_is_flagged():
    s = _metrics(["Dạ vâng anh cứ cân nhắc thêm nhé."])
    assert [f.kind for f in s.findings] == ["style_da_opener"]
    assert s.metrics["style_da_opener_rate"] == 1.0


def test_more_than_one_a_particle_is_flagged():
    s = _metrics(["Anh cứ cân nhắc thêm ạ. Khi nào cần anh nhắn em ạ."])
    assert "style_a_overuse" in {f.kind for f in s.findings}
    assert s.metrics["style_a_overuse_rate"] == 1.0


def test_single_a_particle_is_fine():
    s = _metrics(["Anh cứ cân nhắc thêm, không vội. Có phải anh còn lăn tăn về giá không ạ?"])
    assert s.metrics["style_a_overuse_rate"] == 0.0


def test_markdown_markers_are_flagged():
    s = _metrics(["**Noble Crystal**\n- giá 3 tỷ\n- hướng Đông"])
    assert "style_markdown" in {f.kind for f in s.findings}
    assert s.metrics["style_markdown_rate"] == 1.0


def test_two_questions_in_one_reply_is_flagged():
    s = _metrics(["Anh muốn xem căn 2 ngủ không? Hay anh thích căn 3 ngủ hơn?"])
    assert "style_multi_question" in {f.kind for f in s.findings}
    assert s.metrics["style_multi_question_rate"] == 1.0


def test_hotline_cliche_mid_conversation_is_flagged():
    s = _metrics(["Cảm ơn anh đã dành thời gian, chúc anh một ngày tốt lành!"], users=["giá bao nhiêu"])
    assert "style_cliche" in {f.kind for f in s.findings}


def test_cliche_allowed_when_customer_says_goodbye():
    s = _metrics(["Cảm ơn anh, cần gì anh cứ nhắn em nhé."], users=["thôi cảm ơn em, để hôm khác nhé"])
    assert "style_cliche" not in {f.kind for f in s.findings}


def test_violation_rate_counts_replies_not_findings():
    # một reply vi phạm hai luật vẫn chỉ là MỘT reply xấu trên hai reply.
    s = _metrics(["Dạ vâng ạ, anh cứ xem ạ.", "Căn này hướng Đông Nam."])
    assert s.metrics["style_violation_rate"] == 0.5
    assert s.metrics["style_replies_checked"] == 2.0


def test_unreviewed_cases_and_empty_replies_are_skipped():
    case = _case(["u"], reviewed=False)
    s = score_style([case], [_trace(["Dạ vâng ạ ạ."])])
    assert s.metrics["style_replies_checked"] == 0.0
    assert s.metrics["style_violation_rate"] is None
    s2 = score_style([_case(["u"])], [_trace([""])])
    assert s2.metrics["style_replies_checked"] == 0.0


def test_empty_input_yields_all_metric_keys():
    s = score_style([], [])
    for key in (
        "style_violation_rate", "style_da_opener_rate", "style_a_overuse_rate",
        "style_markdown_rate", "style_multi_question_rate", "style_cliche_rate", "style_replies_checked",
    ):
        assert key in s.metrics
