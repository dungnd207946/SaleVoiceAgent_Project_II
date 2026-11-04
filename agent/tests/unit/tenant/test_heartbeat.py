import asyncio

import pytest

from noble_agent.tenant import heartbeat as HB
from noble_agent.tenant import version_resolver as VR
from noble_agent.tenant.store import Bundle, FakeTenantStore, TenantMeta, VersionInfo, bundle_hash

ISO = "2026-07-30T04:03:53Z"


def _pub_bundle(tid, soul="one"):
    mtext = f'tenant_id="{tid}"\ndata_source="nbx"\npersona_dir="persona"\n[tools]\nenabled=["escalate"]\n'
    files = {
        "persona/SOUL.md": soul,
        "persona/RULES.md": "escalate",
        "persona/PROMPT_TEMPLATE.md": "x",
        "persona/CUSTOMER_PROFILE.md": "x",
        "persona/config.json": "{}",
    }
    return mtext, files, bundle_hash(mtext, files)


def _add_version(s, tid, n, soul):
    mtext, files, bh = _pub_bundle(tid, soul=soul)
    meta = TenantMeta(tid, "active", n, bh, published_version=n, latest_version=n)
    s.write_version_bundle(tid, n, Bundle(tid, mtext, files, meta), VersionInfo(tid, n, bh))


def _versioned_store(tid="tt"):
    s = FakeTenantStore()
    _add_version(s, tid, 1, "one")
    s.write_pointer(tid, 1)
    return s


def _legacy_store(tid="lg"):
    s = FakeTenantStore()
    mtext, files, bh = _pub_bundle(tid)
    s.write_bundle(Bundle(tid, mtext, files, TenantMeta(tid, "active", 1, bh)))  # in-place, no pointer
    return s


class _S:
    noble_config_poll_sec = 0.0
    tenant_materialize_dir = "/x"
    heartbeat_sec = 20.0
    tenant_id = "tt"


async def _ok_build(_version):
    return None


def _emitter(store, tid="tt", build_fn=None, now_iso=None):
    VR.reset_for_tests()
    return HB.HeartbeatEmitter(
        store, _S(), tid, build_fn=build_fn or _ok_build, now_iso=now_iso or (lambda: ISO)
    )


# ── pure shape ──────────────────────────────────────────────────────────────
def test_build_heartbeat_shape():
    doc = HB.build_heartbeat("tt", 12, 12, "serving", None, "START", "NOW")
    assert doc == {
        "tenant_id": "tt",
        "running_version": 12,
        "published_version_seen": 12,
        "status_hint": "serving",
        "last_error": None,
        "started_at": "START",
        "ts": "NOW",
    }


# ── versioned healthy ───────────────────────────────────────────────────────
async def test_beat_versioned_serving_and_writes():
    s = _versioned_store()
    em = _emitter(s)
    doc = await em.beat()
    assert doc["status_hint"] == "serving"
    assert doc["running_version"] == 1 and doc["published_version_seen"] == 1
    assert doc["last_error"] is None
    assert s.read_heartbeat("tt") == doc  # persisted to the store


async def test_beat_advances_running_on_publish():
    s = _versioned_store()
    built = []

    async def bf(v):
        built.append(v)

    em = _emitter(s, build_fn=bf)
    await em.beat()  # serving v1
    _add_version(s, "tt", 2, "two")
    s.write_pointer("tt", 2)
    doc = await em.beat()
    assert doc["running_version"] == 2 and doc["published_version_seen"] == 2
    assert doc["status_hint"] == "serving"
    assert built == [1, 2]


async def test_beat_checksum_error_is_degraded_and_keeps_running():
    s = _versioned_store()
    em = _emitter(s)
    await em.beat()  # running=1
    _add_version(s, "tt", 2, "two")
    s.write_pointer("tt", 2)

    async def boom(_v):
        raise VR.ChecksumError("v2: hash mismatch")

    em._build_fn = boom
    doc = await em.beat()
    assert doc["status_hint"] == "degraded"
    assert doc["running_version"] == 1  # E04: keep last good
    assert doc["published_version_seen"] == 2
    assert doc["last_error"]["code"] == "checksum_mismatch"
    assert doc["last_error"]["ts"] == ISO


async def test_beat_build_error_is_degraded():
    s = _versioned_store()

    async def boom(_v):
        raise RuntimeError("provider down")

    em = _emitter(s, build_fn=boom)
    doc = await em.beat()
    assert doc["status_hint"] == "degraded"
    assert doc["last_error"]["code"] == "load_error"
    assert doc["running_version"] == 0  # never built


# ── legacy in-place ─────────────────────────────────────────────────────────
async def test_beat_legacy_inplace_serving_without_build():
    s = _legacy_store("lg")
    calls = []

    async def bf(v):
        calls.append(v)

    em = HB.HeartbeatEmitter(s, _S(), "lg", build_fn=bf, now_iso=lambda: ISO)
    doc = await em.beat()
    assert doc["status_hint"] == "serving"
    assert doc["running_version"] == 1 and doc["published_version_seen"] == 1
    assert calls == []  # legacy path never materializes a version


# ── absent tenant ───────────────────────────────────────────────────────────
async def test_beat_absent_tenant_is_degraded():
    s = FakeTenantStore()
    em = HB.HeartbeatEmitter(s, _S(), "ghost", build_fn=_ok_build, now_iso=lambda: ISO)
    doc = await em.beat()
    assert doc["status_hint"] == "degraded"
    assert doc["last_error"]["code"] == "tenant_absent"


# ── store outage on read → skip (no write) ──────────────────────────────────
async def test_beat_store_down_skips_write():
    s = _versioned_store()
    em = _emitter(s)

    def down(_t):
        raise RuntimeError("minio down")

    s.read_pointer = down
    doc = await em.beat()
    assert doc is None
    assert s.read_heartbeat("tt") is None


# ── started_at is fixed; ts advances ────────────────────────────────────────
async def test_started_at_stable_ts_advances():
    s = _versioned_store()
    ticks = iter(["T0", "T1", "T2", "T3"])
    em = _emitter(s, now_iso=lambda: next(ticks))
    d1 = await em.beat()
    d2 = await em.beat()
    assert d1["started_at"] == d2["started_at"] == "T0"  # captured once at construct
    assert d1["ts"] == "T1" and d2["ts"] == "T2"


# ── shared gate + materialize-only build_fn (LiveKit dispatch process) ──────
class _GateS:
    def __init__(self, store_on, hb_on):
        self.tenant_store_enabled = store_on
        self.heartbeat_enabled = hb_on


def test_should_emit_gate():
    assert HB.should_emit(_GateS(True, True)) is True
    assert HB.should_emit(_GateS(False, True)) is False  # no store → nowhere to write
    assert HB.should_emit(_GateS(True, False)) is False  # explicitly disabled


def test_should_emit_db_mode_without_store():
    from types import SimpleNamespace

    s = SimpleNamespace(agent_config_source="db", tenant_store_enabled=False, heartbeat_enabled=True)
    assert HB.should_emit(s) is True


async def test_materialize_build_fn_writes_version_to_disk(tmp_path):
    VR.reset_for_tests()
    s = _versioned_store()

    class _MS:
        tenant_materialize_dir = str(tmp_path)

    fn = HB.build_materialize_fn(s, _MS(), "tt")
    await fn(1)
    # materialize+checksum only — no LLM runner, no context build — just the disk copy
    assert (tmp_path / "tt" / "versions" / "1" / "persona" / "SOUL.md").read_text() == "one"


async def test_materialize_build_fn_propagates_checksum_error(tmp_path, monkeypatch):
    VR.reset_for_tests()
    s = _versioned_store()
    good = s.read_version_bundle("tt", 1)
    from noble_agent.tenant.store import Bundle

    bad_meta = good.meta.__class__(**{**good.meta.__dict__, "bundle_hash": "sha256:WRONG"})
    monkeypatch.setattr(s, "read_version_bundle", lambda t, n: Bundle("tt", good.manifest_text, good.files, bad_meta))

    class _MS:
        tenant_materialize_dir = str(tmp_path)

    fn = HB.build_materialize_fn(s, _MS(), "tt")
    with pytest.raises(VR.ChecksumError):
        await fn(1)


# ── run loop beats then stops cleanly ───────────────────────────────────────
async def test_run_loop_beats_then_stops():
    s = _versioned_store()
    em = _emitter(s)
    em._interval = 0.01
    stop = asyncio.Event()
    task = asyncio.create_task(em.run(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert s.read_heartbeat("tt") is not None
    assert task.done() and task.exception() is None


# ── HeartbeatSupervisor (multi-tenant) ──────────────────────────────────────
def _multi_store(*tids):
    s = FakeTenantStore()
    for tid in tids:
        _add_version(s, tid, 1, "one")
        s.write_pointer(tid, 1)
    return s


def _supervisor(store, **kw):
    VR.reset_for_tests()
    kw.setdefault("build_fn_factory", lambda tid: _ok_build)
    kw.setdefault("now_iso", lambda: ISO)
    return HB.HeartbeatSupervisor(store, _S(), **kw)


async def test_supervisor_emits_one_heartbeat_per_active_tenant():
    s = _multi_store("t1", "t2", "t3")
    sup = _supervisor(s)
    await sup._cycle()
    assert set(s._heartbeats) == {"t1", "t2", "t3"}
    assert s._heartbeats["t2"]["status_hint"] == "serving"


async def test_supervisor_skips_non_active_tenants():
    s = _multi_store("t1", "t2")
    s.write_status("t2", "disabled")
    sup = _supervisor(s)
    await sup._cycle()
    assert set(s._heartbeats) == {"t1"}  # disabled tenant gets no beat


async def test_supervisor_reconcile_drops_tenant_when_deactivated():
    s = _multi_store("t1", "t2")
    sup = _supervisor(s)
    await sup._cycle()
    assert set(sup._emitters) == {"t1", "t2"}
    s.write_status("t2", "disabled")
    await sup._cycle()
    assert set(sup._emitters) == {"t1"}  # emitter for t2 dropped


async def test_supervisor_store_error_keeps_current_set(monkeypatch):
    s = _multi_store("t1")
    sup = _supervisor(s)
    await sup._cycle()  # establishes {"t1"}
    monkeypatch.setattr(s, "list_ids", lambda: (_ for _ in ()).throw(RuntimeError("store down")))
    await sup._cycle()  # must not crash; keeps t1 and still beats it
    assert set(sup._emitters) == {"t1"}


async def test_supervisor_emitters_keep_independent_state():
    s = _multi_store("t1", "t2")
    sup = _supervisor(s)
    await sup._cycle()
    assert sup._emitters["t1"] is not sup._emitters["t2"]
    assert sup._emitters["t1"]._tenant == "t1"
    assert sup._emitters["t2"]._tenant == "t2"
