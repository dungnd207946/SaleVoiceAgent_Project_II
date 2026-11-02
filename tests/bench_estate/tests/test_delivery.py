from tests.bench_estate.delivery import to_user_inputs
from tests.bench_estate.loader import EssayCase, MCQCase, ScenarioCase, Turn


def _mcq(case_id, section, mode, question="Thời hạn?", correct="B"):
    return MCQCase(
        case_id=case_id,
        section=section,
        topic="t",
        question=question,
        choices={"A": "3", "B": "5", "C": "7", "D": "10"},
        correct=correct,
        points=2.0,
        delivery_mode=mode,
        roleplay_question="Em ơi chứng chỉ mấy năm vậy?" if mode == "roleplay" else None,
    )


def test_literal_mcq_format():
    case = _mcq("B-72", "B", "literal", question="SPIN viết tắt của:")
    inputs = to_user_inputs(case)
    assert len(inputs) == 1
    assert "B-72" in inputs[0]
    assert "Trả lời ngắn gọn" in inputs[0]
    assert "A. 3" in inputs[0] and "D. 10" in inputs[0]


def test_roleplay_mcq_uses_roleplay_question():
    case = _mcq("A-6", "A", "roleplay")
    inputs = to_user_inputs(case)
    assert inputs == ["Em ơi chứng chỉ mấy năm vậy?"]


def test_roleplay_falls_back_to_question_if_no_cache():
    case = MCQCase(
        case_id="A-99",
        section="A",
        topic="t",
        question="Q?",
        choices={"A": "a", "B": "b", "C": "c", "D": "d"},
        correct="A",
        points=2.0,
        delivery_mode="roleplay",
        roleplay_question=None,
    )
    inputs = to_user_inputs(case)
    assert inputs == ["Q?"]


def test_essay_returns_kh_turns_only():
    case = EssayCase(
        case_id="C-1",
        title="t",
        case_text="ctx",
        turns=(Turn("KH", "câu 1?"), Turn("Sale", "REFERENCE: x"), Turn("KH", "câu 2?")),
        rubric_checkpoints=(("a",), ("b",)),
        key_answers={},
    )
    assert to_user_inputs(case) == ["câu 1?", "câu 2?"]


def test_scenario_returns_kh_turns_only():
    case = ScenarioCase(
        case_id="S-1",
        title="t",
        setup="s",
        turns=(Turn("KH", "Hello"), Turn("Sale", "REFERENCE: x"), Turn("KH", "Bye")),
        rubric_checkpoints=(("a",), ("b",)),
    )
    assert to_user_inputs(case) == ["Hello", "Bye"]
