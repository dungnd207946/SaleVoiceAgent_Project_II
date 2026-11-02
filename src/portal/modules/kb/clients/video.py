"""Gemini mô tả video. HAI nhánh nguồn, chọn theo URL:

· **YouTube** — gửi thẳng `file_uri` là link xem. Không tải một byte nào.
· **Tệp video** (mp4/mov/webm/…) — tải về rồi đẩy qua **Files API**, chờ Gemini xử lý
  xong mới hỏi. Ba lượt gọi thay vì một, và có một vòng chờ.

CHUẨN HOÁ URL LÀ BẮT BUỘC ở nhánh YouTube: `tenant_data.media.media_url` lưu dạng nhúng
(`/embed/<id>?si=…`) vì frontend dùng chính nó cho iframe. Gemini chỉ nhận dạng xem
(`watch?v=<id>`). Hàm dưới chỉ đổi thứ GỬI ĐI — cột trong DB không đụng tới.
"""

import asyncio
import contextlib
import re

import httpx

from portal.modules.kb import prompts, settings

_GOC = "https://generativelanguage.googleapis.com"
_API = f"{_GOC}/v1beta/models"
_API_FILES = f"{_GOC}/v1beta/files"
_UPLOAD_FILES = f"{_GOC}/upload/v1beta/files"

_MIME_VIDEO: dict[str, str] = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
    ".3gp": "video/3gpp",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
}


def mime_video(url: str) -> str:
    """Mime suy từ ĐUÔI trong đường dẫn, bỏ query string.

    Không sniff magic byte như ảnh: khung chứa video (`ftyp` của mp4 và mov giống nhau ở
    4 byte đầu) không phân biệt được rẻ như JPEG/PNG, còn đuôi tệp thì có sẵn và đúng
    trong mọi bản ghi đo được. Không nhận ra ⇒ `video/mp4`, định dạng áp đảo.
    """
    duong = (url or "").split("?", 1)[0].lower()
    for duoi, mime in _MIME_VIDEO.items():
        if duong.endswith(duoi):
            return mime
    return "video/mp4"


_YT = (
    re.compile(r"(?:www\.|m\.)?youtube\.com/embed/([A-Za-z0-9_-]{6,})"),
    re.compile(r"(?:www\.|m\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]{6,})"),
    re.compile(r"(?:www\.|m\.)?youtube\.com/shorts/([A-Za-z0-9_-]{6,})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{6,})"),
)


def youtube_watch_url(url: str) -> str | None:
    for pat in _YT:
        m = pat.search(url or "")
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    return None


def _parse_text(data: dict) -> str:
    """`candidates` vắng hoặc text rỗng phải nổ rõ ràng: một mô tả rỗng lặng lẽ ghi
    vào cột `media.caption` trông y hệt "chưa chạy job", và không ai phân biệt được.
    """
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"response Gemini thiếu candidates/content/parts/text: {data!r}") from exc
    text = str(text).strip()
    if not text:
        raise ValueError(f"response Gemini trả text rỗng: {data!r}")
    return text


class VideoClient:
    def __init__(self, *, api_key: str) -> None:
        if not api_key:
            raise ValueError("thiếu KB_GEMINI_API_KEY — không gửi request không auth")
        self._key = api_key
        self._http = httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SEC)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _hoi(self, *, spec: prompts.PromptSpec, file_data: dict) -> str:
        r = await self._http.post(
            f"{_API}/{spec.model}:generateContent",
            headers={"x-goog-api-key": self._key},
            json={
                "contents": [{"parts": [{"file_data": file_data}, {"text": spec.prompt}]}],
                "generationConfig": {"maxOutputTokens": spec.max_tokens, "temperature": spec.temperature},
            },
        )
        r.raise_for_status()
        return _parse_text(r.json())

    async def describe(self, media_url: str, *, profile: str = "video_describe") -> str:
        """Nhánh YouTube — không tải byte nào. Nguồn khác đi bằng `describe_bytes`."""
        spec = prompts.get(profile)
        watch = youtube_watch_url(media_url)
        if watch is None:
            raise ValueError(f"không phải link YouTube: {media_url!r} — nguồn tệp phải đi qua describe_bytes")
        return await self._hoi(spec=spec, file_data={"file_uri": watch})

    async def _tai_len(self, data: bytes, *, mime: str) -> tuple[str, str]:
        """Đẩy byte lên Files API. Trả `(name, uri)`.

        Giao thức RESUMABLE hai chặng, đúng như Gemini yêu cầu cho tệp nhị phân: chặng
        `start` chỉ khai kích thước và mime rồi nhận về một URL riêng ở header
        `x-goog-upload-url`, chặng sau mới đẩy byte kèm `upload, finalize`. Không có
        đường một-lượt cho video.
        """
        r = await self._http.post(
            _UPLOAD_FILES,
            headers={
                "x-goog-api-key": self._key,
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(data)),
                "X-Goog-Upload-Header-Content-Type": mime,
                "Content-Type": "application/json",
            },
            json={"file": {"display_name": "kb-video"}},
        )
        r.raise_for_status()
        url = r.headers.get("x-goog-upload-url")
        if not url:
            raise ValueError(f"Files API không trả x-goog-upload-url: {dict(r.headers)!r}")

        r2 = await self._http.post(
            url,
            headers={
                "Content-Length": str(len(data)),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
            content=data,
        )
        r2.raise_for_status()
        tep = r2.json().get("file") or {}
        if not tep.get("name") or not tep.get("uri"):
            raise ValueError(f"Files API trả tệp thiếu name/uri: {r2.json()!r}")
        return str(tep["name"]), str(tep["uri"])

    async def _cho_san_sang(self, name: str) -> None:
        """Chờ Gemini giải mã xong video.

        HỎI NGAY KHI CÒN `PROCESSING` LÀ 400 — tệp có `uri` từ lúc tải lên xong, nên rất
        dễ tưởng là dùng được ngay. Vòng chờ này là phần khác biệt lớn nhất giữa nhánh
        tệp và nhánh YouTube.
        """
        for _ in range(settings.VIDEO_POLL_LAN):
            r = await self._http.get(f"{_API_FILES}/{name.split('/')[-1]}", headers={"x-goog-api-key": self._key})
            r.raise_for_status()
            trang_thai = str(r.json().get("state", ""))
            if trang_thai == "ACTIVE":
                return
            if trang_thai == "FAILED":
                raise ValueError(f"Gemini giải mã video thất bại: {r.json()!r}")
            await asyncio.sleep(settings.VIDEO_POLL_GIAY)
        raise TimeoutError(f"video còn PROCESSING sau {settings.VIDEO_POLL_LAN} lượt hỏi")

    async def _xoa(self, name: str) -> None:
        """Dọn tệp đã tải lên. Best-effort: hạn ngạch Files API là 20 GB/dự án và một
        video bất động sản dễ vài chục MB, nên để chúng tự hết hạn sau 48h là cách hết
        hạn ngạch trong một đợt nạp lớn. Lỗi ở đây KHÔNG được che mất mô tả đã lấy được."""
        with contextlib.suppress(Exception):  # dọn rác không được làm hỏng kết quả
            await self._http.delete(f"{_API_FILES}/{name.split('/')[-1]}", headers={"x-goog-api-key": self._key})

    async def describe_bytes(self, data: bytes, *, mime: str, profile: str = "video_describe") -> str:
        """Nhánh tệp (mp4/mov/webm/…): tải lên → chờ ACTIVE → hỏi → dọn."""
        spec = prompts.get(profile)
        name, uri = await self._tai_len(data, mime=mime)
        try:
            await self._cho_san_sang(name)
            return await self._hoi(spec=spec, file_data={"mime_type": mime, "file_uri": uri})
        finally:
            await self._xoa(name)
