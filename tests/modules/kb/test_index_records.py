"""Luồng B: trigger → job → văn bản → Qdrant (fake). Postgres thật (testcontainers)."""

import json

import asyncpg

from portal.core.db.session import tx
from portal.modules.kb import jobs, settings
from tests.modules.kb.conftest import GIA_BAN, GIA_NIEM_YET, Fakes, seed_product


async def _jobs(pool: asyncpg.Pool, kind: str, payload: dict | None = None) -> list[asyncpg.Record]:
    sql = "SELECT id, payload, state FROM shop.jobs WHERE kind = $1"
    args: list = [kind]
    if payload is not None:
        sql += " AND payload = $2::jsonb"
        args.append(json.dumps(payload))
    return await pool.fetch(sql + " ORDER BY id", *args)


async def _index(pool: asyncpg.Pool, entity: str, rid: int, **them) -> str:
    async with tx(pool) as conn:
        return (await jobs.handle_index(conn, {"entity": entity, "id": rid, **them})).message


async def _state(pool: asyncpg.Pool, entity: str, rid: int) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT state, content_hash, points FROM shop.kb_index_state WHERE entity = $1 AND record_id = $2", entity, rid
    )


def _text(fakes: Fakes, rid: int) -> str:
    return "\n".join(p["text"] for p in fakes.store.payloads(settings.collection_documents(), record_id=rid))


async def test_trigger_xep_mot_job_cho_insert_va_update(admin_pool: asyncpg.Pool) -> None:
    pid = await seed_product(admin_pool)
    # 8 lần chạm (sản phẩm + spec + tính năng + màu + biến thể + nhãn) ⇒ MỘT việc đang chờ.
    assert len(await _jobs(admin_pool, "kb_index", {"entity": "product", "id": pid})) == 1

    await admin_pool.execute("UPDATE shop.jobs SET state = 'success'")
    await admin_pool.execute("UPDATE shop.products SET name = 'iPhone 16 Pro Max VN/A' WHERE id = $1", pid)
    queued = [
        j for j in await _jobs(admin_pool, "kb_index", {"entity": "product", "id": pid}) if j["state"] == "queued"
    ]
    assert len(queued) == 1

    await admin_pool.execute("DELETE FROM shop.products WHERE id = $1", pid)
    assert await _jobs(admin_pool, "kb_delete", {"entity": "product", "id": pid})


async def test_van_ban_san_pham_co_thong_so_khong_co_gia(admin_pool: asyncpg.Pool, fakes: Fakes) -> None:
    pid = await seed_product(admin_pool)
    msg = await _index(admin_pool, "product", pid)
    assert "+" in msg

    pts = fakes.store.payloads(settings.collection_documents(), doc_type="product", record_id=pid)
    assert pts and all(p["entity"] == "product" and p["product_id"] == pid for p in pts)
    assert pts[0]["brand"] == "iPhone (Apple)" and pts[0]["category"] == "Điện thoại"
    text = _text(fakes, pid)
    for dong in (
        "Chip xử lý (CPU): Apple A18 Pro 6 nhân",
        'Màn hình rộng: 6.9"',
        "Tính năng camera sau: Chống rung quang học (OIS)",
        "Wifi: Wi-Fi 7",
        "Kháng nước, bụi: IP68",
        "Kích thước: Dài 163 mm - Ngang 77.6 mm - Dày 8.25 mm",
        "Màu sắc: Titan sa mạc",
        "8 GB/256 GB",
        "8 GB/1 TB",
        "Chụp ảnh đẹp",
        "Pin & Sạc",
        "Thiết kế & Chất liệu",
    ):
        assert dong in text, dong
    for gia in (GIA_NIEM_YET, GIA_BAN):
        assert str(gia) not in text
        assert f"{gia:,}".replace(",", ".") not in text

    st = await _state(admin_pool, "product", pid)
    assert st["state"] == "indexed" and st["points"] == len(pts)


async def test_bo_qua_khi_noi_dung_khong_doi(admin_pool: asyncpg.Pool, fakes: Fakes) -> None:
    pid = await seed_product(admin_pool)
    await _index(admin_pool, "product", pid)
    goi = fakes.embed.calls

    assert "bỏ qua" in await _index(admin_pool, "product", pid)
    # Đổi GIÁ không đổi văn bản ⇒ vẫn bỏ qua, không nhúng lại.
    await admin_pool.execute("UPDATE shop.product_variants SET sale_price_vnd = 30000000 WHERE product_id = $1", pid)
    assert "bỏ qua" in await _index(admin_pool, "product", pid)
    assert fakes.embed.calls == goi

    await admin_pool.execute("UPDATE shop.phone_specs SET ip_rating = 'IP69' WHERE product_id = $1", pid)
    assert "bỏ qua" not in await _index(admin_pool, "product", pid)
    assert "IP69" in _text(fakes, pid)
    assert "bỏ qua" not in await _index(admin_pool, "product", pid, force=True)


async def test_ban_ghi_mat_hoac_nhap_thi_xoa(admin_pool: asyncpg.Pool, fakes: Fakes) -> None:
    pid = await seed_product(admin_pool)
    await _index(admin_pool, "product", pid)
    assert _text(fakes, pid)

    await admin_pool.execute("UPDATE shop.products SET status = 'draft' WHERE id = $1", pid)
    await _index(admin_pool, "product", pid)
    assert not _text(fakes, pid)
    assert (await _state(admin_pool, "product", pid))["state"] == "deleted"

    await admin_pool.execute("UPDATE shop.products SET status = 'selling' WHERE id = $1", pid)
    await _index(admin_pool, "product", pid)
    await admin_pool.execute("DELETE FROM shop.products WHERE id = $1", pid)
    # kb_index cho bản ghi không còn = xoá (bảng con cascade vẫn xếp kb_index cho product).
    assert "gỡ" in await _index(admin_pool, "product", pid)
    assert not _text(fakes, pid)


async def test_anh_va_faq_va_chinh_sach(admin_pool: asyncpg.Pool, fakes: Fakes) -> None:
    pid = await seed_product(admin_pool)
    mid = await admin_pool.fetchval(
        """INSERT INTO shop.product_media (product_id, color_id, media_type, url, alt_text)
           SELECT $1, id, 'image', 'https://cdn.example/ip16.jpg', 'Mặt lưng' FROM shop.product_colors
            WHERE product_id = $1 RETURNING id""",
        pid,
    )
    await _index(admin_pool, "product_media", mid)
    (pt,) = fakes.store.payloads(settings.collection_media(), record_id=mid)
    assert pt["caption"] == "Ảnh iPhone 16 Pro Max màu Titan sa mạc. Mặt lưng"
    assert pt["product_id"] == pid and pt["media_url"] == "https://cdn.example/ip16.jpg"

    fid = await admin_pool.fetchval(
        "INSERT INTO shop.faqs (product_id, question, answer) VALUES ($1, 'Có sạc kèm?', 'Không') RETURNING id", pid
    )
    await _index(admin_pool, "faq", fid)
    assert "Trả lời: Không" in _text(fakes, fid)

    plid = await admin_pool.fetchval(
        """INSERT INTO shop.policies (policy_type, slug, title, summary, content_md)
           VALUES ('return_exchange', 'doi-tra', 'Hư gì đổi nấy 12 tháng', 'Đổi mới', '## Điều kiện\n\nCòn hộp')
           RETURNING id"""
    )
    await _index(admin_pool, "policy", plid)
    pts = fakes.store.payloads(settings.collection_documents(), doc_type="policy", record_id=plid)
    assert pts and "Áp dụng cho mọi sản phẩm" in "\n".join(p["text"] for p in pts)


async def test_reindex_all_xep_viec_cho_moi_ban_ghi(admin_pool: asyncpg.Pool) -> None:
    pid = await seed_product(admin_pool)
    fid = await admin_pool.fetchval(
        "INSERT INTO shop.faqs (product_id, question, answer) VALUES ($1, 'Q', 'A') RETURNING id", pid
    )
    # Sổ còn một sản phẩm đã mất khỏi DB ⇒ cũng được xếp (để handler xoá point sót).
    await admin_pool.execute(
        "INSERT INTO shop.kb_index_state (entity, record_id, target, state) "
        "VALUES ('product', 999, 'documents', 'indexed')"
    )
    await admin_pool.execute("DELETE FROM shop.jobs")
    async with tx(admin_pool) as conn:
        r = await jobs.handle_reindex_all(conn, {"force": True})
    assert r.count == 3
    payloads = {json.dumps(json.loads(j["payload"]), sort_keys=True) for j in await _jobs(admin_pool, "kb_index")}
    for entity, rid in (("product", pid), ("faq", fid), ("product", 999)):
        assert json.dumps({"entity": entity, "force": True, "id": rid}, sort_keys=True) in payloads
