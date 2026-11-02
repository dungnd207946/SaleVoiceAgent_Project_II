"""Cảnh báo «tenant im lặng» — nửa cuối cùng của §7.

Đối soát bắt được `delete` bị rơi, nhưng nó do BÊN KHÁCH kích hoạt. Job của họ
chết ⇒ §7 tắt và không ai biết. Bộ bài này canh đúng bốn nhánh quyết định của
`jobs.handle_im_lang`, và một bài cho việc đóng dấu nhịp tim.

⚠️ Bài quan trọng nhất KHÔNG phải bài «phát hiện được» mà là ba bài «KHÔNG kêu»:
một kênh cảnh báo kêu sai là kênh bị tắt, và lúc đó nó thua cả việc không có.
"""

from datetime import UTC, datetime

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.ingest import contracts, fanout, jobs, service

pytestmark = pytest.mark.integration

LUC = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
DU_AN = {"name": "Vinhomes Thử"}


@pytest.fixture(autouse=True)
async def _don_job(pool):
    """Dọn job của module này TRƯỚC và SAU mỗi bài.

    ⚠️ Vế SAU mới là vế bắt buộc, và nó do một bài đỏ dạy ra: `fanout` xếp job cho
    MỌI tenant đang hoạt động, còn `core.jobs.run_once` thì nhặt job CŨ NHẤT bất kể
    của ai. Để lại một hàng `queued` là `tests/modules/test_worker.py` nhặt phải
    job của mình và đỏ ở ba bài trông chẳng liên quan — mà chỉ đỏ khi chạy CẢ BỘ,
    không đỏ khi chạy riêng tệp đó.

    Đây đúng lớp lỗi mà `conftest.py` cạnh bên đã cảnh báo cho `tenant_data`; chỗ
    khác nhau là hàng đợi nằm ở `control` nên nó rò sang MODULE khác, không chỉ
    sang bài khác.
    """
    xoa = "DELETE FROM control.jobs WHERE kind = $1"
    await pool.execute(xoa, jobs.KIND_IM_LANG)
    yield
    await pool.execute(xoa, jobs.KIND_IM_LANG)


def _lo(ma: str):
    return contracts.LoNapIn(
        records=[contracts.BanGhiIn(entity="project", externalId=ma, op="upsert", occurredAt=LUC, data=DU_AN)]
    )


def _ke(*ma: str):
    return contracts.BanKeIn(entity="project", records=[contracts.MucBanKe(externalId=m, updatedAt=LUC) for m in ma])


async def _chay(api_pool, tenant_id: str):
    """Chạy handler đúng như worker chạy: trong `tenant_conn` của tenant đó."""
    async with tenant_conn(api_pool, tenant_id) as conn:
        return await jobs.handle_im_lang(conn, {})


async def _dem_canh_bao(pool, tenant_id: str) -> int:
    return await pool.fetchval(
        "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = $2",
        tenant_id,
        jobs.HANH_DONG,
    )


async def _lui_moc(pool, tenant_id: str, ngay: int) -> None:
    """Đẩy mốc nhận bản kê lùi lại N ngày — mô phỏng adapter ngừng chạy."""
    await pool.execute(
        "UPDATE tenant_data.ingest_manifest_runs SET nhan_luc = now() - ($2 || ' days')::interval WHERE tenant_id = $1",
        tenant_id,
        str(ngay),
    )


async def _lui_ca_dong(pool, tenant_id: str, ngay: int) -> None:
    """Dịch CẢ mốc bản kê LẪN nhật ký lùi N ngày — giữ nguyên thứ tự tương đối.

    Khác `_lui_moc` ở đúng điểm quyết định: nó không tạo ra trạng thái «bản kê xảy
    ra trước một cảnh báo đã ghi», thứ không tồn tại ngoài đời. Dùng khi bài cần
    nhiều mốc thời gian nối tiếp nhau.
    """
    await pool.execute(
        "UPDATE tenant_data.ingest_manifest_runs SET nhan_luc = nhan_luc - ($2 || ' days')::interval "
        "WHERE tenant_id = $1",
        tenant_id,
        str(ngay),
    )
    await pool.execute(
        "UPDATE control.audit_log SET luc = luc - ($2 || ' days')::interval "
        "WHERE tenant_id = $1 AND hanh_dong LIKE 'ingest.%'",
        tenant_id,
        str(ngay),
    )


# ─── Đóng dấu nhịp tim ──────────────────────────────────────────────────────


async def test_doi_soat_de_lai_dau_vet(api_pool, hai_tenant):
    """Trước bản này một lượt đối soát KHỚP HOÀN TOÀN để lại đúng KHÔNG GÌ —
    `nhat_ky` chỉ ghi khi có cờ MỚI. Nên «chạy mỗi đêm, luôn khớp» và «ngừng chạy
    ba tuần trước» trông giống hệt nhau trong DB. Đây là dấu vết phân biệt chúng."""
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1"), dry_run=False)
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("P1"))

    async with tenant_conn(api_pool, a) as conn:
        hang = await conn.fetchrow(
            "SELECT entity, so_muc, nhan_luc FROM tenant_data.ingest_manifest_runs WHERE tenant_id = $1", a
        )
    assert hang["entity"] == "project"
    assert hang["so_muc"] == 1
    assert hang["nhan_luc"] is not None


async def test_dau_vet_ghi_ca_khi_doi_soat_phat_hien_lech(api_pool, hai_tenant):
    """Nhịp tim nói «adapter còn sống», KHÔNG nói «dữ liệu khớp».

    Đóng dấu sau phép so thì một tenant ĐANG chạy đối soát mà kết quả xấu sẽ vừa
    bị báo mất dữ liệu vừa bị báo im lặng — hai cảnh báo cho một sự việc, và cái
    thứ hai sai.
    """
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1"), dry_run=False)
    ra = await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke())  # kê RỖNG ⇒ P1 nghi mất tích

    assert ra.soNghiMatTich == 1
    async with tenant_conn(api_pool, a) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_manifest_runs WHERE tenant_id=$1", a) == 1


async def test_moi_thuc_the_mot_hang_rieng(api_pool, hai_tenant):
    """Khách đối soát `project` mà quên `unit` cũng là một kiểu chết một nửa —
    dữ liệu để phân biệt phải có sẵn từ đầu, kể cả khi cảnh báo chưa dùng tới."""
    a, _ = hai_tenant
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke())
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=contracts.BanKeIn(entity="unit", records=[]))
    async with tenant_conn(api_pool, a) as conn:
        ds = [
            r["entity"]
            for r in await conn.fetch(
                "SELECT entity FROM tenant_data.ingest_manifest_runs WHERE tenant_id=$1 ORDER BY 1", a
            )
        ]
    assert ds == ["project", "unit"]


# ─── Ba nhánh KHÔNG được kêu ────────────────────────────────────────────────


async def test_tenant_chua_dung_cong_nap_thi_khong_kêu(api_pool, pool, hai_tenant):
    """Workspace chưa đấu nối mà bị nhắc mỗi đêm là cách nhanh nhất để người trực
    tắt kênh cảnh báo — và lúc đó nó thua cả việc không có cảnh báo."""
    a, _ = hai_tenant
    ra = await _chay(api_pool, a)
    assert ra.count == 0
    assert "chưa dùng" in ra.message
    assert await _dem_canh_bao(pool, a) == 0


async def test_doi_soat_gan_day_thi_khong_kêu(api_pool, pool, hai_tenant):
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1"), dry_run=False)
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("P1"))

    ra = await _chay(api_pool, a)
    assert ra.count == 0
    assert await _dem_canh_bao(pool, a) == 0


async def test_dang_im_lang_nhung_da_bao_thi_khong_bao_lai(api_pool, pool, hai_tenant):
    """MỘT cảnh báo mỗi ĐỢT, không phải mỗi đêm.

    Cùng lý lẽ đã dùng cho cờ nghi mất tích: một dòng lặp lại 30 đêm liền là cách
    dạy người trực bỏ qua đúng dòng đó. «Đang im lặng bao lâu rồi» là TRẠNG THÁI,
    đọc từ `ingest_manifest_runs`; nhật ký kể SỰ KIỆN.
    """
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1"), dry_run=False)
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("P1"))
    await _lui_moc(pool, a, 10)

    assert (await _chay(api_pool, a)).count == 1
    assert (await _chay(api_pool, a)).count == 0, "đêm thứ hai không được báo lại"
    assert (await _chay(api_pool, a)).count == 0
    assert await _dem_canh_bao(pool, a) == 1


# ─── Hai nhánh PHẢI kêu ─────────────────────────────────────────────────────


async def test_ngung_doi_soat_qua_tran_thi_kêu(api_pool, pool, hai_tenant):
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1"), dry_run=False)
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("P1"))
    await _lui_moc(pool, a, 10)

    ra = await _chay(api_pool, a)
    assert ra.count == 1
    hang = await pool.fetchrow(
        "SELECT chi_tiet, actor FROM control.audit_log WHERE tenant_id=$1 AND hanh_dong=$2",
        a,
        jobs.HANH_DONG,
    )
    import json

    ct = json.loads(hang["chi_tiet"]) if isinstance(hang["chi_tiet"], str) else hang["chi_tiet"]
    assert hang["actor"] == "cron"
    assert ct["soNgayImLang"] >= 9
    assert ct["banKeGanNhat"] is not None


async def test_day_du_lieu_nhung_chua_bao_gio_doi_soat_thi_kêu(api_pool, pool, hai_tenant):
    """Ca «chưa từng» phải tính là im lặng — một adapter chỉ đẩy `/events` mà
    không bao giờ đối soát đúng là thứ cơ chế này tồn tại để phát hiện."""
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1"), dry_run=False)

    ra = await _chay(api_pool, a)
    assert ra.count == 1
    assert "chưa từng" in ra.message
    hang = await pool.fetchrow(
        "SELECT chi_tiet FROM control.audit_log WHERE tenant_id=$1 AND hanh_dong=$2", a, jobs.HANH_DONG
    )
    import json

    ct = json.loads(hang["chi_tiet"]) if isinstance(hang["chi_tiet"], str) else hang["chi_tiet"]
    assert ct["banKeGanNhat"] is None


async def test_im_lang_roi_chay_lai_roi_im_lang_thi_bao_LAN_NUA(api_pool, pool, hai_tenant):
    """Đợt im lặng THỨ HAI là một sự việc mới, phải báo lại.

    Đây là chỗ dễ sai nhất của luật «một cảnh báo mỗi đợt»: chặn theo «đã từng báo
    chưa» thay vì theo «đã báo cho đợt NÀY chưa» sẽ làm mọi lần chết sau lần đầu
    thành im lặng vĩnh viễn — tức đúng bệnh mà nó chữa.

    ⚠️ Mô phỏng phải giữ đúng THỨ TỰ THẬT của dòng thời gian, và bản đầu của bài
    này thì không: nó chỉ kéo mốc bản kê lùi lại, làm bản kê rơi về TRƯỚC cảnh báo
    đã ghi — một trạng thái không tồn tại ngoài đời (đồng hồ không chạy ngược).
    Bài đỏ, nhưng lỗi nằm ở bài chứ không ở `_da_bao`. Nên `_lui_ca_dong` dịch CẢ
    HAI bảng cùng một lượng, giữ nguyên thứ tự tương đối.
    """
    a, _ = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1"), dry_run=False)

    # T-30: bản kê cuối cùng của đợt một.
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("P1"))
    await _lui_ca_dong(pool, a, 30)
    assert (await _chay(api_pool, a)).count == 1, "đợt một phải được báo"

    # Dịch cả hai lùi 20 ngày ⇒ bản kê ở T-50, cảnh báo đợt một ở T-20.
    # Thứ tự giữ nguyên: bản kê TRƯỚC cảnh báo, đúng như đã xảy ra.
    await _lui_ca_dong(pool, a, 20)

    # Khách sửa cron, chạy lại một lần…
    await service.doi_soat_ban_ke(api_pool, tenant_id=a, ban_ke=_ke("P1"))
    assert (await _chay(api_pool, a)).count == 0, "vừa chạy xong thì bình thường"

    # …rồi lại chết. Bản kê mới lùi 10 ngày, nhưng cảnh báo đợt một vẫn ở T-20,
    # tức TRƯỚC bản kê đó — nên nó không tính cho đợt này.
    await _lui_moc(pool, a, 10)

    assert (await _chay(api_pool, a)).count == 1, "đợt im lặng MỚI phải được báo"
    assert await _dem_canh_bao(pool, a) == 2


# ─── Cách ly và fanout ──────────────────────────────────────────────────────


async def test_canh_bao_cua_A_khong_dinh_sang_B(api_pool, pool, hai_tenant):
    a, b = hai_tenant
    await service.nap_lo(api_pool, tenant_id=a, lo=_lo("P1"), dry_run=False)
    await _chay(api_pool, a)

    assert await _dem_canh_bao(pool, a) == 1
    assert await _dem_canh_bao(pool, b) == 0
    async with tenant_conn(api_pool, b) as conn:
        assert await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_manifest_runs") == 0


async def test_fanout_xep_mot_job_moi_tenant_dang_hoat_dong(pool, hai_tenant):
    """Một job MỖI tenant, không phải một job quét tất cả: `run_once` chạy handler
    trong `tenant_conn`, nên một job «quét mọi tenant» sẽ bị RLS cắt sạch phần còn
    lại — không lỗi, chỉ âm thầm kiểm thiếu."""
    a, b = hai_tenant
    so = await fanout.xep_moi_tenant(pool, kind=jobs.KIND_IM_LANG)

    assert so >= 2
    tt = {
        r["tenant_id"]
        for r in await pool.fetch("SELECT tenant_id FROM control.jobs WHERE kind = $1", jobs.KIND_IM_LANG)
    }
    assert {a, b} <= tt


async def test_fanout_bo_qua_tenant_ngung_hoat_dong(pool, hai_tenant):
    """Workspace suspended không gửi bản kê là ĐÚNG — cảnh báo nó là sinh việc cho
    người trực về một thứ đã được quyết định dừng."""
    a, b = hai_tenant
    await pool.execute("UPDATE control.tenants SET lifecycle = 'suspended' WHERE id = $1", b)
    try:
        await fanout.xep_moi_tenant(pool, kind=jobs.KIND_IM_LANG)
        tt = {
            r["tenant_id"]
            for r in await pool.fetch("SELECT tenant_id FROM control.jobs WHERE kind = $1", jobs.KIND_IM_LANG)
        }
        assert a in tt
        assert b not in tt
    finally:
        await pool.execute("UPDATE control.tenants SET lifecycle = 'active' WHERE id = $1", b)
