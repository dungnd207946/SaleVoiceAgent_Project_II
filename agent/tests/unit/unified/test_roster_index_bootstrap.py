"""Index tên dự án phải được dựng kể cả khi hồ sơ khách đã được seed sẵn.

Bối cảnh (đo thật 2026-08-06, gateway + worker thật): `find_project` trả
`"Danh mục dự án chưa sẵn sàng."` cho MỌI phiên đi qua gateway. Mũi dò tại chỗ cho thấy
`_INDEX_BY_TENANT` rỗng — `set_index` chưa từng được gọi, không phải sai tenant, không
phải warm lỗi.

Nguyên nhân: `facade.set_customer_fields` CỐ Ý đặt `_profile_loaded=True` để bootstrap
lượt-đầu không ghi đè danh tính người dùng nhập tay, và gateway gửi `set_customer` cho
mọi kết nối (`chat_proxy.first_messages`). Nhưng cùng khối `_profile_loaded` đó còn chứa
việc làm mới danh mục dự án + dựng index — hai thứ chẳng liên quan gì tới danh tính khách,
chỉ tình cờ nằm chung. Bỏ qua khối = mất luôn index.

Đường app NobleX (`app_session` provisioning) seed danh tính bằng đúng cơ chế đó, nên nó
dính y hệt. Triệu chứng che mắt: index là biến toàn cục theo process, nên chỉ cần MỘT phiên
nào đó không seed danh tính là mọi phiên sau đều thấy index — lỗi trông như chập chờn.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.agent.tools import find_project
from noble_agent.config import UnifiedSettings
from noble_agent.data import db_project_registry
from noble_agent.storage.models import Customer, Meta, State
from noble_agent.storage.repo import StateRepo
from noble_agent.tenant.current import use_tenant
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR

TENANT = "t_roster"


class _Sink:
    async def on_token(self, t): ...
    async def on_tool_start(self, name, args): ...
    async def on_tool_done(self, name, result): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


@pytest.fixture
async def repo():
    r = fakeredis.aioredis.FakeRedis()
    yield StateRepo(redis_client=r, ttl_seconds=3600)
    await r.aclose()


@pytest.fixture
def runner(repo):
    llm = AsyncMock()
    llm.stream_completion.return_value = ("ok", [])
    return TurnRunner(
        repo=repo,
        agent_def=load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS),
        llm=llm,
        rag=None,
        settings=UnifiedSettings(USE_UNIFIED_AGENT=True),
    )


@pytest.fixture(autouse=True)
def roster():
    """Danh mục giả + dọn index của tenant test giữa các case (index là biến toàn cục)."""
    db_project_registry.set_cache_for_tests(
        {"NPLB": {"code": "NPLB", "name": "Noble Palace Long Biên", "region": "Hà Nội", "type": "biet_thu"}}
    )
    find_project.set_index(None, tenant=TENANT)
    yield
    db_project_registry.set_cache_for_tests(None)
    find_project.set_index(None, tenant=TENANT)


async def _seed(repo, sid, scratchpad):
    now = datetime.now(UTC)
    await repo.save_all(
        sid,
        Meta(session_id=sid, started_at=now, last_active=now),
        Customer(),
        State(scratchpad=scratchpad),
    )


async def test_ho_so_seed_san_van_dung_index(repo, runner):
    """Cổng của lỗi: `_profile_loaded` đã bật (như sau `set_customer`) mà index vẫn phải có.

    Trước bản vá, hai dòng warm+build nằm TRONG khối `if not _profile_loaded`, nên case
    này để `_INDEX_BY_TENANT` rỗng và `find_project` trả "chưa sẵn sàng".
    """
    await _seed(repo, "sid-seeded", {"_profile_loaded": True, "customer_block": "## Hồ sơ"})

    with use_tenant(TENANT):
        assert find_project.get_index() is None, "tiền đề: chưa có index"
        await runner.handle_turn("sid-seeded", "dự án Noble Palace Long Biên", _Sink())
        assert find_project.get_index() is not None, "hồ sơ seed sẵn KHÔNG được làm mất danh mục dự án"


async def test_phien_binh_thuong_van_dung_index(repo, runner):
    """Đường cũ không được hỏng: phiên chưa seed gì vẫn dựng index như trước."""
    await _seed(repo, "sid-fresh", {})

    with use_tenant(TENANT):
        await runner.handle_turn("sid-fresh", "xin chào", _Sink())
        assert find_project.get_index() is not None


async def test_chi_dung_mot_lan_moi_phien(repo, runner, monkeypatch):
    """Dựng index là việc O(số dự án); lượt thứ hai trong cùng phiên không được làm lại.

    Neo chi phí, không chỉ tính đúng — nếu bỏ cờ và dựng lại mỗi lượt thì test này đỏ.
    """
    from noble_agent.agent import orchestrator

    dem = {"n": 0}
    goc = orchestrator._build_project_index

    def dem_build():
        dem["n"] += 1
        goc()

    monkeypatch.setattr(orchestrator, "_build_project_index", dem_build)
    await _seed(repo, "sid-twice", {})

    with use_tenant(TENANT):
        await runner.handle_turn("sid-twice", "lượt 1", _Sink())
        await runner.handle_turn("sid-twice", "lượt 2", _Sink())

    assert dem["n"] == 1, f"dựng index {dem['n']} lần cho 2 lượt — phải đúng 1"


async def test_process_moi_phai_dung_lai_index_du_phien_da_bat_co(repo, runner):
    """Cổng của lỗi 2026-08-25: cờ `_roster_loaded` sống trong Redis (theo PHIÊN), còn index
    sống trong RAM (theo PROCESS). Process restart (deploy/crash, hay `chat_repl --ask` mỗi
    lần một process) rồi phiên cũ resume → cờ đã bật, khối dựng index bị bỏ qua và
    `find_project` trả "Danh mục dự án chưa sẵn sàng" cho tới khi một phiên MỚI dựng hộ.
    """
    await _seed(repo, "sid-resumed", {"_roster_loaded": True})

    with use_tenant(TENANT):
        assert find_project.get_index() is None, "tiền đề: process vừa khởi động, chưa có index"
        await runner.handle_turn("sid-resumed", "dự án Noble Palace Long Biên", _Sink())
        assert find_project.get_index() is not None, "phiên resume sau restart vẫn phải có index"
