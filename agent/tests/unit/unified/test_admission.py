import pytest

from noble_agent.server.admission import ChatAdmission


@pytest.mark.asyncio
async def test_admits_up_to_cap_then_rejects():
    a = ChatAdmission(max_sessions=2)
    assert await a.try_admit() is True
    assert await a.try_admit() is True
    assert await a.try_admit() is False          # at cap → reject
    assert a.stats()["active"] == 2
    assert a.stats()["rejected"] == 1
    await a.release()
    assert await a.try_admit() is True            # slot freed


@pytest.mark.asyncio
async def test_zero_or_negative_cap_means_unbounded():
    a = ChatAdmission(max_sessions=0)
    for _ in range(50):
        assert await a.try_admit() is True
    assert a.stats()["at_capacity"] is False
