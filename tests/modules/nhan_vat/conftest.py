"""Seed + giả lập cho module nhan_vat.

Hai tenant (bug cách ly trông y hệt chạy đúng nếu chỉ seed tenant đang test). Service
lipsync và nhà cung cấp video là dịch vụ NGOÀI (GPU, API trả tiền) ⇒ thay bằng bản giả
ghi lại lời gọi; kho tệp là MinIO testcontainer thật (`kho_tep`).
"""

import pytest

from portal.core.db.pool import create_pool
from portal.modules.nhan_vat import jobs, router
from portal.modules.nhan_vat.lipsync import LipsyncClient
from portal.modules.nhan_vat.settings import NhanVatEnv

TENANT = "nv_acme"
OTHER_TENANT = "nv_other"


@pytest.fixture
async def seed_nv(pool):
    async with pool.acquire() as conn, conn.transaction():
        for tid, name in [(TENANT, "NV Acme"), (OTHER_TENANT, "NV Other")]:
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')", tid, name
            )
    yield
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.jobs WHERE tenant_id LIKE 'nv\\_%'")
        await conn.execute("DELETE FROM control.tenants WHERE id LIKE 'nv\\_%'")


@pytest.fixture
async def api_pool(api_dsn):
    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()


@pytest.fixture
def video_gia(tmp_path):
    chinh, tay = tmp_path / "chinh.mp4", tmp_path / "tay.mp4"
    chinh.write_bytes(b"MP4-CHINH")
    tay.write_bytes(b"MP4-TAY")
    return str(chinh), str(tay)


@pytest.fixture
def env_nv(monkeypatch, video_gia):
    """Env của module: nhà cung cấp `gia` (file có sẵn), lipsync ở URL giả."""
    env = NhanVatEnv(
        _env_file=None,
        video_provider="gia",
        gia_video=video_gia[0],
        gia_video_tay=video_gia[1],
        lipsync_url="http://lipsync.test:8021",
    )
    monkeypatch.setattr(jobs, "get_env", lambda: env)
    monkeypatch.setattr(router, "get_env", lambda: env)
    return env


class LipsyncGia:
    """Thay các phương thức mạng của LipsyncClient. `trang_thai` trả lần lượt các giá trị
    trong `chuoi` (giữ giá trị cuối khi hết) — mô phỏng service đang dựng rồi xong."""

    def __init__(self):
        self.goi: list[tuple] = []
        self.cat_dau: list[float] = []
        self.chuoi: list[dict | None] = [
            {"trang_thai": "dang_dung", "buoc": "tach_nen", "tien_do": 0.2},
            {"trang_thai": "san_sang", "tien_do": 1.0},
        ]
        self.loi_xem_truoc = False
        self.khung: bytes | None = b"KHUNG-CHO-JPG"  # None = service chưa có khung chờ (404)

    def cai(self, monkeypatch):
        g = self

        async def gui_video(self, avatar_id, loai, noi_dung, ct):
            g.goi.append(("gui_video", avatar_id, loai, noi_dung))

        async def dung(self, avatar_id, cat_dau_s=0.0):
            g.goi.append(("dung", avatar_id))
            g.cat_dau.append(cat_dau_s)

        async def trang_thai(self, avatar_id):
            g.goi.append(("trang_thai", avatar_id))
            return g.chuoi.pop(0) if len(g.chuoi) > 1 else g.chuoi[0]

        async def poster(self, avatar_id):
            return b"\x89PNG-poster"

        async def xem_truoc(self, avatar_id, cau, nen=None):
            from portal.modules.nhan_vat.lipsync import LoiLipsync

            if g.loi_xem_truoc:
                raise LoiLipsync("TTS tắt")
            g.goi.append(("xem_truoc", avatar_id, cau))
            return b"MP4-" + cau.encode()

        async def khung_cho(self, avatar_id):
            g.goi.append(("khung_cho", avatar_id))
            return g.khung

        async def xoa(self, avatar_id):
            g.goi.append(("xoa", avatar_id))
            return True

        for ten, f in [
            ("gui_video", gui_video),
            ("dung", dung),
            ("trang_thai", trang_thai),
            ("poster", poster),
            ("xem_truoc", xem_truoc),
            ("khung_cho", khung_cho),
            ("xoa", xoa),
        ]:
            monkeypatch.setattr(LipsyncClient, ten, f)
        return self


@pytest.fixture
def lipsync_gia(monkeypatch):
    return LipsyncGia().cai(monkeypatch)
