# tests/unit/unified/test_escalation_summary.py
import asyncio

import pytest


@pytest.fixture(autouse=True)
def _don_set_task():
    from noble_agent.agent.summary import escalation_summary as es

    es._bg_tasks.clear()
    yield
    es._bg_tasks.clear()


def _lich_su():
    return [
        {"role": "user", "content": "anh mua căn ở Sunshine Green Iconic rồi"},
        {"role": "assistant", "content": "Dạ em nghe ạ"},
        {"role": "user", "content": "giờ hỏi thủ tục sổ hồng thế nào"},
    ]


@pytest.mark.asyncio
async def test_ghi_summary_vao_dung_dong(monkeypatch):
    from noble_agent.agent.summary import escalation_summary as es

    ghi: dict = {}

    async def _llm_gia(prompt, **kw):
        ghi["prompt"] = prompt
        return "Khách đã mua căn tại SGI, cần hướng dẫn làm sổ hồng."

    async def _luu_gia(escalation_id, summary):
        ghi["id"] = escalation_id
        ghi["summary"] = summary

    monkeypatch.setattr(es, "_call_llm", _llm_gia)
    monkeypatch.setattr(es, "save_escalation_summary", _luu_gia)

    task = es.spawn_escalation_summary(
        12,
        history_snapshot=_lich_su(),
        customer={"full_name": "Nguyễn Văn Nam", "project_interest": "SGI"},
        reason="khách hỏi sổ hồng",
    )
    await task

    assert ghi["id"] == 12
    assert ghi["summary"].startswith("Khách đã mua")
    assert "sổ hồng" in ghi["prompt"], "prompt phải chứa hội thoại"
    assert "khách hỏi sổ hồng" in ghi["prompt"], "prompt phải chứa lý do chuyển"


@pytest.mark.asyncio
async def test_llm_rong_thi_khong_update(monkeypatch):
    """LLM hỏng → giữ nguyên chuỗi cơ học đã ghi lúc INSERT."""
    from noble_agent.agent.summary import escalation_summary as es

    da_goi = False

    async def _llm_rong(prompt, **kw):
        return "   "

    async def _luu_gia(escalation_id, summary):
        nonlocal da_goi
        da_goi = True

    monkeypatch.setattr(es, "_call_llm", _llm_rong)
    monkeypatch.setattr(es, "save_escalation_summary", _luu_gia)

    await es.spawn_escalation_summary(12, history_snapshot=_lich_su(), customer={}, reason="")
    assert not da_goi


@pytest.mark.asyncio
async def test_task_duoc_giu_strong_ref_roi_tu_don(monkeypatch):
    """asyncio chỉ giữ weakref — task không có strong-ref bị GC nuốt giữa chừng."""
    from noble_agent.agent.summary import escalation_summary as es

    cho = asyncio.Event()

    async def _llm_cham(prompt, **kw):
        await cho.wait()
        return "xong"

    async def _luu_gia(escalation_id, summary):
        return None

    monkeypatch.setattr(es, "_call_llm", _llm_cham)
    monkeypatch.setattr(es, "save_escalation_summary", _luu_gia)

    task = es.spawn_escalation_summary(12, history_snapshot=_lich_su(), customer={}, reason="")
    await asyncio.sleep(0)
    assert task in es._bg_tasks

    cho.set()
    await task
    await asyncio.sleep(0)
    assert task not in es._bg_tasks, "xong thì phải tự gỡ khỏi set"


@pytest.mark.asyncio
async def test_khong_co_id_thi_khong_ban_task(monkeypatch):
    from noble_agent.agent.summary import escalation_summary as es

    assert es.spawn_escalation_summary(None, history_snapshot=[], customer={}, reason="") is None
    assert not es._bg_tasks


@pytest.mark.asyncio
async def test_llm_nem_loi_thi_nuot(monkeypatch):
    """Task nền hỏng không được nổi lên thành unhandled exception."""
    from noble_agent.agent.summary import escalation_summary as es

    async def _llm_no(prompt, **kw):
        raise RuntimeError("provider chết")

    monkeypatch.setattr(es, "_call_llm", _llm_no)

    await es.spawn_escalation_summary(12, history_snapshot=_lich_su(), customer={}, reason="")
