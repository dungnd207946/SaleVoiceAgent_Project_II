"""Client API quản lý nhân vật của service lipsync-musetalk (odyssey-models, HTTP :8021).

Hợp đồng: docstring `odyssey-models/lipsync_musetalk/quan_ly.py`. Service dùng chung cho
MỌI tenant — `avatar_id` (ngẫu nhiên, duy nhất toàn cục) là thứ duy nhất phân biệt nhân vật.
"""

from __future__ import annotations

import httpx

from portal.modules.nhan_vat.settings import NhanVatEnv


class LoiLipsync(Exception):
    """Service lipsync không gọi được / trả lỗi lạ — TẠM THỜI, job thử lại lượt sau."""


class LipsyncClient:
    def __init__(self, env: NhanVatEnv):
        self.base = env.lipsync_url.rstrip("/")
        self.hdr = {"Authorization": f"Bearer {env.models_token}"} if env.models_token else {}

    async def _goi(
        self, method: str, path: str, *, timeout: float = 30.0, headers: dict | None = None, **kw
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0)) as http:
                return await http.request(method, f"{self.base}{path}", headers={**self.hdr, **(headers or {})}, **kw)
        except httpx.HTTPError as e:
            raise LoiLipsync(f"{type(e).__name__}: {e}") from e

    async def gui_video(self, avatar_id: str, loai: str, noi_dung: bytes, content_type: str) -> None:
        r = await self._goi(
            "PUT",
            f"/avatars/{avatar_id}/video/{loai}",
            content=noi_dung,
            timeout=120.0,
            headers={"Content-Type": content_type},
        )
        if r.status_code != 200:
            raise LoiLipsync(f"gửi video {loai}: {r.status_code} {r.text[:200]}")

    async def dung(self, avatar_id: str, cat_dau_s: float = 0.0) -> None:
        """Xếp dựng. `cat_dau_s` = sàn cắt đầu (giây) — service lưu cạnh video nguồn, dựng lại
        vẫn áp. Luôn gửi (kể cả 0) để đổi nguồn ảnh→video không giữ sàn cũ."""
        r = await self._goi("POST", f"/avatars/{avatar_id}/dung", json={"cat_dau_s": cat_dau_s})
        if r.status_code != 202:
            raise LoiLipsync(f"xếp dựng: {r.status_code} {r.text[:200]}")

    async def trang_thai(self, avatar_id: str) -> dict | None:
        """Trạng thái dựng, hoặc None nếu service không có nhân vật này (vd. volume mất)."""
        r = await self._goi("GET", f"/avatars/{avatar_id}")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise LoiLipsync(f"trạng thái: {r.status_code} {r.text[:200]}")
        return r.json()

    async def poster(self, avatar_id: str) -> bytes:
        r = await self._goi("GET", f"/avatars/{avatar_id}/poster.png")
        if r.status_code != 200:
            raise LoiLipsync(f"poster: {r.status_code}")
        return r.content

    async def khung_cho(self, avatar_id: str) -> bytes | None:
        """JPEG khung chờ GỐC (có nền) của lần dựng không-tay — ảnh để sinh clip đưa tay. None =
        service chưa có (bản cũ chưa có route, hoặc chưa dựng xong lần nào)."""
        r = await self._goi("GET", f"/avatars/{avatar_id}/khung_cho.jpg")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise LoiLipsync(f"khung chờ: {r.status_code} {r.text[:200]}")
        return r.content

    async def xem_truoc(self, avatar_id: str, cau: str, nen: str | None = None) -> bytes:
        body = {"text": cau}
        if nen:
            body["nen"] = nen
        r = await self._goi("POST", f"/avatars/{avatar_id}/xem-truoc", json=body, timeout=180.0)
        if r.status_code != 200:
            raise LoiLipsync(f"xem trước: {r.status_code} {r.text[:200]}")
        return r.content

    async def xoa(self, avatar_id: str) -> bool:
        """True = đã xoá (hoặc vốn không có). False = service đang dựng nó (409), xoá sau."""
        r = await self._goi("DELETE", f"/avatars/{avatar_id}")
        if r.status_code in (200, 404):
            return True
        if r.status_code == 409:
            return False
        raise LoiLipsync(f"xoá: {r.status_code} {r.text[:200]}")
