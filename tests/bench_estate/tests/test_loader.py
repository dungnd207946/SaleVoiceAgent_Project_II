from pathlib import Path

from tests.bench_estate.loader import EssayCase, MCQCase, ScenarioCase, Turn


def test_mcq_case_is_frozen():
    case = MCQCase(
        case_id="A-6",
        section="A",
        topic="CCHN",
        question="Thời hạn?",
        choices={"A": "3", "B": "5", "C": "7", "D": "10"},
        correct="B",
        points=2.0,
        delivery_mode="roleplay",
    )
    assert case.case_id == "A-6"
    import dataclasses

    assert dataclasses.is_dataclass(case)
    # frozen=True → setattr raises
    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        case.case_id = "X"


def test_turn_speaker_validates():
    t = Turn(speaker="KH", text="Em ơi")
    assert t.speaker == "KH"


def test_essay_case_default_delivery():
    case = EssayCase(
        case_id="C-1",
        title="t",
        case_text="ctx",
        turns=(Turn("KH", "x"),),
        rubric_checkpoints=(("a",),),
        key_answers={},
    )
    assert case.points == 20.0
    assert case.delivery_mode == "scripted_multiturn"


def test_scenario_case_max_extra_turns_default():
    case = ScenarioCase(
        case_id="S-1",
        title="t",
        setup="s",
        turns=(Turn("KH", "x"),),
        rubric_checkpoints=(("a",),),
    )
    assert case.max_extra_turns == 0


REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET_JSON = REPO_ROOT / "docs" / "estate_cert" / "BO_DE_AI_AGENT_DATASET.json"


def test_load_json_dataset_counts():
    from tests.bench_estate.loader import _load_json_dataset

    sections = _load_json_dataset(DATASET_JSON)
    assert len(sections["A"]) == 50
    assert len(sections["B"]) == 40
    assert len(sections["C"]) == 5
    assert len(sections["D"]) == 20


def test_load_json_dataset_mcq_correct_field():
    from tests.bench_estate.loader import _load_json_dataset

    sections = _load_json_dataset(DATASET_JSON)
    a6 = next(q for q in sections["A"] if q["id"] == 6)
    assert a6["answer"] == "B"  # CCHN 5 năm


def test_load_json_dataset_essay_keys_present():
    from tests.bench_estate.loader import _load_json_dataset

    sections = _load_json_dataset(DATASET_JSON)
    c1 = sections["C"][0]
    assert c1["id"] == 1
    assert "key_answers" in c1
    assert "dot_1" in c1["key_answers"]


QUESTIONS_MD = REPO_ROOT / "docs" / "estate_cert" / "DE_THI_NHAN_VIEN.md"


def test_load_md_questions_count():
    from tests.bench_estate.loader import _load_md_questions

    qs = _load_md_questions(QUESTIONS_MD)
    # 50 + 40 + 20 = 110 MCQ. Phần C is essay, parsed separately.
    assert len(qs) >= 110


def test_load_md_questions_returns_choices():
    from tests.bench_estate.loader import _load_md_questions

    qs = _load_md_questions(QUESTIONS_MD)
    q6 = qs[6]
    assert "Thời hạn" in q6["question"]
    assert q6["choices"]["B"].startswith("5")


def test_essay_case_files_loadable():
    import json

    cases_dir = REPO_ROOT / "tests" / "bench_estate" / "data" / "personas_cases"
    files = sorted(cases_dir.glob("*.json"))
    assert len(files) == 5
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["case_id"].startswith("C-")
        assert d["turns"]
        assert d["rubric_checkpoints"]
        # rubric_checkpoints length must match number of Sale turns
        n_sale_turns = sum(1 for t in d["turns"] if t["speaker"] == "Sale")
        assert len(d["rubric_checkpoints"]) == n_sale_turns, f"{f.name}: rubric length mismatch"


def test_scenario_files_loadable():
    import json

    sc_dir = REPO_ROOT / "tests" / "bench_estate" / "data" / "personas_scenarios"
    files = sorted(sc_dir.glob("*.json"))
    assert len(files) == 9
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        assert d["case_id"].startswith("S-")
        assert d["turns"]
        n_sale_turns = sum(1 for t in d["turns"] if t["speaker"] == "Sale")
        assert len(d["rubric_checkpoints"]) == n_sale_turns, f"{f.name}: rubric length mismatch"
        # First turn must be KH (customer initiates the scenario)
        assert d["turns"][0]["speaker"] == "KH", f"{f.name}: first turn must be KH"


def test_load_all_returns_124_typed_cases():
    from tests.bench_estate.loader import EssayCase, MCQCase, ScenarioCase, load_all

    cases = load_all()
    assert len(cases) == 124
    by_type = {"mcq": 0, "essay": 0, "scenario": 0}
    for c in cases:
        if isinstance(c, MCQCase):
            by_type["mcq"] += 1
        elif isinstance(c, EssayCase):
            by_type["essay"] += 1
        elif isinstance(c, ScenarioCase):
            by_type["scenario"] += 1
    assert by_type == {"mcq": 110, "essay": 5, "scenario": 9}


def test_load_all_a_section_uses_roleplay_question():
    from tests.bench_estate.loader import MCQCase, load_all

    cases = load_all()
    a6 = next(c for c in cases if isinstance(c, MCQCase) and c.case_id == "A-6")
    assert a6.delivery_mode == "roleplay"
    assert a6.roleplay_question is not None and len(a6.roleplay_question) > 5


def test_load_all_b_section_uses_literal():
    from tests.bench_estate.loader import MCQCase, load_all

    cases = load_all()
    b72 = next(c for c in cases if isinstance(c, MCQCase) and c.case_id == "B-72")
    assert b72.delivery_mode == "literal"
