"""Load estate certification test bank into typed cases.

Sources:
- docs/estate_cert/BO_DE_AI_AGENT_DATASET.json — 110 MCQ structured (id, topic, correct)
- docs/estate_cert/DE_THI_NHAN_VIEN.md — full question text + 4 choices
- tests/bench_estate/data/personas_cases/*.json — 5 multi-turn case studies (Phần C)
- tests/bench_estate/data/personas_scenarios/*.json — 9 sales scenarios (research1)
- tests/bench_estate/data/personas_mcq/{A,D}_questions.json — roleplay-converted MCQ A+D
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Turn:
    speaker: Literal["KH", "Sale"]
    text: str = ""


@dataclass(frozen=True)
class MCQCase:
    case_id: str
    section: Literal["A", "B", "D"]
    topic: str
    question: str
    choices: dict[str, str]
    correct: Literal["A", "B", "C", "D"]
    points: float
    delivery_mode: Literal["roleplay", "literal"]
    roleplay_question: str | None = None  # filled for A+D after one-time conversion


@dataclass(frozen=True)
class EssayCase:
    case_id: str
    title: str
    case_text: str
    turns: tuple[Turn, ...]
    rubric_checkpoints: tuple[tuple[str, ...], ...]
    key_answers: dict[str, str]
    judge_extras: str = ""
    points: float = 20.0
    delivery_mode: Literal["scripted_multiturn"] = "scripted_multiturn"


@dataclass(frozen=True)
class ScenarioCase:
    case_id: str
    title: str
    setup: str
    turns: tuple[Turn, ...]
    rubric_checkpoints: tuple[tuple[str, ...], ...]
    judge_extras: str = ""
    max_extra_turns: int = 0
    points: float = 20.0
    delivery_mode: Literal["scripted_multiturn"] = "scripted_multiturn"


Case = MCQCase | EssayCase | ScenarioCase


def _load_json_dataset(path: Path) -> dict[str, list[dict]]:
    """Return {'A': [...], 'B': [...], 'C': [...], 'D': [...]} from BO_DE_AI_AGENT_DATASET.json.

    A/B/D sections use 'questions' key, C uses 'cases' key — normalize both to a flat list.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    for sec_id, sec in data["sections"].items():
        if "questions" in sec:
            out[sec_id] = list(sec["questions"])
        elif "cases" in sec:
            out[sec_id] = list(sec["cases"])
        else:
            out[sec_id] = []
    return out


_Q_HEADING = re.compile(r"^### Câu\s+(\d+)\.?\s*(.+)$")
_CHOICE = re.compile(r"^([A-D])\.\s*(.+)$")


def _load_md_questions(path: Path) -> dict[int, dict]:
    """Parse DE_THI_NHAN_VIEN.md → {question_id: {question, choices}}.

    Stops accumulating choices for a question once a new ### heading is seen.
    Only emits questions that have all 4 ABCD choices — partial questions
    (e.g. essay Phần C with no choices) are skipped.
    """
    text = path.read_text(encoding="utf-8")
    out: dict[int, dict] = {}
    cur_id: int | None = None
    cur_q: str = ""
    cur_choices: dict[str, str] = {}
    for line in text.splitlines():
        m = _Q_HEADING.match(line)
        if m:
            if cur_id is not None and len(cur_choices) == 4:
                out[cur_id] = {"question": cur_q.strip(), "choices": cur_choices}
            cur_id = int(m.group(1))
            cur_q = m.group(2).strip()
            cur_choices = {}
            continue
        cm = _CHOICE.match(line)
        if cm and cur_id is not None:
            cur_choices[cm.group(1)] = cm.group(2).strip()
            continue
        # accumulate question continuation lines (rare)
        if cur_id is not None and not cur_choices and line.strip():
            cur_q += " " + line.strip()
    if cur_id is not None and len(cur_choices) == 4:
        out[cur_id] = {"question": cur_q.strip(), "choices": cur_choices}
    return out


DEFAULT_DATASET_JSON = Path(__file__).resolve().parents[2] / "docs" / "estate_cert" / "BO_DE_AI_AGENT_DATASET.json"
DEFAULT_QUESTIONS_MD = Path(__file__).resolve().parents[2] / "docs" / "estate_cert" / "DE_THI_NHAN_VIEN.md"
DEFAULT_PERSONAS_DIR = Path(__file__).resolve().parent / "data"


def _build_mcq_cases(
    section: Literal["A", "B", "D"],
    json_questions: list[dict],
    md_questions: dict[int, dict],
    roleplay_lookup: dict[str, str],
) -> list[MCQCase]:
    out: list[MCQCase] = []
    points = 2.0 if section in ("A", "D") else 2.5
    mode: Literal["roleplay", "literal"] = "literal" if section == "B" else "roleplay"
    for q in json_questions:
        case_id = f"{section}-{q['id']}"
        md = md_questions.get(q["id"])
        if md is None:
            continue
        out.append(
            MCQCase(
                case_id=case_id,
                section=section,
                topic=q.get("topic", ""),
                question=md["question"],
                choices=md["choices"],
                correct=q["answer"],
                points=points,
                delivery_mode=mode,
                roleplay_question=roleplay_lookup.get(case_id),
            )
        )
    return out


def _build_essay_cases(personas_dir: Path) -> list[EssayCase]:
    out: list[EssayCase] = []
    for f in sorted((personas_dir / "personas_cases").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append(
            EssayCase(
                case_id=d["case_id"],
                title=d["title"],
                case_text=d["case_text"],
                turns=tuple(Turn(**t) for t in d["turns"]),
                rubric_checkpoints=tuple(tuple(rc) for rc in d["rubric_checkpoints"]),
                key_answers=d.get("key_answers", {}),
                judge_extras=d.get("judge_extras", ""),
            )
        )
    return out


def _build_scenario_cases(personas_dir: Path) -> list[ScenarioCase]:
    out: list[ScenarioCase] = []
    for f in sorted((personas_dir / "personas_scenarios").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append(
            ScenarioCase(
                case_id=d["case_id"],
                title=d["title"],
                setup=d.get("setup", ""),
                turns=tuple(Turn(**t) for t in d["turns"]),
                rubric_checkpoints=tuple(tuple(rc) for rc in d["rubric_checkpoints"]),
                judge_extras=d.get("judge_extras", ""),
                max_extra_turns=d.get("max_extra_turns", 0),
            )
        )
    return out


def _load_roleplay_lookup(personas_dir: Path) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for sec in ("A", "D"):
        f = personas_dir / "personas_mcq" / f"{sec}_questions.json"
        if not f.exists():
            continue
        for entry in json.loads(f.read_text(encoding="utf-8")):
            lookup[entry["case_id"]] = entry["roleplay_question"]
    return lookup


def load_all(
    *,
    dataset_json: Path = DEFAULT_DATASET_JSON,
    questions_md: Path = DEFAULT_QUESTIONS_MD,
    personas_dir: Path = DEFAULT_PERSONAS_DIR,
) -> list[Case]:
    sections = _load_json_dataset(dataset_json)
    md = _load_md_questions(questions_md)
    rp = _load_roleplay_lookup(personas_dir)

    cases: list[Case] = []
    cases += _build_mcq_cases("A", sections["A"], md, rp)
    cases += _build_mcq_cases("B", sections["B"], md, rp)
    cases += _build_mcq_cases("D", sections["D"], md, rp)
    cases += _build_essay_cases(personas_dir)
    cases += _build_scenario_cases(personas_dir)
    return cases
