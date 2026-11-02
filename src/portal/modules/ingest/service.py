"""Nghiệp vụ của cổng nạp — nhận lô, chiếu, quản trị token.

LUẬT MỘT CÂU CỦA MODULE: **token nói «tôi là tenant nào»; hợp đồng nói «dữ liệu
này có hợp lệ không».** Không gộp hai vai. Token không mang quyền cấu hình được,
và hợp đồng không biết gì về tenant.

── VÌ SAO CHIẾU NGAY TRONG REQUEST, KHÔNG ĐẨY QUA `control.jobs` ────────────
Đã cân nhắc và bỏ. Lô đã bị chặn ở `TRAN_LO` (500 bản ghi), và phép chiếu là một
loạt upsert theo khoá — rẻ. Đổi lại, bên khách biết NGAY bản ghi nào vào được.

LƯU THÔ + CHIẾU LÀ MỘT SAVEPOINT CHO TỪNG BẢN GHI (từ 2026-08-15): chiếu hỏng
thì bản thô cũng không được ghi — bản đang có giữ nguyên `occurred_at` cũ, nên
khách sửa xong đẩy lại NGUYÊN VĂN vẫn được nhận. Bản trước đánh dấu «đã chiếu»
cả khi hỏng rồi dựa vào guard strict-`<` — tức bản ghi hỏng bị khoá vĩnh viễn
ngoài kho trong khi số liệu đếm nó là thành công (review finding #3).

Hàng chưa giải được cha nằm chờ ở `cho_cha_*` và được nhặt ĐÚNG LÚC cha nó chiếu
xong — không có backlog để quét, không có LIMIT để starve (finding #7), không có
lượt đánh-dấu-hàng-loạt để đè lên reset của lô khác (finding #8: hai lô đụng cùng
một bản ghi bị khoá hàng `ON CONFLICT` của chính `ingest_records` serialize).
"""

import json

import asyncpg
from redis.asyncio import Redis

from portal.core import nhat_ky
from portal.core.db.session import tenant_conn
from portal.modules.ingest import bi_mat, chieu, contracts, doi_soat, nhip, repo
from portal.modules.ingest.hop_dong import kiem

TRAN_LOI_TRA_VE = 200

TRAN_LAN_TRUYEN = 2000

# ─── Xác thực token ─────────────────────────────────────────────────────────


async def xac_thuc(
    pool: asyncpg.Pool,
    bearer: str | None,
    *,
    vertical: str,
    redis: Redis,
    cua: str,
    so_lan: int,
    giay: int,
) -> asyncpg.Record | None:
    """`Authorization: Bearer …` → hàng `ingest_tokens`, hoặc `None`.

    `vertical` là lĩnh vực của ENDPOINT đang gọi, và token phải khớp. Đây là chỗ
    DUY NHẤT cưỡng chế lời hứa «token của lĩnh vực này không với sang lĩnh vực
    khác» — đường dẫn `/ingest/<lĩnh vực>/` chỉ ĐẶT TÊN lời hứa đó, không thi hành
    nó. Trước 2026-08-14 không ai so, và nó vô hại chỉ vì `CHECK (vertical IN
    ('realestate'))` khiến giá trị thứ hai chưa tồn tại; ngày `finance` được thêm
    (đã khai sẵn ở `control.tenant_verticals`), một token tài chính sẽ ghi thẳng
    vào KB bất động sản mà không cổng nào đỏ.

    THAM SỐ BẮT BUỘC, không mặc định `contracts.LINH_VUC`: một mặc định nghĩa là
    router của lĩnh vực thứ hai copy-paste được nguyên dòng gọi và âm thầm nhận
    phép kiểm của lĩnh vực thứ nhất — đúng lớp lỗi mà bản vá này đang đóng.

    Lệch lĩnh vực trả `None` như mọi dạng sai khác: một mã cho cả «thiếu header»,
    «token sai» lẫn «token của lĩnh vực khác». Đánh đổi có ý thức — bên khách gõ
    nhầm đường dẫn sẽ đọc «token không hợp lệ» và có thể đi phát lại token vô ích.
    Một mã lỗi riêng đáng viết vào ngày có lĩnh vực thứ hai, không phải hôm nay.

    ⚠️ GIỚI HẠN NHỊP NÉM `429`, KHÔNG trả `None`. Hai thứ khác hẳn nhau và bên
    khách phải phân biệt được: `401` nghĩa là «đổi token đi», `429` nghĩa là «token
    đúng rồi, chậm lại». Gộp chúng là đẩy một dev đang bị chặn nhịp đi phát lại
    token — thao tác vô ích, và họ sẽ làm lại mỗi lần gặp.

    Nhịp kiểm TRƯỚC khi tra DB — xem `nhip.py`.
    """
    if not bearer or not bearer.startswith("Bearer "):
        return None
    tho = bearer.removeprefix("Bearer ").strip()
    if not tho:
        return None

    bam = bi_mat.bam(tho)
    await nhip.cho_qua(redis, bam_token=bam, cua=cua, so_lan=so_lan, giay=giay)

    async with pool.acquire() as conn:
        hang = await repo.tra_token(conn, bam)
    if hang is None or hang["vertical"] != vertical:
        return None
    return hang


# ─── Nhận lô ────────────────────────────────────────────────────────────────


async def nap_lo(
    pool: asyncpg.Pool,
    *,
    tenant_id: str,
    lo: contracts.LoNapIn,
    dry_run: bool,
) -> contracts.LoNapOut:
    """Kiểm → lưu thô → chiếu. Trả kết quả TỪNG bản ghi.

    ⚠️ `dry_run` KHÔNG ghi gì: không `ingest_records`, không `ingest_errors`. Một
    lần thử làm bẩn số liệu vận hành là một lần thử nói dối về sức khoẻ đường đẩy.
    """
    ket_qua: list[contracts.KetQuaBanGhi] = []

    async with tenant_conn(pool, tenant_id) as conn:
        if not dry_run:
            await chieu.dam_bao_collection(conn, tenant_id)

        for r in lo.records:
            loi = [] if r.op == "delete" else kiem(r.entity, r.data)[1]
            if loi:
                for e in loi:
                    if not dry_run:
                        await repo.ghi_loi(
                            conn,
                            tenant_id=tenant_id,
                            entity=r.entity,
                            external_id=r.externalId,
                            field=e.truong,
                            reason=e.ly_do,
                        )
                dau = loi[0]
                ket_qua.append(
                    contracts.KetQuaBanGhi(
                        externalId=r.externalId,
                        status="rejected",
                        field=dau.truong,
                        reason=dau.ly_do if len(loi) == 1 else f"{dau.ly_do} (+{len(loi) - 1} lỗi nữa)",
                    )
                )
                continue

            if dry_run:
                ket_qua.append(
                    contracts.KetQuaBanGhi(
                        externalId=r.externalId,
                        status="accepted",
                        reason=await _canh_bao_cha(conn, r),
                    )
                )
                continue

            trang_thai, ly_do = await _nap_mot(conn, tenant_id, r, sync_id=lo.syncId)
            ket_qua.append(contracts.KetQuaBanGhi(externalId=r.externalId, status=trang_thai, reason=ly_do))

    return contracts.LoNapOut(
        accepted=sum(1 for k in ket_qua if k.status == "accepted"),
        rejected=sum(1 for k in ket_qua if k.status == "rejected"),
        stale=sum(1 for k in ket_qua if k.status == "stale"),
        results=ket_qua,
        dryRun=dry_run,
    )


async def _canh_bao_cha(conn: asyncpg.Connection, r: contracts.BanGhiIn) -> str:
    """Chỉ dùng ở `dryRun`. Cha chưa tới là CẢNH BÁO, không phải lỗi.

    Bản ghi con tới trước cha là chuyện bình thường của đẩy bất đồng bộ. Nhưng
    trong một lượt thử, biết trước «tôi đang trỏ vào một dự án chưa tồn tại» là
    đúng thứ dev bên khách cần — nó thường nghĩa là họ ghép sai `externalId`.
    """
    if r.op == "delete":
        return ""
    try:
        await chieu._giai_cha(conn, r.entity, r.data)  # noqa: SLF001 — cùng module
    except chieu.ChuaGiaiDuocCha as e:
        return f"Cảnh báo: chưa tìm thấy {e.truong} — bản ghi cha phải tới trước, hoặc cùng lô"
    return ""


async def _nap_mot(
    conn: asyncpg.Connection, tenant_id: str, r: contracts.BanGhiIn, *, sync_id: str | None, lan_thu: int = 0
) -> tuple[str, str]:
    """Lưu thô + chiếu MỘT bản ghi, nguyên tử trong MỘT savepoint.

    Ba lối ra: `accepted` (đã vào kho, hoặc đang chờ cha), `stale` (bản tới cũ
    hơn/bằng), `rejected` (chiếu hỏng ⇒ savepoint rollback CẢ bản thô + một dòng
    `ingest_errors` — khách sửa rồi đẩy lại nguyên văn được, vì bản đang có giữ
    `occurred_at` cũ)."""
    da_chieu = False
    try:
        async with conn.transaction():
            moi = await repo.ghi_ban_ghi(
                conn,
                tenant_id=tenant_id,
                entity=r.entity,
                external_id=r.externalId,
                op=r.op,
                occurred_at=r.occurredAt,
                sync_id=sync_id,
                payload=r.data,
            )
            if not moi:
                return "stale", "Đã có bản mới hơn hoặc bằng — bỏ qua"
            try:
                await chieu.chieu_mot(conn, tenant_id, entity=r.entity, external_id=r.externalId, op=r.op, data=r.data)
                da_chieu = True
            except chieu.ChuaGiaiDuocCha as e:
                await repo.danh_dau_cho_cha(
                    conn, entity=r.entity, external_id=r.externalId, cha_entity=e.cha_entity, cha_ma=e.cha_ma
                )
    except asyncpg.UniqueViolationError:
        if lan_thu == 0:
            return await _nap_mot(conn, tenant_id, r, sync_id=sync_id, lan_thu=1)
        await repo.ghi_loi(
            conn,
            tenant_id=tenant_id,
            entity=r.entity,
            external_id=r.externalId,
            field="",
            reason="Không ghi được vào kho: đụng mã hai lần liên tiếp",
        )
        return "rejected", "Không ghi được vào kho — xem chi tiết ở bảng lỗi nạp"
    except Exception as e:  # noqa: BLE001 — một bản ghi hỏng không được kéo lô (§3.1)
        await repo.ghi_loi(
            conn,
            tenant_id=tenant_id,
            entity=r.entity,
            external_id=r.externalId,
            field="",
            reason=f"Không ghi được vào kho: {type(e).__name__}: {str(e)[:200]}",
        )
        return "rejected", "Không ghi được vào kho — xem chi tiết ở bảng lỗi nạp"
    if da_chieu:
        await _chieu_con_dang_cho(conn, tenant_id, goc=(r.entity, r.externalId))
    return "accepted", ""


async def _chieu_con_dang_cho(conn: asyncpg.Connection, tenant_id: str, *, goc: tuple[str, str]) -> None:
    """Cha vừa chiếu xong ⇒ chiếu nốt các con đang chờ, LAN TRUYỀN (zone mở khoá unit).

    MỌI câu SQL của cascade (tra con, re-mark cờ, ghi lỗi) chạy TRONG một savepoint
    RIÊNG — một câu hỏng ở tầng lan truyền KHÔNG được phép abort giao dịch NGOÀI
    của `nap_lo` (§3.1: một bản ghi hỏng không được kéo cả lô). Tra con hỏng ⇒
    bỏ lượt lan truyền, con giữ nguyên cờ chờ (trạng thái (b), an toàn), KHÔNG
    re-raise. Re-mark cờ hỏng ⇒ cờ CŨ vẫn còn (savepoint con vừa rollback), vẫn
    (b). Ghi lỗi hỏng ⇒ nuốt, mất một dòng lỗi chứ không giết lô.

    CÓ TRẦN — xem `TRAN_LAN_TRUYEN`. Vượt trần: DỪNG, con còn lại giữ nguyên cờ
    chờ (an toàn), và MỘT dòng lỗi cho CHA GỐC nói cách tiếp tục (đẩy lại cha với
    `occurredAt` mới hơn để chạy tiếp lượt lan truyền)."""
    hang_doi = [goc]
    da_xu_ly = 0
    while hang_doi:
        cha_entity, cha_ma = hang_doi.pop()
        try:
            async with conn.transaction():
                con_list = await repo.con_dang_cho(
                    conn, cha_entity=cha_entity, cha_ma=cha_ma, gioi_han=TRAN_LAN_TRUYEN - da_xu_ly + 1
                )
        except Exception:  # noqa: BLE001 — SELECT hỏng không được kéo `nap_lo` (§3.1)
            return

        for con in con_list:
            if da_xu_ly >= TRAN_LAN_TRUYEN:
                goc_entity, goc_ma = goc
                try:
                    async with conn.transaction():
                        await repo.ghi_loi(
                            conn,
                            tenant_id=tenant_id,
                            entity=goc_entity,
                            external_id=goc_ma,
                            field="",
                            reason=(
                                f"Lan truyền dừng ở {TRAN_LAN_TRUYEN} bản ghi con — còn con đang chờ; "
                                "đẩy lại bản ghi cha (occurredAt mới hơn) để tiếp tục"
                            ),
                        )
                except Exception:  # noqa: BLE001 — mất dòng cảnh báo, vẫn phải dừng
                    pass
                return

            da_xu_ly += 1
            try:
                payload = con["payload"]
                data = json.loads(payload) if isinstance(payload, str) else payload
                async with conn.transaction():
                    await chieu.chieu_mot(
                        conn,
                        tenant_id,
                        entity=con["entity"],
                        external_id=con["external_id"],
                        op=con["op"],
                        data=data,
                    )
                    await repo.xoa_cho_cha(conn, con["id"])
            except chieu.ChuaGiaiDuocCha as e:
                try:
                    async with conn.transaction():
                        await repo.danh_dau_cho_cha(
                            conn,
                            entity=con["entity"],
                            external_id=con["external_id"],
                            cha_entity=e.cha_entity,
                            cha_ma=e.cha_ma,
                        )
                except Exception:  # noqa: BLE001 — cờ CŨ vẫn còn (savepoint con rollback), vẫn (b)
                    continue
            except Exception as e:  # noqa: BLE001
                try:
                    async with conn.transaction():
                        await repo.ghi_loi(
                            conn,
                            tenant_id=tenant_id,
                            entity=con["entity"],
                            external_id=con["external_id"],
                            field="",
                            reason=f"Không ghi được vào kho: {type(e).__name__}: {str(e)[:200]}",
                        )
                except Exception:  # noqa: BLE001 — mất một dòng lỗi, không giết lô
                    continue
            else:
                hang_doi.append((con["entity"], con["external_id"]))


# ─── Đối soát ───────────────────────────────────────────────────────────────


class BanKeKhongHopLe(Exception):
    """Bản kê bị từ chối TRƯỚC khi so. Xem `doi_soat.kiem_ban_ke`."""


async def doi_soat_ban_ke(
    pool: asyncpg.Pool, *, tenant_id: str, ban_ke: contracts.BanKeIn, token_id: int | None = None, dry_run: bool = False
) -> contracts.DoiSoatOut:
    """So bản kê của khách với bảng của mình, gắn/gỡ cờ nghi mất tích.

    KIỂM TRƯỚC, SO SAU. Một bản kê cắt dở hoặc có mã trùng cho ra kết quả sai theo
    hướng tệ nhất — hàng nghìn bản ghi bị gắn cờ nghi mất tích — nên nó phải bị
    chặn trước khi chạm dữ liệu, không phải sau.

    `dry_run=True` — DIỄN TẬP: kiểm và SO như thật (kết quả khác đi là lượt diễn
    tập vô dụng), nhưng KHÔNG gắn/gỡ cờ, KHÔNG ghi nhật ký, KHÔNG đóng dấu nhịp
    tim. Ba cái «không» là ba lớp hại riêng nếu thiếu: cờ giả trên dữ liệu thật ·
    cảnh báo vận hành cho một lượt bấm thử · dấu «adapter còn sống» từ một lượt
    dev đang nghịch — cái cuối làm im cảnh báo «tenant im lặng» cho đúng ca
    adapter thật đã chết. Cùng lý lẽ `dryRun` của `nap_lo`.
    """
    ly_do = doi_soat.kiem_ban_ke(ban_ke)
    if ly_do:
        raise BanKeKhongHopLe(ly_do)

    ma = [m.externalId for m in ban_ke.records]
    moc = [m.updatedAt for m in ban_ke.records]
    async with tenant_conn(pool, tenant_id) as conn:
        if ban_ke.isLastPage and not dry_run:
            await repo.cham_ban_ke(conn, tenant_id=tenant_id, entity=ban_ke.entity, so_muc=len(ma))
        kh = doi_soat.khoang(ma, ban_ke.afterExternalId, ban_ke.isLastPage)

        lech, mat_tich = await doi_soat.so_ban_ke(conn, entity=ban_ke.entity, ma=ma, moc=moc, kh=kh)
        moi = [] if dry_run else await doi_soat.dat_co_mat_tich(conn, ban_ke.entity, mat_tich, kh=kh)
        if moi:
            await nhat_ky.ghi(
                conn,
                tenant_id,
                "ingest.nghi_mat_tich",
                f"ingest_token:{token_id}" if token_id else "ingest",
                {"entity": ban_ke.entity, "externalId": moi[:50], "so": len(moi)},
            )
    return contracts.DoiSoatOut(
        dryRun=dry_run,
        soLech=len(lech),
        soNghiMatTich=len(mat_tich),
        externalIdLech=lech,
        externalIdNghiMatTich=mat_tich,
    )


# ─── Control-plane ──────────────────────────────────────────────────────────


async def toi_la_ai(pool: asyncpg.Pool, tenant_id: str) -> contracts.WhoamiOut:
    """`/whoami` — xem docstring `contracts.WhoamiOut` cho vì sao nó tồn tại.

    `name` NULL không xảy ra với tenant thật (cột NOT NULL), nhưng fallback về
    `tenant_id` thay vì nổ: whoami là công cụ CHẨN ĐOÁN — nó phải trả lời được
    ngay cả khi dữ liệu control đang xấu, vì đó chính là lúc người ta gọi nó."""
    async with pool.acquire() as conn:
        ten = await repo.ten_tenant(conn, tenant_id)
    return contracts.WhoamiOut(workspaceId=tenant_id, workspaceName=ten or tenant_id)


async def tong_quan(pool: asyncpg.Pool, tenant_id: str, *, diem_nap: str, docs_url: str) -> contracts.TongQuanOut:
    async with pool.acquire() as conn:
        token = await repo.liet_ke_token(conn, tenant_id, contracts.LINH_VUC)
    async with tenant_conn(pool, tenant_id) as conn:
        tk = await repo.thong_ke(conn)
    return contracts.TongQuanOut(
        diemNap=diem_nap,
        docsUrl=docs_url,
        thongKe=contracts.ThongKeOut(
            nhanCuoiLuc=tk["nhan_cuoi_luc"],
            soNhan24h=tk["so_nhan"],
            soGhiDuoc24h=tk["so_ghi_duoc"],
            soHong24h=tk["so_hong"],
        ),
        tokens=[contracts.TokenOut(id=t["id"], label=t["label"], token=t["token"]) for t in token],
    )


async def tao_token(pool: asyncpg.Pool, tenant_id: str, label: str, created_by: str | None) -> contracts.TokenOut:
    """Phát một token. GHI NHẬT KÝ — xem `_vi_sao_nhat_ky`."""
    tho, bam = bi_mat.sinh_token()
    async with pool.acquire() as conn:
        hang = await repo.tao_token(
            conn,
            tenant_id=tenant_id,
            vertical=contracts.LINH_VUC,
            label=label.strip(),
            token=tho,
            token_sha256=bam,
            created_by=created_by,
        )
        await nhat_ky.ghi(
            conn, tenant_id, "ingest.token_tao", created_by or "", {"id": hang["id"], "label": hang["label"]}
        )
    return contracts.TokenOut(id=hang["id"], label=hang["label"], token=hang["token"])


async def xoa_token(pool: asyncpg.Pool, tenant_id: str, id_: int, boi: str | None = None) -> bool:
    """Xoá hẳn. GHI NHẬT KÝ khi xoá được thật — xem `_vi_sao_nhat_ky`.

    Chỉ ghi khi `DELETE` chạm đúng một hàng: một id không tồn tại (hoặc của tenant
    khác) trả `False`, và ghi nhật ký cho nó là dựng ra một sự kiện chưa xảy ra.
    """
    async with pool.acquire() as conn:
        nhan = await conn.fetchval(
            "SELECT label FROM control.ingest_tokens WHERE id = $1 AND tenant_id = $2 AND vertical = $3",
            id_,
            tenant_id,
            contracts.LINH_VUC,
        )
        xong = await repo.xoa_token(conn, tenant_id, contracts.LINH_VUC, id_)
        if xong:
            await nhat_ky.ghi(conn, tenant_id, "ingest.token_xoa", boi or "", {"id": id_, "label": nhan})
    return xong


_vi_sao_nhat_ky = """VÌ SAO GHI, VÀ VÌ SAO CHỈ Ở ĐÂY.

`TokenOut` cố ý chỉ có ba trường và docstring của nó khai rằng «siêu dữ liệu kiểm
toán là việc của Nhật ký»; `router_tenant.xoa_token` cũng viết «ai xoá token nào là
việc của Nhật ký, không phải của bảng này». Cả hai câu đó RỖNG cho tới 2026-08-15 —
module này chưa từng ghi một dòng nhật ký nào cho vòng đời token. Hai lời hứa,
không lời nào được giữ.

Ghi ở ĐÂY chứ không ở đường nạp: phát và xoá token là việc của MỘT NGƯỜI, hiếm, và
đổi được ai ghi được dữ liệu vào workspace. Còn `/events` chạy hàng nghìn lượt mỗi
ngày bởi một hệ thống — ghi nhật ký ở đó là biến Nhật ký thành log truy cập, và
chôn mất đúng những dòng nói về hành động của con người.

KHÔNG ghi chuỗi token vào `chi_tiet`: Nhật ký có nhiều người đọc hơn bảng token.
"""


async def liet_ke_loi(pool: asyncpg.Pool, tenant_id: str) -> contracts.TrangLoiOut:
    async with tenant_conn(pool, tenant_id) as conn:
        hang = await repo.liet_ke_loi(conn, TRAN_LOI_TRA_VE)
    return contracts.TrangLoiOut(
        loi=[
            contracts.LoiNapOut(
                id=h["id"],
                entity=h["entity"],
                externalId=h["external_id"],
                truong=h["field"],
                lyDo=h["reason"],
                nhanLuc=h["received_at"],
            )
            for h in hang
        ]
    )
