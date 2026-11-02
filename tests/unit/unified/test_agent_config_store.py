import pytest

from noble_agent.storage import agent_config_store as acs
from noble_agent.storage.agent_config_store import read_published_config


class _FakeTxn:
    async def __aenter__(self): return None
    async def __aexit__(self, *a): return False


class _FakeConn:
    def __init__(self, row): self._row = row
    def transaction(self): return _FakeTxn()
    async def execute(self, *a): return None
    async def fetchrow(self, *a): return self._row


class _FakeAcq:
    def __init__(self, conn): self._c = conn
    async def __aenter__(self): return self._c
    async def __aexit__(self, *a): return False


class _FakePool:
    def __init__(self, row): self._conn = _FakeConn(row)
    def acquire(self): return _FakeAcq(self._conn)


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(acs, "_CACHE_DIR", tmp_path)


def _flat_row(**over):
    row = {
        "name": "Luna", "brand_name": "", "self_pronoun": "", "customer_pronoun": "",
        "greeting": "", "scope_does": "", "scope_does_not": "", "refusal_line": "",
        "departments": "[]", "tone": "than_thien", "reply_length": "trung_binh",
        "skills": "[]", "version": 1,
    }
    row.update(over)
    return row


async def test_reads_flat_row_and_decodes_jsonb_columns():
    # departments/skills come back from asyncpg as jsonb STRINGS → decoded to lists.
    pool = _FakePool(_flat_row(
        version=3, name="Luna",
        departments='[{"ten":"CSKH","khi_nao":"x"}]', skills='["booking"]',
    ))
    pc = await read_published_config("org_a1b2c3d4_x", pool=pool)
    assert pc.version == 3
    assert pc.config["name"] == "Luna"
    assert pc.config["skills"] == ["booking"]
    assert pc.config["departments"] == [{"ten": "CSKH", "khi_nao": "x"}]
    assert "version" not in pc.config           # version lifted out of the config dict


async def test_none_when_no_row():
    pool = _FakePool(None)
    assert await read_published_config("org_a1b2c3d4_x", pool=pool) is None


async def test_serves_last_good_on_db_error(monkeypatch):
    ok = _FakePool(_flat_row(version=5, name="Cached"))
    assert (await read_published_config("org_a1b2c3d4_x", pool=ok)).version == 5   # writes last-good

    async def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(acs, "_read_from_db", _boom)
    pc = await read_published_config("org_a1b2c3d4_x")     # DB errors → last-good
    assert pc.version == 5 and pc.config["name"] == "Cached"


def test_parse_config_doc_tts_normalization():
    from noble_agent.agent.agent_config import parse_config

    cfg = parse_config({"name": "Mai", "tts_normalization": {"NCLB": "Noble Crystal Long Biên"}})

    assert cfg.tts_normalization == {"NCLB": "Noble Crystal Long Biên"}


def test_parse_config_tu_dien_thieu_thanh_dict_rong():
    from noble_agent.agent.agent_config import parse_config

    assert parse_config({"name": "Mai"}).tts_normalization == {}


def test_parse_config_tu_dien_sai_kieu_thanh_dict_rong():
    """Cột này là OBJECT, khác `departments`/`skills` là MẢNG. `_decode(...) or []` biến
    `{}` thành `[]` vì `{}` là falsy — nếu ai đó xếp cột này vào `_JSON_COLUMNS` thì
    `parse_config` nhận list ở chỗ nó chờ dict, và bài này đỏ."""
    from noble_agent.agent.agent_config import parse_config

    assert parse_config({"name": "Mai", "tts_normalization": []}).tts_normalization == {}


def test_parse_config_bo_muc_khong_phai_chuoi():
    from noble_agent.agent.agent_config import parse_config

    cfg = parse_config({"name": "Mai", "tts_normalization": {"NCLB": 12, "SSLC": "Sunshine"}})

    assert cfg.tts_normalization == {"SSLC": "Sunshine"}


def test_cot_tts_normalization_khong_nam_trong_JSON_COLUMNS():
    """Cổng cấu trúc: `_JSON_COLUMNS` giải mã bằng `or []`. Xếp một cột OBJECT vào đó là
    biến từ điển rỗng thành `[]` — không lỗi nào phát ra, agent chỉ đọc sai."""
    from noble_agent.storage.agent_config_store import (
        _COLUMNS,
        _JSON_COLUMNS,
        _JSON_OBJECT_COLUMNS,
    )

    assert "tts_normalization" in _COLUMNS
    assert "tts_normalization" in _JSON_OBJECT_COLUMNS
    assert "tts_normalization" not in _JSON_COLUMNS
