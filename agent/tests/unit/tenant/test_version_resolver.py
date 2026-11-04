import pytest

from noble_agent.tenant import version_resolver as VR
from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta, VersionInfo, bundle_hash


def _pub_bundle(tid, soul):
    mtext = f'tenant_id="{tid}"\ndata_source="nbx"\npersona_dir="persona"\n[tools]\nenabled=["escalate"]\n'
    files = {
        "persona/SOUL.md": soul,
        "persona/RULES.md": "escalate",
        "persona/PROMPT_TEMPLATE.md": "x",
        "persona/CUSTOMER_PROFILE.md": "x",
        "persona/config.json": "{}",
    }
    bh = bundle_hash(mtext, files)
    return mtext, files, bh


def _store_with_v1(tid="tt", soul="one"):
    s = FakeTenantStore()
    mtext, files, bh = _pub_bundle(tid, soul)
    meta = TenantMeta(tid, "active", 1, bh, published_version=1, latest_version=1)
    s.write_version_bundle(tid, 1, Bundle(tid, mtext, files, meta), VersionInfo(tid, 1, bh))
    s.write_pointer(tid, 1)
    return s


def test_materialize_and_build_context(tmp_path):
    VR._context_cache.clear()
    s = _store_with_v1()

    class _S:  # minimal settings
        tenant_materialize_dir = str(tmp_path)

    ctx = VR.context_for_version(s, _S(), "tt", 1)
    assert ctx.tenant_id == "tt" and "escalate" in ctx.enabled_tools
    assert (tmp_path / "tt" / "versions" / "1" / "persona" / "SOUL.md").read_text() == "one"


def test_context_for_version_caches(tmp_path):
    VR._context_cache.clear()
    s = _store_with_v1()

    class _S:
        tenant_materialize_dir = str(tmp_path)

    a = VR.context_for_version(s, _S(), "tt", 1)
    b = VR.context_for_version(s, _S(), "tt", 1)
    assert a is b


def test_checksum_mismatch_raises(tmp_path, monkeypatch):
    s = _store_with_v1()
    # corrupt: return a bundle whose stored hash != content
    good = s.read_version_bundle("tt", 1)
    bad_meta = good.meta.__class__(**{**good.meta.__dict__, "bundle_hash": "sha256:WRONG"})
    monkeypatch.setattr(
        s, "read_version_bundle", lambda t, n: Bundle("tt", good.manifest_text, good.files, bad_meta)
    )
    with pytest.raises(VR.ChecksumError):
        VR.materialize_version(s, "tt", 1, str(tmp_path))


def test_materialize_missing_version_raises(tmp_path):
    s = _store_with_v1()
    with pytest.raises(FileNotFoundError):
        VR.materialize_version(s, "tt", 99, str(tmp_path))


def test_current_version_ttl_and_refresh():
    VR.reset_for_tests()
    s = _store_with_v1()

    class _S:
        noble_config_poll_sec = 100.0
        tenant_materialize_dir = "/x"

    t = [0.0]
    clk = lambda: t[0]  # noqa: E731
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 1
    s.write_pointer("tt", 2)  # publish v2
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 1  # cached (TTL not elapsed)
    t[0] = 200.0
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 2  # refreshed


def test_current_version_store_down_uses_last_good():
    VR.reset_for_tests()
    s = _store_with_v1()

    class _S:
        noble_config_poll_sec = 0.0
        tenant_materialize_dir = "/x"

    clk = lambda: 0.0  # noqa: E731
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 1  # primes last_good

    def boom(t):
        raise RuntimeError("minio down")

    s.read_pointer = boom
    assert VR.current_published_version(s, _S(), "tt", clock=clk) == 1  # E01: last_good


def test_current_version_absent_tenant_fails_loud():
    VR.reset_for_tests()
    s = FakeTenantStore()

    class _S:
        noble_config_poll_sec = 0.0
        tenant_materialize_dir = "/x"

    with pytest.raises(FileNotFoundError):
        VR.current_published_version(s, _S(), "nope", clock=lambda: 0.0)
