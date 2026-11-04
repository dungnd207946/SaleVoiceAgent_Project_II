from pathlib import Path

import pytest

import noble_agent
from noble_agent.config import get_settings
from noble_agent.tenant import loader
from noble_agent.tenant.loader import _context_from_dir


def test_context_from_dir_builds_context():
    d = Path(noble_agent.__file__).resolve().parent / "tenants" / "noble"
    ctx = _context_from_dir("noble", d, is_materialized=False)
    assert ctx.tenant_id == "noble"
    assert "escalate" in ctx.enabled_tools
    assert ctx.persona_dir == (d / "persona").resolve()


def test_context_from_dir_aliases_legacy_tool_names(tmp_path):
    # Bundle bên ngoài còn chở tên tool trước merge 2026-09-07 → loader map sang
    # tool hợp nhất + dedupe, không phụ thuộc bundle được cập nhật cùng lúc.
    d = tmp_path / "t_legacy"
    (d / "persona").mkdir(parents=True)
    (d / "manifest.toml").write_text(
        'tenant_id = "t_legacy"\ndata_source = "pg_kb"\npersona_dir = "persona"\n'
        '[tools]\nenabled = ["recommend_units", "search_units", "get_project_overview", "check_inventory"]\n',
        encoding="utf-8",
    )
    ctx = _context_from_dir("t_legacy", d, is_materialized=False)
    assert set(ctx.enabled_tools) == {"search_units", "discover_projects", "analyze_projects"}
    assert list(ctx.enabled_tools).count("search_units") == 1


def test_load_noble_manifest_matches_current_defaults():
    ctx = loader.load_tenant("noble", get_settings())
    assert ctx.tenant_id == "noble"
    # The Postgres KB is the sole provider; the manifest MUST mirror the default.
    assert ctx.data_source == "pg_kb"
    assert ctx.persona_dir.name == "persona"
    assert ctx.persona_dir.is_absolute()
    assert set(ctx.enabled_tools) == {
        "find_project", "update_customer", "kb_search", "discover_projects",
        "search_units", "booking", "escalate", "send_media",
        "get_document", "analyze_projects", "service_customer",
    }
    assert ctx.rankers == frozenset({"feng_shui"})
    assert ctx.media_channel == "noblex_app"
    assert ctx.brand == {"company": "Noble", "app_name": "NobleX"}


def test_resolve_tenant_dir_roi_ve_in_wheel_khi_store_khong_co(monkeypatch):
    """`noble` KHÔNG có trong store ⇒ rơi về bundle in-wheel.

    ĐỔI NGHĨA 2026-08-15. Bản cũ tên `..._legacy_id_skips_store` và khẳng định
    store KHÔNG ĐƯỢC hỏi tới: lúc đó `is_valid_tenant_id` đòi tiền tố `org_`, nên
    một id phẳng như `noble` bị loại từ vòng ngoài — và bắt buộc phải bị loại, vì
    `_prefix()` sẽ gọi `org_of()` và ném ValueError.

    Tiền tố org đã bỏ (xem `identity.py`), nên `noble` giờ là id HỢP LỆ và store
    ĐƯỢC hỏi. Cái phải neo lại là kết quả: `read_meta` trả None ⇒ rơi về dir
    in-wheel, không nổ.
    """
    da_hoi = []

    class _StoreRong:
        def read_meta(self, tenant_id):
            da_hoi.append(tenant_id)
            return None

    monkeypatch.setattr(loader, "_build_store", lambda _s: _StoreRong())

    class _S:
        tenant_store_enabled = True

    d, is_mat = loader._resolve_tenant_dir("noble", _S())
    assert da_hoi == ["noble"], "store phải được hỏi — id phẳng giờ hợp lệ"
    assert d == loader._tenants_root() / "noble"
    assert is_mat is False


def test_unknown_tenant_fails_loud():
    with pytest.raises((FileNotFoundError, ValueError)):
        loader.load_tenant("does_not_exist", get_settings())


def test_missing_required_key_fails_loud(tmp_path, monkeypatch):
    # A fixture tenant dir with a manifest missing [tools].enabled.
    tdir = tmp_path / "tenants" / "broken"
    tdir.mkdir(parents=True)
    (tdir / "manifest.toml").write_text('data_source = "nbx"\npersona_dir = "persona"\n', encoding="utf-8")
    monkeypatch.setattr(loader, "_tenants_root", lambda: tmp_path / "tenants")
    with pytest.raises(ValueError):
        loader.load_tenant("broken", get_settings())


def test_get_tenant_context_is_singleton():
    loader.reset_tenant_context_for_tests()
    a = loader.get_tenant_context()
    b = loader.get_tenant_context()
    assert a is b
    loader.reset_tenant_context_for_tests()


def test_get_tenant_context_keyed_by_current_tenant(monkeypatch):
    from noble_agent.config import reset_settings_for_tests
    from noble_agent.tenant.current import use_tenant
    from noble_agent.tenant.loader import get_tenant_context, reset_tenant_context_for_tests

    monkeypatch.setenv("TENANT_ID", "noble")
    reset_settings_for_tests()
    reset_tenant_context_for_tests()

    with use_tenant("noble"):
        a = get_tenant_context()
    with use_tenant("demo_acme"):
        b = get_tenant_context()

    assert a.tenant_id == "noble"
    assert b.tenant_id == "demo_acme"
    # cached per tenant — same object on second read
    with use_tenant("noble"):
        assert get_tenant_context() is a
