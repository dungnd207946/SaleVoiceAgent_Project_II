"""Kho «Tài liệu tra cứu» — repo SQL (Task 2) + 3 route /kb/files (Task 3, 4).

Khuôn của module: gọi thẳng hàm (module kb không có fixture client đăng nhập),
Principal dựng sẵn. user_id dùng `u_seed_test` — user seed toàn cục ở
tests/conftest.py, thoả FK `kb_files.uploaded_by → control.users(id)`.
"""

import io
import json

import pytest
from fastapi import UploadFile

from portal.api.loi import LoiPortal
from portal.core.auth.principal import Principal
from portal.core.db.session import tenant_conn
from portal.modules.kb import files_repo, router
from portal.modules.kb.contracts import DOC_TYPE_KB_FILE, KIND_KB_FILE_INDEX
from portal.modules.kb.index.store import point_id_of
from tests.modules.kb.fake import FakeObjectStore

from .conftest import OTHER_TENANT, TENANT

_P = Principal(user_id="u_seed_test", tenant_id=TENANT, role="Quản trị", actions=frozenset())
_P_OTHER = Principal(user_id="u_seed_test", tenant_id=OTHER_TENANT, role="Quản trị", actions=frozenset())


@pytest.fixture
def fake_store(monkeypatch):
    """Router lấy kho tệp qua tên module-level `object_store` — patch đúng tên đó."""
    store = FakeObjectStore()
    monkeypatch.setattr(router, "object_store", lambda: store)
    return store


def _up(ten: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=ten)


async def _them_mau(pool, tenant: str, ten: str = "bao-gia.pdf") -> files_repo.HangTaiLieu:
    async with tenant_conn(pool, tenant) as conn:
        return await files_repo.them(
            conn,
            ten_file=ten,
            s3_key=f"tenants/{tenant}/kb/abc123/{ten}",
            kich_thuoc=1234,
            loai="pdf",
            uploaded_by="u_seed_test",
        )


async def test_them_roi_liet_ke_moi_nhat_truoc(api_pool, seed_kb):
    a = await _them_mau(api_pool, TENANT, "a.pdf")
    b = await _them_mau(api_pool, TENANT, "b.docx")
    async with tenant_conn(api_pool, TENANT) as conn:
        ds = await files_repo.liet_ke(conn)
    assert [t.id for t in ds][:2] == [b.id, a.id]  # mới nhất trước (uploaded_at DESC, id DESC)
    assert ds[0].state == "dang_xu_ly" and ds[0].chunk_count == 0 and ds[0].loi_message == ""


async def test_khong_thay_hang_cua_tenant_khac(api_pool, seed_kb):
    """RLS + vị từ app: OTHER_TENANT không thấy hàng của TENANT — bug cách ly ở đây
    trông y hệt chạy đúng nếu chỉ seed một tenant."""
    await _them_mau(api_pool, TENANT)
    async with tenant_conn(api_pool, OTHER_TENANT) as conn:
        assert await files_repo.liet_ke(conn) == []


async def test_doc_xoa_va_danh_dau(api_pool, seed_kb):
    t = await _them_mau(api_pool, TENANT)
    async with tenant_conn(api_pool, TENANT) as conn:
        await files_repo.danh_dau_san_sang(conn, record_id=t.id, chunk_count=7)
        sau = await files_repo.doc(conn, t.id)
        assert sau is not None and (sau.state, sau.chunk_count) == ("san_sang", 7)

        await files_repo.danh_dau_loi(conn, record_id=t.id, loi_message="hỏng thử")
        sau = await files_repo.doc(conn, t.id)
        assert sau is not None and (sau.state, sau.loi_message) == ("loi", "hỏng thử")

        await files_repo.xoa(conn, t.id)
        assert await files_repo.doc(conn, t.id) is None


async def test_get_kho_rong_tra_mang_rong(api_pool, seed_kb):
    assert await router.kb_liet_ke(p=_P, pool=api_pool) == []


async def test_post_202_ghi_s3_hang_va_job(api_pool, seed_kb, fake_store):
    ra = await router.kb_tai_len(file=_up("Báo giá Q3.pdf", b"%PDF-fake"), p=_P, pool=api_pool)

    # Hàng: tên GỐC giữ nguyên (kể cả dấu + khoảng trắng), trạng thái khởi đầu.
    assert (ra.tenFile, ra.loai, ra.state, ra.chunkCount) == ("Báo giá Q3.pdf", "pdf", "dang_xu_ly", 0)
    assert ra.uploadedBy == "u_seed_test"

    # Tệp nằm trong kho, key mang tiền tố tenant + tên ASCII lành (không dấu, không khoảng trắng).
    (key,) = fake_store.stored
    assert key.startswith(f"tenants/{TENANT}/kb/") and key.endswith("/Bao-gia-Q3.pdf")

    # Job được xếp đúng tenant, đúng kind, payload trỏ đúng hàng.
    async with tenant_conn(api_pool, TENANT) as conn:
        job = await conn.fetchrow(
            "SELECT kind, payload FROM control.jobs WHERE tenant_id = $1 ORDER BY id DESC LIMIT 1", TENANT
        )
    assert job["kind"] == KIND_KB_FILE_INDEX
    payload = job["payload"] if isinstance(job["payload"], dict) else json.loads(job["payload"])
    assert payload["record_id"] == ra.id

    # Nhật ký kb.upload — KB_01 BR09.
    async with tenant_conn(api_pool, TENANT) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = 'kb.upload'", TENANT
        )
    assert n == 1


async def test_post_duoi_la_422(api_pool, seed_kb, fake_store):
    with pytest.raises(LoiPortal) as e:
        await router.kb_tai_len(file=_up("virus.exe", b"xx"), p=_P, pool=api_pool)
    assert e.value.ma == "UNSUPPORTED_TYPE"
    assert fake_store.stored == {}  # từ chối TRƯỚC khi chạm kho tệp


async def test_post_qua_tran_va_rong_422(api_pool, seed_kb, fake_store):
    with pytest.raises(LoiPortal) as e:
        await router.kb_tai_len(file=_up("to.pdf", b"x" * (router.GIOI_HAN_BYTE + 1)), p=_P, pool=api_pool)
    assert e.value.ma == "FILE_TOO_LARGE"
    with pytest.raises(LoiPortal) as e:
        await router.kb_tai_len(file=_up("rong.pdf", b""), p=_P, pool=api_pool)
    assert e.value.ma == "FILE_TOO_LARGE"


class _QdrantGia:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, int, str]] = []
        self.closed = False

    async def delete_by_record(self, name: str, *, record_id: int, doc_type: str = "") -> int:
        self.deleted.append((name, record_id, doc_type))
        return 1

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def qdrant_gia(monkeypatch):
    q = _QdrantGia()
    monkeypatch.setattr(router, "_qdrant_store", lambda: q)
    return q


async def test_delete_go_point_va_hang_trong_mot_giao_dich(api_pool, seed_kb, fake_store, qdrant_gia):
    ra = await router.kb_tai_len(file=_up("xoa-toi.pdf", b"%PDF-fake"), p=_P, pool=api_pool)
    await router.kb_xoa(ra.id, p=_P, pool=api_pool)

    assert qdrant_gia.deleted == [(f"{TENANT}_documents", ra.id, "kb_file")]
    assert qdrant_gia.closed  # client Qdrant phải được đóng — worker sống dài đã dạy bài này
    assert await router.kb_liet_ke(p=_P, pool=api_pool) == []
    assert fake_store.stored == {}  # tệp S3 cũng đi

    async with tenant_conn(api_pool, TENANT) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM control.audit_log WHERE tenant_id = $1 AND hanh_dong = 'kb.delete'", TENANT
        )
    assert n == 1


async def test_delete_s3_hong_van_xoa_duoc_hang(api_pool, seed_kb, fake_store, qdrant_gia, monkeypatch):
    """S3 là best-effort: object content-addressed nằm lại vô hại, còn point + hàng PHẢI đi."""
    ra = await router.kb_tai_len(file=_up("s3-hong.pdf", b"%PDF-fake"), p=_P, pool=api_pool)

    async def _no(*, key: str) -> None:
        raise RuntimeError("minio sập giả lập")

    monkeypatch.setattr(fake_store, "delete", _no)
    await router.kb_xoa(ra.id, p=_P, pool=api_pool)
    assert await router.kb_liet_ke(p=_P, pool=api_pool) == []


async def test_delete_id_la_404(api_pool, seed_kb, qdrant_gia):
    with pytest.raises(LoiPortal) as e:
        await router.kb_xoa(999_999, p=_P, pool=api_pool)
    assert e.value.ma == "NO_DOCUMENT"
    assert qdrant_gia.deleted == []  # 404 thì không chạm Qdrant


# ─── GET /kb/files/{id}/noi-dung — Task 15: xem lại nội dung đã nạp ────────────────


class _QdrantDocGia:
    """Đứng thay `_qdrant_store()` — nhớ payload theo point id, giả lập point thiếu
    bằng cách đơn giản là không đưa id đó vào `payloads`."""

    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads
        self.closed = False

    async def payload_many(self, name: str, point_ids: list[str]) -> dict[str, dict]:
        return {pid: self.payloads[pid] for pid in point_ids if pid in self.payloads}

    async def aclose(self) -> None:
        self.closed = True


def _diem(file_id: int, idx: int, text: str) -> tuple[str, dict]:
    return point_id_of(DOC_TYPE_KB_FILE, file_id, idx), {"text": text}


async def test_noi_dung_dung_thu_tu_va_tach_section(api_pool, seed_kb, monkeypatch):
    t = await _them_mau(api_pool, TENANT, "so-tay.md")
    async with tenant_conn(api_pool, TENANT) as conn:
        await files_repo.danh_dau_san_sang(conn, record_id=t.id, chunk_count=3)
    id0, pl0 = _diem(t.id, 0, "so-tay.md\n\nĐoạn mở đầu.")
    id1, pl1 = _diem(t.id, 1, "so-tay.md — Mục 1\n\nNội dung mục 1.")
    id2, pl2 = _diem(t.id, 2, "so-tay.md — Mục 2\n\nNội dung mục 2.")
    q = _QdrantDocGia({id0: pl0, id1: pl1, id2: pl2})
    monkeypatch.setattr(router, "_qdrant_store", lambda: q)

    ra = await router.kb_noi_dung(t.id, p=_P, pool=api_pool)

    assert [d.idx for d in ra] == [0, 1, 2]
    assert (ra[0].text, ra[0].sectionPath) == ("Đoạn mở đầu.", "")
    assert (ra[1].text, ra[1].sectionPath) == ("Nội dung mục 1.", "Mục 1")
    assert (ra[2].text, ra[2].sectionPath) == ("Nội dung mục 2.", "Mục 2")
    assert q.closed  # client Qdrant phải được đóng, cùng luật với kb_xoa


async def test_noi_dung_tai_lieu_tenant_khac_la_404(api_pool, seed_kb, monkeypatch):
    """403 xác nhận id đó tồn tại — hàng của tenant khác phải 404 (brief §Quyền)."""
    t = await _them_mau(api_pool, TENANT)
    monkeypatch.setattr(router, "_qdrant_store", lambda: (_ for _ in ()).throw(AssertionError("không tới Qdrant")))
    with pytest.raises(LoiPortal) as e:
        await router.kb_noi_dung(t.id, p=_P_OTHER, pool=api_pool)
    assert (e.value.ma, e.value.http) == ("NO_DOCUMENT", 404)


async def test_noi_dung_id_khong_ton_tai_la_404(api_pool, seed_kb):
    with pytest.raises(LoiPortal) as e:
        await router.kb_noi_dung(999_999, p=_P, pool=api_pool)
    assert e.value.ma == "NO_DOCUMENT"


async def test_noi_dung_chua_nap_xong_tra_rong_khong_500(api_pool, seed_kb, monkeypatch):
    """`chunk_count == 0` (state `dang_xu_ly` hoặc `loi`) — danh sách rỗng, không chạm Qdrant."""
    t = await _them_mau(api_pool, TENANT)

    def _khong_duoc_goi():
        raise AssertionError("chunk_count=0 thì không cần Qdrant")

    monkeypatch.setattr(router, "_qdrant_store", _khong_duoc_goi)
    assert await router.kb_noi_dung(t.id, p=_P, pool=api_pool) == []


async def test_noi_dung_point_thieu_thi_bo_qua_khong_nem(api_pool, seed_kb, monkeypatch):
    """`chunk_count` lệch thực tế — point idx=1 không tồn tại thì bỏ qua, không ném."""
    t = await _them_mau(api_pool, TENANT, "thieu.md")
    async with tenant_conn(api_pool, TENANT) as conn:
        await files_repo.danh_dau_san_sang(conn, record_id=t.id, chunk_count=3)
    id0, pl0 = _diem(t.id, 0, "thieu.md\n\nĐoạn 0.")
    id2, pl2 = _diem(t.id, 2, "thieu.md\n\nĐoạn 2.")
    q = _QdrantDocGia({id0: pl0, id2: pl2})
    monkeypatch.setattr(router, "_qdrant_store", lambda: q)

    ra = await router.kb_noi_dung(t.id, p=_P, pool=api_pool)
    assert [d.idx for d in ra] == [0, 2]


async def test_noi_dung_khong_khop_ten_file_giu_nguyen_van_ban(api_pool, seed_kb, monkeypatch):
    """Tài liệu nạp trước khi có tiền tố (hoặc đổi tên tệp sau khi đã nhúng) — text
    không khớp `ten_file` ở đầu, `tach_tien_to` trả `None`, phải giữ NGUYÊN VĂN, không
    cắt mất chữ nào."""
    t = await _them_mau(api_pool, TENANT, "cu.md")
    async with tenant_conn(api_pool, TENANT) as conn:
        await files_repo.danh_dau_san_sang(conn, record_id=t.id, chunk_count=1)
    id0, pl0 = _diem(t.id, 0, "Đoạn văn không có tiền tố nào ở đầu.\n\nCâu thứ hai.")
    q = _QdrantDocGia({id0: pl0})
    monkeypatch.setattr(router, "_qdrant_store", lambda: q)

    ra = await router.kb_noi_dung(t.id, p=_P, pool=api_pool)

    assert ra[0].text == "Đoạn văn không có tiền tố nào ở đầu.\n\nCâu thứ hai."
    assert ra[0].sectionPath == ""


async def test_noi_dung_danh_dau_dong_trung_voi_doan_truoc(api_pool, seed_kb, monkeypatch):
    """Chunker mượn lại đuôi đoạn trước (overlap cấu hình, hoặc dòng văn xuôi mượn
    trước ảnh) — đoạn kế phải tự báo được việc đó qua `overlapsPrev`, đoạn đầu và đoạn
    không trùng gì thì không."""
    t = await _them_mau(api_pool, TENANT, "hdsd.md")
    async with tenant_conn(api_pool, TENANT) as conn:
        await files_repo.danh_dau_san_sang(conn, record_id=t.id, chunk_count=3)
    id0, pl0 = _diem(t.id, 0, "hdsd.md\n\nMột câu văn khá dài để mượn lại ở đoạn kế tiếp.")
    id1, pl1 = _diem(t.id, 1, "hdsd.md — Mục 1\n\nMột câu văn khá dài để mượn lại ở đoạn kế tiếp.\n\n![Ảnh](x.png)")
    id2, pl2 = _diem(t.id, 2, "hdsd.md — Mục 2\n\nNội dung hoàn toàn khác, không trùng gì cả.")
    q = _QdrantDocGia({id0: pl0, id1: pl1, id2: pl2})
    monkeypatch.setattr(router, "_qdrant_store", lambda: q)

    ra = await router.kb_noi_dung(t.id, p=_P, pool=api_pool)

    assert ra[0].overlapsPrev is False
    assert ra[1].overlapsPrev is True
    assert ra[2].overlapsPrev is False


@pytest.mark.asyncio
async def test_tai_len_md_ghi_duoc_hang(client_cfg, workspace_cfg):
    """CHECK `kb_files_loai_check` phải nhận 'md'. Không có vế này thì route cho qua
    rồi Postgres từ chối ở INSERT — người dùng thấy 500, không phải một thông điệp
    nói họ sai chỗ nào."""
    r = await client_cfg.post(
        "/api/v1/kb/files",
        files={"file": ("sotay.md", b"# Tieu de\n\nNoi dung.\n", "text/markdown")},
    )
    assert r.status_code == 202, r.text
    assert r.json()["loai"] == "md"
