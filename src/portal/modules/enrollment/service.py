"""Nghiệp vụ đấu nối agent.

LUẬT MỘT CÂU CỦA MODULE: `api_key` nói "tôi là ai"; credential nói "tôi được làm
gì". Không gộp hai vai. api_key mở được ĐÚNG MỘT thứ — bộ credential của tenant
nó thuộc về.

Vì sao không cho api_key làm data-plane token (bản nháp ban đầu): Postgres,
Qdrant và MinIO không biết api_key của portal là gì. Muốn nó "mở" được cả ba thì
portal phải làm proxy cho cả ba — tức bỏ không dùng RLS + policy tiền tố đã xây.
Đổi một cơ chế Postgres cưỡng chế lấy một cơ chế do code portal cưỡng chế.
"""

from datetime import UTC, datetime, timedelta

import asyncpg
from pydantic import SecretStr
from redis.asyncio import Redis

from portal.core import nhat_ky
from portal.core.config import get_settings
from portal.core.db.session import tenant_conn
from portal.core.ten_tai_nguyen import ten_collection, ten_kho_web, ten_khoa_truy_cap, ten_role_agent
from portal.modules.enrollment import contracts, loi, qdrant_jwt, repo
from portal.modules.enrollment.bi_mat import LOAI_PG, LOAI_S3, bam_khoa, dan_xuat, sinh_khoa
from portal.modules.enrollment.ha_tang import HaTang

NHIP_SO_LAN = 10
NHIP_GIAY = 300
"""10 lần / 5 phút mỗi khoá. Chống dò khoá, không phải chia băng thông công bằng."""

_TIEN_TO_NHIP = "nhip:agent_key:"


async def cap_phat(
    pool: asyncpg.Pool,
    ha_tang: HaTang,
    tenant_id: str,
    label: str,
    boi: str,
) -> contracts.KhoaMoiOut:
    """Áp bí mật lên hạ tầng + phát một khoá.

    Thứ tự có chủ ý: HẠ TẦNG TRƯỚC, KHOÁ SAU. Hỏng ở hạ tầng thì chưa có khoá nào
    được phát ra ngoài. Hỏng sau khi phát khoá thì `/runtime-credentials` trả
    NOT_PROVISIONED — xấu nhưng chẩn đoán được, và admin bấm lại là xong.
    """
    master = get_settings().master_key_bytes()
    version = await repo.doc_version(pool, tenant_id)

    await ha_tang.dat_mat_khau_role(pool, tenant_id, dan_xuat(LOAI_PG, tenant_id, version, master))
    # `kho_tep=False` = bỏ qua vì môi trường không có credential admin MinIO
    # (ha_tang.tu_cai_dat). Khoá vẫn phát — nó không cần kho tệp — nhưng cờ này
    # PHẢI vào nhật ký: khi pod kêu "S3 access denied", audit log là chỗ trả lời
    # được "kho tệp của tenant này chưa từng được cấp" mà không phải mò MinIO.
    kho_tep = ha_tang.dat_khoa_kho_tep(tenant_id, dan_xuat(LOAI_S3, tenant_id, version, master))

    khoa = await _phat_khoa(pool, tenant_id, label, boi)
    # `deployment_id` rời khỏi payload cùng bảng `deployments` (`0941`). `key_id` thay chỗ
    # nó: một dòng "đã cấp phát" mà không nói cấp ra khoá nào thì không truy được về đâu.
    await nhat_ky.ghi(pool, tenant_id, "agent.cap_phat", boi, {"key_id": khoa.id, "kho_tep": kho_tep})
    return khoa


async def phat_khoa_them(pool: asyncpg.Pool, tenant_id: str, boi: str, label: str = "") -> contracts.KhoaMoiOut:
    """Khoá thứ hai cho một tenant đã cấp phát — đường xoay khoá KHÔNG gián đoạn:
    phát mới → nạp vào pod → thu hồi cũ. Nếu mỗi tenant chỉ được một khoá thì mọi
    lần xoay đều có một khoảng chết.

    KHÔNG áp lại hạ tầng: đây là đường xoay khoá, không phải đường cấp phát. Tenant
    chưa từng cấp phát mà gọi vào đây sẽ nhận khoá dùng được nhưng
    `/runtime-credentials` trả NOT_PROVISIONED — đúng như trước `0940`.

    `label` mặc định rỗng để đường admin nền tảng (router.py) gọi y như cũ.
    """
    if await repo.lifecycle_tenant(pool, tenant_id) is None:
        raise loi.khong_co_tenant(tenant_id)
    return await _phat_khoa(pool, tenant_id, label, boi)


async def _phat_khoa(pool: asyncpg.Pool, tenant_id: str, label: str, boi: str) -> contracts.KhoaMoiOut:
    tho, sha, prefix = sinh_khoa()
    key_id = await repo.them_khoa(pool, tenant_id, sha, tho, prefix, label, boi)
    await nhat_ky.ghi(pool, tenant_id, "agent.phat_khoa", boi, {"key_id": key_id, "key_prefix": prefix})
    return contracts.KhoaMoiOut(id=key_id, api_key=tho, key_prefix=prefix)


async def thu_hoi_khoa(pool: asyncpg.Pool, key_id: int, boi: str) -> None:
    """Idempotent: thu hồi hai lần không phải lỗi, nhưng chỉ ghi nhật ký một lần."""
    tenant_id = await repo.tenant_cua_khoa(pool, key_id)
    if await repo.thu_hoi_khoa(pool, key_id) and tenant_id:
        await nhat_ky.ghi(pool, tenant_id, "agent.thu_hoi_khoa", boi, {"key_id": key_id})


# ─── Đường owner workspace tự phát khoá ───────────────────────────────────────
#
# Ba hàm dưới đây nhận `tenant_id` từ PHIÊN ĐÃ XÁC THỰC (Principal.tenant_id),
# không từ request. Đó là chỗ duy nhất cưỡng chế cách ly cho đường này — repo.py
# đã cảnh báo: ba bảng đó ở schema `control`, KHÔNG có RLS đỡ phía sau.


async def phat_khoa_cho_tenant(
    pool: asyncpg.Pool, ha_tang: HaTang, tenant_id: str, label: str, boi: str
) -> contracts.KhoaMoiOut:
    """Phát khoá cho tenant, TỰ cấp phát hạ tầng nếu workspace chưa có.

    VÌ SAO GỘP HAI VIỆC VÀO MỘT LỜI GỌI: với owner workspace thì "cấp phát" không
    phải một khái niệm — họ chỉ muốn một khoá để đưa cho bên agent. Bắt họ bấm hai
    nút, nút đầu tạo một thứ họ không hiểu, là bắt họ học mô hình dữ liệu của ta
    để làm xong một việc.

    An toàn khi gọi lại: `cap_phat` idempotent ở phần hạ tầng —
    `dat_mat_khau_role` tạo-nếu-chưa-có, `dat_khoa_kho_tep` ghi đè. Còn nhánh này
    chỉ chạy khi tenant CHƯA có khoá nào, nên hai lần bấm liên tiếp thì lần thứ
    hai đi nhánh dưới.

    TÍN HIỆU "đã cấp phát" ĐỔI Ở `0940`: trước là "đã có hàng deployment chưa",
    giờ là "đã có khoá nào chưa" (`repo.tenant_da_co_khoa`). Hai vị từ trùng nhau
    trên mọi dữ liệu thật — `cap_phat` luôn tạo deployment VÀ khoá trong cùng lời
    gọi — nên đó không phải đổi hành vi. Từ `0941` bảng kia không còn, và khoá là
    dấu vết cấp phát DUY NHẤT.
    """
    if not await repo.tenant_da_co_khoa(pool, tenant_id):
        return await cap_phat(pool, ha_tang, tenant_id, label, boi)
    return await _phat_khoa(pool, tenant_id, label, boi)


async def liet_ke_khoa(pool: asyncpg.Pool, tenant_id: str) -> list[contracts.KhoaOut]:
    """MỌI khoá của workspace — kể cả đã tắt (`status: "inactive"`), không biến mất."""
    return [contracts.KhoaOut(**r) for r in await repo.liet_ke_khoa_cua_tenant(pool, tenant_id)]


async def dat_trang_thai_khoa_cua_tenant(
    pool: asyncpg.Pool, key_id: int, tenant_id: str, status: str, boi: str
) -> contracts.KhoaOut:
    """Bật/tắt CHỈ KHI khoá thuộc tenant người gọi. Ngược lại 404.

    Kiểm sở hữu TRƯỚC khi đổi — nếu đảo thứ tự thì người ở workspace A đổi được
    trạng thái khoá của workspace B rồi mới bị từ chối, và lúc đó khoá đã đổi.

    Khoá không tồn tại và khoá của tenant khác trả CÙNG một 404 — xem
    loi.khong_co_khoa() để biết vì sao không phân biệt.
    """
    if await repo.tenant_cua_khoa(pool, key_id) != tenant_id:
        raise loi.khong_co_khoa(key_id)
    hang = await repo.dat_trang_thai_khoa(pool, key_id, status == "active")
    if hang is None:
        raise loi.khong_co_khoa(key_id)
    await nhat_ky.ghi(pool, tenant_id, "agent.dat_trang_thai_khoa", boi, {"key_id": key_id, "status": status})
    return contracts.KhoaOut(**hang)


async def xoay_khoa_cua_tenant(pool: asyncpg.Pool, key_id: int, tenant_id: str, boi: str) -> contracts.KhoaMoiOut:
    """Phát khoá MỚI cùng nhãn, rồi thu hồi khoá CŨ — một bước cho việc mà trước
    đây phải làm tay bằng hai nút (Tạo khoá mới, rồi Tắt khoá cũ).

    Kiểm sở hữu TRƯỚC khi đổi, cùng lý lẽ `dat_trang_thai_khoa_cua_tenant`: đảo
    thứ tự thì người ở workspace A xoay được khoá của workspace B rồi mới bị
    từ chối, và lúc đó khoá B đã đổi.

    Thu hồi khoá cũ qua `repo.thu_hoi_khoa` (một chiều, giống đường admin nền
    tảng) chứ không qua `dat_trang_thai_khoa` — khoá vừa bị THAY THẾ, không phải
    người dùng chủ động tạm tắt nó.
    """
    hang = await repo.tenant_va_nhan_cua_khoa(pool, key_id)
    if hang is None or hang[0] != tenant_id:
        raise loi.khong_co_khoa(key_id)
    _, nhan = hang
    khoa_moi = await _phat_khoa(pool, tenant_id, nhan, boi)
    await repo.thu_hoi_khoa(pool, key_id)
    await nhat_ky.ghi(pool, tenant_id, "agent.xoay_khoa", boi, {"key_id_cu": key_id, "key_id_moi": khoa_moi.id})
    return khoa_moi


async def lay_runtime_credentials(
    pool: asyncpg.Pool, redis: Redis, ha_tang: HaTang, khoa_tho: str
) -> contracts.RuntimeCredentialsOut:
    """Đổi api_key lấy bộ credential.

    Endpoint DUY NHẤT trong hệ trả mật khẩu qua HTTP. Bù lại bằng năm điều kiện,
    CẢ NĂM: TLS · chỉ mạng nội bộ · rate-limit · nhật ký mỗi lần gọi · TTL ngắn.

    Thứ tự kiểm có chủ ý: NHỊP TRƯỚC KHI TRA DB. Kẻ dò khoá không được phép làm
    portal chạy một query cho mỗi lần đoán.
    """
    sha = bam_khoa(khoa_tho)
    if not await _cho_qua_nhip(redis, sha):
        raise loi.vuot_gioi_han_nhip()

    khoa = await repo.tra_khoa(pool, sha)
    if khoa is None:
        raise loi.khoa_khong_hop_le()

    lifecycle = await repo.lifecycle_tenant(pool, khoa.tenant_id)
    if lifecycle != "active":
        raise loi.tenant_khong_hoat_dong(lifecycle or "không tồn tại")

    thieu = await ha_tang.thieu_gi(pool, khoa.tenant_id)
    if thieu:
        raise loi.chua_cap_phat(thieu)

    c = get_settings()
    master = c.master_key_bytes()
    version = await repo.doc_version(pool, khoa.tenant_id)

    await repo.cham_last_used(pool, sha)
    await nhat_ky.ghi(pool, khoa.tenant_id, "agent.runtime_credentials", "agent", {"agent_key_id": khoa.key_id})

    # MỘT mốc hết hạn cho CẢ bộ credential — `expires_at` của response và `exp`
    # của token Qdrant là cùng một giá trị, không phải hai lần gọi `now()`.
    het_han = datetime.now(UTC) + timedelta(seconds=c.runtime_credentials_ttl_seconds)
    collection = ten_collection(khoa.tenant_id)
    public_web = ten_kho_web(khoa.tenant_id)

    return contracts.RuntimeCredentialsOut(
        tenant_id=khoa.tenant_id,
        agent_key_id=khoa.key_id,
        postgres_role=ten_role_agent(khoa.tenant_id),
        postgres_password=SecretStr(dan_xuat(LOAI_PG, khoa.tenant_id, version, master)),
        storage=contracts.KhoTepOut(
            endpoint=c.s3_endpoint_url or "",
            bucket=c.s3_bucket,
            access_key=ten_khoa_truy_cap(khoa.tenant_id),
            secret_key=SecretStr(dan_xuat(LOAI_S3, khoa.tenant_id, version, master)),
            prefix=f"tenants/{khoa.tenant_id}/",
        ),
        kb=contracts.KbOut(
            url=c.qdrant_url,
            collection=collection,
            public_web_collection=public_web,
            api_key=_token_qdrant(collection, het_han, c.qdrant_api_key, them=(public_web,)),
        ),
        expires_at=het_han,
    )


def _token_qdrant(collection: str, het_han: datetime, khoa_ky: str, *, them: tuple[str, ...] = ()) -> SecretStr | None:
    """JWT chỉ-đọc cho pod, hoặc `None` nếu môi trường chưa cấu hình khoá ký.

    ⚠️ `None` KHÔNG được coi là lỗi, và đó là điều làm việc bật khoá không gián
    đoạn: pod bản mới đọc trường này chạy được cả TRƯỚC lẫn SAU khi Qdrant bật
    `service.api_key`, nên hai bên không phải deploy cùng lúc.

    Ném ở đây thay vì trả `None` sẽ làm `/runtime-credentials` chết ở mọi môi
    trường chưa đặt `QDRANT_API_KEY` — tức đánh sập cả đường lấy mật khẩu Postgres
    vì một kho hoàn toàn khác chưa được cấu hình.
    """
    if not khoa_ky:
        return None
    return SecretStr(qdrant_jwt.ky_token_doc(collection=collection, het_han=het_han, khoa_ky=khoa_ky, them=them))


async def ghi_feedback(pool: asyncpg.Pool, khoa_tho: str, du_lieu: contracts.FeedbackIn) -> None:
    """Ghi feedback cuối phiên do BE của agent pod gửi — CÙNG `api_key` nó đã có
    sẵn cho `/runtime-credentials`, KHÔNG phải một cơ chế xác thực mới.

    Tenant suy từ khoá (`repo.tra_khoa`), giống hệt `lay_runtime_credentials` —
    contract `FeedbackIn` cố tình không có trường `tenant_id` để không ai bị cám
    dỗ tin input client (xem contracts.py).

    KHÔNG gọi `_cho_qua_nhip`: giới hạn đó (10 lần/5 phút mỗi khoá) thiết kế cho
    một pod làm mới TTL thưa, feedback thì tần suất theo LƯỢNG NGƯỜI DÙNG THẬT
    của tenant — áp cùng ngưỡng sẽ chặn nhầm một tenant đông khách. Vẫn tra
    `tra_khoa`/`lifecycle_tenant` như cũ nên khoá đã thu hồi hay tenant ngừng
    hoạt động vẫn bị chặn ghi.
    """
    sha = bam_khoa(khoa_tho)
    khoa = await repo.tra_khoa(pool, sha)
    if khoa is None:
        raise loi.khoa_khong_hop_le()

    lifecycle = await repo.lifecycle_tenant(pool, khoa.tenant_id)
    if lifecycle != "active":
        raise loi.tenant_khong_hoat_dong(lifecycle or "không tồn tại")

    async with tenant_conn(pool, khoa.tenant_id) as conn:
        await conn.execute(
            """
            INSERT INTO tenant_data.agent_feedback (tenant_id, session_id, rating, comment)
            VALUES ($1, $2, $3, $4)
            """,
            khoa.tenant_id,
            du_lieu.session_id,
            du_lieu.rating,
            du_lieu.comment,
        )
    await nhat_ky.ghi(
        pool, khoa.tenant_id, "agent.feedback", "agent", {"session_id": du_lieu.session_id, "rating": du_lieu.rating}
    )


async def liet_ke_feedback_cua_tenant(
    pool: asyncpg.Pool,
    tenant_id: str,
    limit: int,
    before_id: int | None,
    ratings: list[int] | None = None,
    session_id: str | None = None,
) -> contracts.DanhSachFeedbackOut:
    """Feedback của workspace hiện tại, mới nhất trước — đường FE Portal (`router_tenant.py`).

    Xin thừa `limit + 1` hàng để biết có trang sau mà không cần một câu COUNT
    riêng cho việc đó — `total` vẫn cần một COUNT thật vì FE dựng thanh trang có
    số (cùng lý lẽ `TrangDuAn.total` ở module realestate).

    `ratings`/`session_id` chỉ lọc DANH SÁCH (`items`) — KHÔNG lọc thống kê
    tổng (`total`, `theo_sao`, `diem_trung_binh`), vì thống kê phải phản ánh
    TOÀN BỘ feedback của tenant bất kể đang lọc gì trên màn.
    """
    # `f.tenant_id = portal.current_tenant()` viết LITERAL ngay trong f-string
    # dưới đây (không gói vào `dieu_kien`/nội suy biến) — cổng tĩnh
    # `tests/isolation/test_loc_tenant_o_tang_app.py` quét AST tìm chuỗi
    # `current_tenant(` NGAY TRONG SOURCE; một vị từ giấu trong biến rồi nội
    # suy `{where_items}` chạy đúng lúc thực thi nhưng cổng đó không đọc được
    # (cùng lý lẽ `_cach_ly()` ở `realestate/repo.py` — gọi literal, không lưu
    # kết quả ra biến rồi dùng lại).
    dieu_kien: list[str] = []
    tham_so: list[object] = []

    if ratings:
        tham_so.append(ratings)
        dieu_kien.append(f"f.rating = ANY(${len(tham_so)})")
    if session_id:
        tham_so.append(session_id)
        dieu_kien.append(f"f.session_id = ${len(tham_so)}")

    dieu_kien_dong = "".join(f" AND {d}" for d in dieu_kien)

    async with tenant_conn(pool, tenant_id) as conn:
        if before_id is None:
            rows = await conn.fetch(
                f"""
                SELECT f.id, f.session_id, f.rating, f.comment, f.created_at,
                       c.customer_name, c.phone, c.source
                  FROM tenant_data.agent_feedback f
                  LEFT JOIN tenant_data.conversations c
                         ON c.tenant_id = f.tenant_id AND c.session_id = f.session_id
                 WHERE f.tenant_id = portal.current_tenant(){dieu_kien_dong}
                 ORDER BY f.id DESC
                 LIMIT ${len(tham_so) + 1}
                """,
                *tham_so,
                limit + 1,
            )
        else:
            rows = await conn.fetch(
                f"""
                SELECT f.id, f.session_id, f.rating, f.comment, f.created_at,
                       c.customer_name, c.phone, c.source
                  FROM tenant_data.agent_feedback f
                  LEFT JOIN tenant_data.conversations c
                         ON c.tenant_id = f.tenant_id AND c.session_id = f.session_id
                 WHERE f.tenant_id = portal.current_tenant(){dieu_kien_dong} AND f.id < ${len(tham_so) + 1}
                 ORDER BY f.id DESC
                 LIMIT ${len(tham_so) + 2}
                """,
                *tham_so,
                before_id,
                limit + 1,
            )
        total = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.agent_feedback WHERE tenant_id = portal.current_tenant()"
        )
        theo_sao_rows = await conn.fetch(
            """
            SELECT rating, count(*) AS n
              FROM tenant_data.agent_feedback
             WHERE tenant_id = portal.current_tenant()
             GROUP BY rating
            """
        )

    theo_sao = {str(i): 0 for i in range(1, 6)}
    tong_diem = 0
    for r in theo_sao_rows:
        theo_sao[str(r["rating"])] = r["n"]
        tong_diem += r["rating"] * r["n"]
    diem_trung_binh = round(tong_diem / total, 2) if total else 0.0

    co_trang_sau = len(rows) > limit
    rows = rows[:limit]
    return contracts.DanhSachFeedbackOut(
        items=[contracts.FeedbackOut(**r) for r in rows],
        next_before_id=rows[-1]["id"] if co_trang_sau and rows else None,
        total=total,
        theo_sao=theo_sao,
        diem_trung_binh=diem_trung_binh,
    )


async def xoay_bi_mat(pool: asyncpg.Pool, ha_tang: HaTang, tenant_id: str, boi: str) -> int:
    """Tăng version rồi áp mật khẩu mới lên Postgres và MinIO.

    Kết nối Postgres ĐANG MỞ không đứt — Postgres chỉ hỏi mật khẩu lúc nối mới.
    Pod có trọn một chu kỳ TTL để chuyển sang bản mới.
    """
    master = get_settings().master_key_bytes()
    version = await repo.tang_version(pool, tenant_id, boi)

    await ha_tang.dat_mat_khau_role(pool, tenant_id, dan_xuat(LOAI_PG, tenant_id, version, master))
    kho_tep = ha_tang.dat_khoa_kho_tep(tenant_id, dan_xuat(LOAI_S3, tenant_id, version, master))

    await nhat_ky.ghi(pool, tenant_id, "agent.xoay_bi_mat", boi, {"secret_version": version, "kho_tep": kho_tep})
    return version


async def liet_ke_tenant_van_hanh(pool: asyncpg.Pool) -> list[contracts.TenantVanHanhOut]:
    """Ghép hai nguồn: hàng workspace (`control`) + chẩn đoán dữ liệu (`tenant_data`).

    Ở service chứ không ở repo vì repo không nối `tenant_conn()`; không ở router vì
    router chỉ điều phối.
    """
    rows = await repo.liet_ke_tenant_van_hanh(pool)
    return [
        contracts.TenantVanHanhOut(**r, san_sang_du_lieu=await san_sang_du_lieu(pool, r["tenant_id"])) for r in rows
    ]


async def san_sang_du_lieu(pool: asyncpg.Pool, tenant_id: str) -> contracts.SanSangDuLieu:
    """Hai con số chẩn đoán. ĐỌC THUẦN — không cache, không lưu thành trạng thái.

    Cấp phát xong KHÔNG có nghĩa agent nói được: chưa publish dự án nào thì
    `tenant_data.projects`/`kb_files` trả 0 hàng, pod chạy sạch, và agent tư vấn
    bằng kết quả rỗng. Hỏng im lặng và trông như đang hoạt động — đây là cách duy
    nhất admin thấy nó.

    PHẢI đi qua `tenant_conn()`: nó là chỗ đặt biến phiên mà
    `portal.current_tenant()` trong hai câu dưới đọc. Gọi ngoài nó thì
    `current_tenant()` trả NULL, vị từ thành `tenant_id = NULL` (không bao giờ
    đúng), và hai con số luôn bằng 0 mà trông như thật.

    Vị từ tenant viết TAY: `0909_bo_rls_toan_bo` đã dỡ RLS khỏi `tenant_data`.
    Thiếu nó, hàm này đếm dự án published của TOÀN BỘ khách hàng rồi gán con số
    đó cho từng workspace — và vì `liet_ke_tenant_van_hanh()` gọi nó trong vòng lặp
    trên mọi tenant, MỌI dòng trong bảng admin sẽ hiện cùng một con số.
    """
    async with tenant_conn(pool, tenant_id) as conn:
        du_an = await conn.fetchval(
            "SELECT count(*) FROM tenant_data.projects "
            "WHERE tenant_id = portal.current_tenant() AND status = 'published'"
        )
        doan = await conn.fetchval(
            "SELECT coalesce(sum(chunk_count), 0) FROM tenant_data.kb_files WHERE tenant_id = portal.current_tenant()"
        )
    return contracts.SanSangDuLieu(projects_published=du_an, kb_chunks=int(doan))


async def _cho_qua_nhip(redis: Redis, sha: str) -> bool:
    """Cửa sổ cố định, không trượt: ở đây ta chống dò khoá chứ không chia băng
    thông, nên một cửa sổ 5 phút là đủ và nó rẻ hơn một bậc.

    Đếm theo BĂM của khoá, không theo khoá thô — Redis không phải chỗ để khoá thô
    đi qua, kể cả trong tên key.
    """
    key = f"{_TIEN_TO_NHIP}{sha}"
    dem = await redis.incr(key)
    if dem == 1:
        await redis.expire(key, NHIP_GIAY)
    return dem <= NHIP_SO_LAN
