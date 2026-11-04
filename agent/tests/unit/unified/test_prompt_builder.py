from datetime import UTC, datetime

import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.prompts.builder import build_system_prompt, render_customer_block
from noble_agent.data import db_project_registry
from noble_agent.storage.models import Customer, ThreadSummary
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR


@pytest.fixture
def agent():
    return load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)


@pytest.fixture(autouse=True)
def _clean_registry_cache():
    yield
    db_project_registry.set_cache_for_tests(None)


def test_prompt_with_empty_customer_no_summary(agent):
    prompt = build_system_prompt(agent, Customer(), None)
    assert "Luna" in prompt
    assert "Operational Protocol" in prompt
    assert "Hôm nay là" in prompt
    assert "Tên:" not in prompt
    assert "Tóm tắt các turn trước" not in prompt


def test_prompt_with_customer_data(agent):
    prompt = build_system_prompt(
        agent,
        Customer(name="Hùng", phone="0901234567", project_interest="NCLB"),
        None,
    )
    assert "Hùng" in prompt
    assert "0901234567" in prompt
    assert "NCLB" in prompt


def test_prompt_has_no_project_table(agent):
    """The full-roster project table was removed from the system prompt — Luna
    resolves project codes per-turn via the find_project tool instead."""
    db_project_registry.set_cache_for_tests(
        {
            "NCLB": {"code": "NCLB", "name": "Noble Crystal Long Biên", "region": "Long Biên", "type": "Căn hộ"},
        }
    )
    prompt = build_system_prompt(agent, Customer(), None)
    assert "Danh mục dự án" not in prompt
    assert "- NCLB — Noble Crystal Long Biên — Long Biên — Căn hộ" not in prompt


def test_prompt_with_summary(agent):
    summary = ThreadSummary(
        text="Khách Hùng đã hỏi giá NCLB và đặt lịch tham quan thứ Bảy.",
        covers_turns=6,
        updated_at=datetime.now(UTC),
    )
    prompt = build_system_prompt(agent, Customer(name="Hùng"), summary)
    assert "Tóm tắt các turn trước" in prompt
    assert "đặt lịch tham quan thứ Bảy" in prompt


def test_render_customer_block_standalone(agent):
    block = render_customer_block(agent, Customer(name="Hùng", phone="0901234567"))
    assert "Hùng" in block
    assert "0901234567" in block


def test_build_uses_frozen_customer_block_verbatim(agent):
    # A frozen block from a DIFFERENT customer must win over the live customer.
    frozen = render_customer_block(agent, Customer(name="Minh", phone="0912345678"))
    prompt = build_system_prompt(
        agent,
        Customer(name="Hùng", phone="0901234567"),
        None,
        customer_block=frozen,
    )
    assert "Minh" in prompt
    assert "0912345678" in prompt
    assert "Hùng" not in prompt  # live customer ignored when block is frozen
