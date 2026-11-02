"""SQL của module ingest — `control.ingest_tokens` + hai bảng `tenant_data`.

⚠️ HAI LUẬT CÁCH LY KHÁC NHAU TRONG CÙNG MỘT FILE. Đọc trước khi thêm câu SQL.

**`control.ingest_tokens`** — schema `control` chưa từng có RLS. Cách ly do chính
câu SQL mang `tenant_id = $n`, và `tenant_id` phải đến từ `Principal` (membership
đã xác thực), KHÔNG BAO GIỜ từ path/query/body.

**`tenant_data.ingest_records` · `ingest_errors`** — hai lớp độc lập, cả hai bắt
buộc:
  1. RLS ở tầng DB (`0913` bật lại sau khi `0909` dỡ) — migration `0927` gọi
     `control.enforce_tenant_isolation` cho cả hai bảng.
  2. Vị từ `portal.current_tenant()` trong CHÍNH câu SQL. Cổng
     `tests/isolation/test_loc_tenant_o_tang_app.py` quét tĩnh và đỏ nếu thiếu.

Một lớp là một điểm chết — đó đúng là bài học của `0913`: agent uỷ thác lọc cho
RLS, `0909` rút sàn, và không có gì để grep ra. Đừng bỏ lớp nào.

Mọi hàm chạm `tenant_data` nhận `conn` đã ở trong `tenant_conn()`.
"""

import json

import asyncpg

from portal.core import bi_mat_luu

_CACH_LY = "tenant_id = portal.current_tenant()"
"""Vị từ cách ly tầng app. Viết một chỗ để cổng quét tĩnh thấy nó ở mọi câu, và
để đọc ra ngay câu nào thiếu."""


# ─── control.ingest_tokens ──────────────────────────────────────────────────


async def liet_ke_token(conn: asyncpg.Connection, tenant_id: str, vertical: str) -> list[dict]:
    """Trả `dict` chứ không `Record`: cột `token` phải GIẢI MÃ trước khi ra khỏi
    đây, và `asyncpg.Record` bất biến nên không sửa tại chỗ được.

    Giải mã ở tầng repo — chỗ DUY NHẤT chạm SQL — để không tầng nào phía trên phải
    nhớ gọi. Một lớp trên quên giải mã sẽ bày `enc.v1.…` lên giao diện như thể đó
    là khoá thật, và người dùng sẽ đi dán nó."""
    hang = await conn.fetch(
        """
        SELECT id, label, token
          FROM control.ingest_tokens
         WHERE tenant_id = $1 AND vertical = $2
         ORDER BY id DESC
        """,
        tenant_id,
        vertical,
    )
    return [{**dict(h), "token": bi_mat_luu.giai_ma(h["token"])} for h in hang]


async def tao_token(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    vertical: str,
    label: str,
    token: str,
    token_sha256: str,
    created_by: str | None,
) -> dict:
    hang = await conn.fetchrow(
        """
        INSERT INTO control.ingest_tokens
               (tenant_id, vertical, label, token, token_sha256, created_by)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, label
        """,
        tenant_id,
        vertical,
        label,
        bi_mat_luu.ma_hoa(token),
        token_sha256,
        created_by,
    )
    return {"id": hang["id"], "label": hang["label"], "token": token}


async def xoa_token(conn: asyncpg.Connection, tenant_id: str, vertical: str, id_: int) -> bool:
    """`tenant_id` trong WHERE, không chỉ `id`.

    Thiếu nó thì một id đoán được là xoá được token của tenant khác — và `id` là
    bigserial, tức đoán được thật.
    """
    ket_qua = await conn.execute(
        "DELETE FROM control.ingest_tokens WHERE id = $1 AND tenant_id = $2 AND vertical = $3",
        id_,
        tenant_id,
        vertical,
    )
    return ket_qua.endswith(" 1")


async def tra_token(conn: asyncpg.Connection, token_sha256: str) -> asyncpg.Record | None:
    """Đường XÁC THỰC — chỗ duy nhất trong hệ tra token mà chưa biết tenant.

    Không có vị từ `tenant_id` vì tenant CHÍNH LÀ thứ câu này đi tìm. `token_sha256`
    là `UNIQUE` toàn cục (`0927`), nên không có chuyện một băm trúng hai tenant.
    """
    return await conn.fetchrow(
        "SELECT id, tenant_id, vertical FROM control.ingest_tokens WHERE token_sha256 = $1",
        token_sha256,
    )


async def ten_tenant(conn: asyncpg.Connection, tenant_id: str) -> str | None:
    """Tên workspace cho `/whoami`. Bảng `control` — ngoài vòng RLS tenant_data,
    và `tenant_id` ở đây ĐÃ xác thực (đi ra từ `tra_token`), không phải input thô."""
    return await conn.fetchval("SELECT name FROM control.tenants WHERE id = $1", tenant_id)


# ─── tenant_data.ingest_records ─────────────────────────────────────────────


async def ghi_ban_ghi(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    entity: str,
    external_id: str,
    op: str,
    occurred_at,
    sync_id: str | None,
    payload: dict,
) -> bool:
    """Upsert latest-wins. Trả `False` nếu bản ghi tới là CŨ HƠN bản đang có.

    `WHERE ... occurred_at < EXCLUDED.occurred_at` trong `DO UPDATE` là thứ làm
    idempotency và chống-lệch-thứ-tự thành MỘT phép, ở tầng DB, không phải hai
    lượt đọc-rồi-ghi có khoảng hở giữa chừng.

    ⚠️ `<` chứ không `<=`: đẩy lại y hệt một bản ghi (retry của khách) phải ra
    `stale` — không tốn một lượt chiếu lại.

    Tie-break cùng mốc: TOMBSTONE THẮNG — ERP một-updated_at-mỗi-dòng export
    delete với đúng mốc cuối; chiều ngược (upsert hồi sinh delete cùng mốc)
    vẫn stale vì hồi sinh cần một sự kiện MỚI HƠN.
    """
    ket_qua = await conn.fetchval(
        """
        INSERT INTO tenant_data.ingest_records
               (tenant_id, entity, external_id, op, occurred_at, sync_id, payload)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        ON CONFLICT (tenant_id, entity, external_id) DO UPDATE
           SET op             = EXCLUDED.op,
               occurred_at    = EXCLUDED.occurred_at,
               sync_id        = EXCLUDED.sync_id,
               payload        = EXCLUDED.payload,
               received_at    = now(),
               cho_cha_entity = NULL,
               cho_cha_ma     = NULL
         WHERE tenant_data.ingest_records.occurred_at < EXCLUDED.occurred_at
            OR (tenant_data.ingest_records.occurred_at = EXCLUDED.occurred_at
                AND tenant_data.ingest_records.op = 'upsert'
                AND EXCLUDED.op = 'delete')
        RETURNING id
        """,
        tenant_id,
        entity,
        external_id,
        op,
        occurred_at,
        sync_id,
        json.dumps(payload, ensure_ascii=False, default=str),
    )
    return ket_qua is not None


async def danh_dau_cho_cha(
    conn: asyncpg.Connection, *, entity: str, external_id: str, cha_entity: str, cha_ma: str
) -> None:
    """Bản ghi này đang chờ ĐÚNG bản ghi cha (cha_entity, cha_ma). Gọi TRONG
    savepoint của chính bản ghi — cờ và bản thô sống chết cùng nhau."""
    await conn.execute(
        f"""UPDATE tenant_data.ingest_records
               SET cho_cha_entity = $3, cho_cha_ma = $4
             WHERE {_CACH_LY} AND entity = $1 AND external_id = $2""",
        entity,
        external_id,
        cha_entity,
        cha_ma,
    )


async def xoa_cho_cha(conn: asyncpg.Connection, record_id: int) -> None:
    await conn.execute(
        f"UPDATE tenant_data.ingest_records SET cho_cha_entity = NULL, cho_cha_ma = NULL WHERE {_CACH_LY} AND id = $1",
        record_id,
    )


async def con_dang_cho(
    conn: asyncpg.Connection, *, cha_entity: str, cha_ma: str, gioi_han: int
) -> list[asyncpg.Record]:
    """Các bản ghi đang chờ đúng cha này — cha vừa chiếu xong thì nhặt chúng.

    Tra TRÚNG ĐÍCH theo index một phần `ingest_records_cho_cha_idx`, không phải
    quét backlog: chính LIMIT-2000-quét-tất của bản trước là nguồn starvation
    (review finding #7).

    `FOR UPDATE` — khoá HÀNG THÔ của từng con NGAY TẠI ĐÂY, trước khi đọc payload
    để chiếu. Không khoá thì có khe TOCTOU giữa cascade và một lô trực tiếp đụng
    CÙNG con: lô cascade đọc payload CŨ của con C ở câu này; một lô khác upsert C
    bản MỚI HƠN xen giữa (ghi payload mới, xoá cờ, chiếu, commit); cascade sau đó
    chiếu payload CŨ đè lên bản MỚI — không cờ, không lỗi, và đối soát §7 mù vì
    `occurred_at` của C vẫn khớp bản kê (đúng "trạng thái thứ tư" phải diệt). Hai
    upsert TRỰC TIẾP thì tự nhiên serialize qua khoá hàng của `ON CONFLICT` trên
    `ingest_records` (xem comment TOCTOU ở `chieu_mot`) — đường cascade SELECT trần
    không tự khoá gì, nên phải khoá tường minh ở đây. Thứ tự khoá (hàng thô của
    con → hàng entity của con) TRÙNG với đường trực tiếp nên không sinh deadlock
    mới: cascade khoá trước ⇒ lô trực tiếp chờ rồi chiếu đúng bản MỚI HƠN sau; lô
    trực tiếp khoá trước ⇒ cascade tra lại (read-committed) thấy cờ đã NULL nên
    con đó không còn nằm trong kết quả — cả hai thứ tự đều an toàn.

    `gioi_han` — ngân sách CÒN LẠI của lượt lan truyền (bên gọi truyền
    `TRAN_LAN_TRUYEN - da_xu_ly + 1`, cộng 1 để phát hiện «còn nữa»): không kéo
    hàng chục nghìn payload của một cha đông con vào RAM khi ngân sách chỉ đủ xử
    lý một phần nhỏ.
    """
    return await conn.fetch(
        f"""SELECT id, entity, external_id, op, payload
              FROM tenant_data.ingest_records
             WHERE {_CACH_LY} AND cho_cha_entity = $1 AND cho_cha_ma = $2
             ORDER BY occurred_at
             LIMIT $3
             FOR UPDATE""",
        cha_entity,
        cha_ma,
        gioi_han,
    )


async def thong_ke(conn: asyncpg.Connection) -> asyncpg.Record:
    """Ba con số 24 giờ + mốc nhận cuối, trong MỘT lượt đi DB.

    Bốn câu riêng sẽ là bốn roundtrip cho một thẻ mà người ta chỉ liếc.
    """
    return await conn.fetchrow(
        f"""
        SELECT
            (SELECT max(received_at) FROM tenant_data.ingest_records WHERE {_CACH_LY})
                AS nhan_cuoi_luc,
            (SELECT count(*) FROM tenant_data.ingest_records
              WHERE {_CACH_LY} AND received_at > now() - interval '24 hours')
                AS so_nhan,
            -- Chiếu hỏng ⇒ bản thô rollback ⇒ không có hàng để đếm nhầm. Hàng
            -- đang chờ cha thì CHƯA vào kho — không được tính (finding #3: bản
            -- cũ đếm cả hàng hỏng-nhưng-đã-đánh-dấu).
            (SELECT count(*) FROM tenant_data.ingest_records
              WHERE {_CACH_LY} AND cho_cha_ma IS NULL
                AND received_at > now() - interval '24 hours')
                AS so_ghi_duoc,
            (SELECT count(*) FROM tenant_data.ingest_errors
              WHERE {_CACH_LY} AND received_at > now() - interval '24 hours')
                AS so_hong
        """
    )


# ─── tenant_data.ingest_errors ──────────────────────────────────────────────


async def ghi_loi(
    conn: asyncpg.Connection,
    *,
    tenant_id: str,
    entity: str,
    external_id: str,
    field: str,
    reason: str,
) -> None:
    await conn.execute(
        """
        INSERT INTO tenant_data.ingest_errors (tenant_id, entity, external_id, field, reason)
        VALUES ($1, $2, $3, $4, $5)
        """,
        tenant_id,
        entity,
        external_id,
        field,
        reason,
    )


# ─── tenant_data.ingest_manifest_runs — nhịp tim của adapter ────────────────


async def cham_ban_ke(conn: asyncpg.Connection, *, tenant_id: str, entity: str, so_muc: int) -> None:
    """Đóng dấu «vừa nhận một bản kê». Xem docstring migration `0929`.

    KHÔNG có `WHERE nhan_luc < now()`: một tenant chạy đối soát hai lần trong một
    đêm thì lần sau đè lần trước, và đó đúng là điều mình muốn — câu hỏi là «lần
    gần nhất là bao giờ», không phải «đã chạy mấy lần».
    """
    await conn.execute(
        """
        INSERT INTO tenant_data.ingest_manifest_runs (tenant_id, entity, so_muc)
        VALUES ($1, $2, $3)
        ON CONFLICT (tenant_id, entity) DO UPDATE
           SET nhan_luc = now(), so_muc = EXCLUDED.so_muc
        """,
        tenant_id,
        entity,
        so_muc,
    )


async def ban_ke_gan_nhat(conn: asyncpg.Connection):
    """Mốc nhận bản kê MỚI NHẤT của tenant, mọi thực thể — `None` nếu chưa từng."""
    return await conn.fetchval(f"SELECT max(nhan_luc) FROM tenant_data.ingest_manifest_runs WHERE {_CACH_LY}")


async def co_du_lieu_nap(conn: asyncpg.Connection) -> bool:
    """Tenant này có dùng cổng nạp không.

    Câu hỏi bắt buộc trước khi cảnh báo im lặng: một workspace chưa bao giờ đấu
    nối thì không gửi bản kê là ĐÚNG, và cảnh báo nó mỗi đêm là cách nhanh nhất
    dạy người trực tắt kênh cảnh báo.
    """
    return bool(await conn.fetchval(f"SELECT EXISTS (SELECT 1 FROM tenant_data.ingest_records WHERE {_CACH_LY})"))


async def don_loi(conn: asyncpg.Connection, *, giu_ngay: int, tran_hang: int) -> int:
    """Cắt `ingest_errors` theo TUỔI rồi theo SỐ DÒNG. Trả tổng số dòng đã xoá.

    HAI VẾ, thiếu vế nào cũng hở một chiều:
      · Chỉ theo tuổi ⇒ một đợt bùng (adapter hỏng đẩy toàn payload sai ở nhịp tối
        đa) nằm nguyên trọn kỳ lưu.
      · Chỉ theo số dòng ⇒ một tenant lỗi lai rai giữ mãi vài dòng từ năm ngoái,
        vô hại về dung lượng nhưng làm bảng nói dối về «đang có vấn đề gì».

    CẮT THEO `id`, KHÔNG theo `received_at`, ở vế thứ hai: `received_at` mặc định
    `now()` — GIỜ GIAO DỊCH — nên cả 500 dòng lỗi của một lô mang ĐÚNG một mốc.
    Một lô đủ lớn thì mọi dòng cùng mốc, `min(received_at)` bằng chính nó, và
    phép cắt không xoá được gì. `id` là bigserial, không bao giờ trùng.
    """
    xoa = await conn.execute(
        f"DELETE FROM tenant_data.ingest_errors "  # noqa: S608 — không có gì từ request
        f"WHERE {_CACH_LY} AND received_at < now() - ($1 || ' days')::interval",
        str(giu_ngay),
    )
    theo_tuoi = int(xoa.rsplit(" ", 1)[1])

    xoa = await conn.execute(
        f"""
        DELETE FROM tenant_data.ingest_errors
         WHERE {_CACH_LY}
           AND id < (SELECT min(id) FROM (
                     SELECT id FROM tenant_data.ingest_errors
                      WHERE {_CACH_LY} ORDER BY id DESC LIMIT $1) t)
        """,
        tran_hang,
    )
    return theo_tuoi + int(xoa.rsplit(" ", 1)[1])


async def liet_ke_loi(conn: asyncpg.Connection, gioi_han: int) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"""
        SELECT id, entity, external_id, field, reason, received_at
          FROM tenant_data.ingest_errors
         WHERE {_CACH_LY}
         ORDER BY received_at DESC, id DESC
         LIMIT $1
        """,
        gioi_han,
    )


# ─── Giải mã ngoài → khoá nội bộ ────────────────────────────────────────────


async def project_code_theo_ma_ngoai(conn: asyncpg.Connection, external_id: str) -> str | None:
    return await conn.fetchval(
        f"SELECT project_code FROM tenant_data.projects WHERE {_CACH_LY} AND external_id = $1",
        external_id,
    )


async def zone_theo_ma_ngoai(conn: asyncpg.Connection, external_id: str) -> asyncpg.Record | None:
    """Trả CẢ `project_code` lẫn `zone_code`: `units` cần đủ cặp cho khoá ngoại
    ba cột, và lấy `project_code` từ payload của căn thay vì từ chính phân khu là
    mở đường cho một căn trỏ sang phân khu của dự án khác."""
    return await conn.fetchrow(
        f"SELECT project_code, zone_code FROM tenant_data.zones WHERE {_CACH_LY} AND external_id = $1",
        external_id,
    )


async def unit_theo_ma_ngoai(conn: asyncpg.Connection, external_id: str) -> asyncpg.Record | None:
    """Trả TRỌN BỘ địa chỉ `(project_code, zone_code, unit_code)` của chính căn —
    cùng lý lẽ `zone_theo_ma_ngoai`: lấy nửa địa chỉ từ payload người gửi là mở
    đường cho media mang project của dự án này và unit của dự án khác
    (`media.unit_code` không có FK, không unique — 0400 cố ý). Review finding #14."""
    return await conn.fetchrow(
        f"SELECT project_code, zone_code, unit_code FROM tenant_data.units WHERE {_CACH_LY} AND external_id = $1",
        external_id,
    )


async def media_id_theo_zone(conn: asyncpg.Connection, project_code: str, zone_code: str) -> list[int]:
    """Mọi media neo vào một phân khu — để purge CASCADE khi phân khu rời published.

    Worker KB chỉ tự cascade theo `anchor_code` (project); zone thì bên gọi phải tự
    liệt kê media, đúng như đường manual làm ở `_enqueue_purge_zone`
    (`realestate/router.py`)."""
    hang = await conn.fetch(
        f"SELECT id FROM tenant_data.media WHERE {_CACH_LY} AND project_code = $1 AND zone_code = $2",
        project_code,
        zone_code,
    )
    return [h["id"] for h in hang]
