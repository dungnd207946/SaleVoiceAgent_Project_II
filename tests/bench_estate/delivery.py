"""Convert Case → list of user_input strings to send to the agent.

Three delivery modes (per spec §3):
- literal:  Section B (internal nghiệp vụ knowledge) — direct MCQ format with ABCD
- roleplay: Sections A + D (pháp lý + đạo đức) — natural Vietnamese customer question
- scripted_multiturn: Phần C essay + 9 scenarios — extract KH turns in order
"""

from __future__ import annotations

from tests.bench_estate.loader import Case, EssayCase, MCQCase, ScenarioCase


def to_user_inputs(case: Case) -> list[str]:
    if isinstance(case, MCQCase):
        if case.delivery_mode == "literal":
            return [_literal_mcq(case)]
        # roleplay
        return [case.roleplay_question or case.question]
    if isinstance(case, (EssayCase, ScenarioCase)):
        return [t.text for t in case.turns if t.speaker == "KH"]
    raise TypeError(f"unsupported case type: {type(case)}")


def _literal_mcq(case: MCQCase) -> str:
    lines = [
        "[CHẾ ĐỘ KIỂM TRA NGHIỆP VỤ NỘI BỘ]",
        f"Câu {case.case_id}: {case.question}",
    ]
    for letter in ("A", "B", "C", "D"):
        lines.append(f"{letter}. {case.choices[letter]}")
    lines.append("")
    lines.append('Trả lời ngắn gọn: "Đáp án: <X>" rồi giải thích 1-2 câu.')
    return "\n".join(lines)
