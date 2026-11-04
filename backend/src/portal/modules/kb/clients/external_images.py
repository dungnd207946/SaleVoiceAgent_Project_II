"""Ảnh ngoài trong Markdown → kho của mình.

Tài liệu (Markdown, nội dung bài viết…) hay nhúng ảnh từ CDN bên ngoài. Ba lý do phải kéo về:
· kho bên ngoài đổi quyền hoặc xoá tệp là ảnh vỡ phía khách, không lỗi nào phía ta;
· URL của họ đi thẳng vào vector làm nhiễu phép tìm (đo được: hạng 1 từ 7/10 lên 8/10 khi
  bỏ URL khỏi chuỗi nhúng, và URL S3 thật dài gấp đôi URL trong bài đo);
· không cầm byte trong tay thì không sinh được thumbnail.

Phần PHÂN TÍCH là hàm thuần — không mạng, không kho, test được không cần Docker. Phần
KÉO VỀ (`mirror_images`) mới chạm mạng và kho.
"""

import hashlib
import re

from portal.modules.kb import settings

# Dùng chung với `rag._text_de_nhung` (cả hai gọi là "khớp một thẻ ảnh Markdown", và
# hai bản chép tay từng LỆCH NHAU — bản của rag.py không cân bằng ngoặc tròn nên cắt
# cụt `https://s3.khach.vn/file(1).png` tại dấu `)` đầu, dán phần đuôi vào ảnh kế tiếp).
IMG_MD_RE = re.compile(r"!\[([^\]]*)\]\((https?://(?:[^()\s]|\([^)]*\))*)\)")

MAX_IMAGES = 100
MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_SEC = 15.0

# Tuần tự thì 100 ảnh × TIMEOUT_SEC giữ một worker gần nửa giờ cho MỘT tài liệu.
MAX_CONCURRENT_FETCHES = 4

_EXT_BY_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}


def find_external_images(text: str, *, own_prefix: str) -> list[str]:
    """URL ảnh KHÔNG thuộc kho mình, theo thứ tự xuất hiện, đã bỏ trùng.

    ⚠️ `own_prefix` rỗng phải nghĩa là «chưa biết kho mình ở đâu», KHÔNG phải «mọi thứ
    là của mình»: `url.startswith("")` luôn True, nên thiếu vế `bool(own_prefix)` thì
    một môi trường chưa cấu hình `PUBLIC_BASE_URL` sẽ lặng lẽ không kéo ảnh nào về.
    """
    out: list[str] = []
    for _, url in IMG_MD_RE.findall(text):
        is_ours = bool(own_prefix) and url.startswith(own_prefix)
        if not is_ours and url not in out:
            out.append(url)
    return out


def rewrite_urls(text: str, table: dict[str, str]) -> str:
    """Thay URL theo `table`, GIỮ NGUYÊN alt và vị trí. URL vắng trong bảng giữ nguyên.

    Giữ nguyên vị trí là cả mục đích: thứ tự ảnh trong văn bản chính là thứ tự người đọc
    cần, và nó là thứ `chunker` rồi agent dựa vào.
    """
    return IMG_MD_RE.sub(lambda m: f"![{m.group(1)}]({table.get(m.group(2), m.group(2))})", text)


async def mirror_images(text: str, *, store) -> tuple[str, list[str]]:
    """Kéo mọi ảnh ngoài về kho mình, sinh thumb, viết lại link. Trả (text mới, cảnh báo).

    KHÔNG NÉM vì một ảnh hỏng, dù vĩnh viễn (404, sai content-type, vượt trần) hay tạm
    thời (timeout): tài liệu là sản phẩm chính, ảnh là minh hoạ — một ảnh hỏng không được
    làm cả tệp `error`. Cảnh báo vẫn phân biệt hai loại vì người đọc cần biết tải lại có ích không.

    IDEMPOTENT: sau lượt đầu, link đã trỏ kho mình nên lượt sau không tải lại gì — văn bản
    được nhúng lại MỖI LẦN SỬA, nên tính chất này là bắt buộc.
    """
    import asyncio

    import httpx

    from portal.core.config import get_settings
    from portal.core.public_url import PUBLIC_PATH, la_noi_bo, public_url_of
    from portal.modules.kb.contracts import TemporaryError

    base = get_settings().public_base_url.rstrip("/")
    own_prefix = f"{base}{PUBLIC_PATH}" if base else ""
    to_fetch = find_external_images(text, own_prefix=own_prefix)
    if not to_fetch:
        return text, []

    warnings: list[str] = []
    if len(to_fetch) > MAX_IMAGES:
        extra = len(to_fetch) - MAX_IMAGES
        warnings.append(f"{len(to_fetch)} ảnh vượt trần {MAX_IMAGES} — {extra} ảnh cuối giữ URL gốc")
        to_fetch = to_fetch[:MAX_IMAGES]

    sem = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)

    async def _bounded(http: "httpx.AsyncClient", url: str) -> tuple[str, str | None]:
        async with sem:
            return await _fetch_one(http, url, store=store)

    async with httpx.AsyncClient(timeout=TIMEOUT_SEC, follow_redirects=True) as http:
        results = await asyncio.gather(*(_bounded(http, url) for url in to_fetch), return_exceptions=True)

    table: dict[str, str] = {}
    for url, result in zip(to_fetch, results, strict=True):
        if isinstance(result, TemporaryError):
            warnings.append(f"{url}: lỗi mạng tạm thời ({result}) — thử tải lại tệp để lấy ảnh này")
            continue
        if isinstance(result, BaseException):
            warnings.append(f"{url}: {type(result).__name__}: {result}")
            continue
        key, canh_bao_thumb = result
        if canh_bao_thumb:
            warnings.append(canh_bao_thumb)
        new_url = public_url_of(key)
        if not new_url:
            # `public_url_of` trả rỗng khi PUBLIC_BASE_URL trống HOẶC trỏ vào địa chỉ
            # nội bộ (mặc định dev) — hai lý do khác nhau, cảnh báo phải nói đúng cái
            # đang xảy ra chứ không đổ đồng thành "chưa cấu hình". Viết rỗng vào link
            # cho ra `![alt]()`: ảnh mất, không lỗi nào — nên phải giữ URL gốc.
            ly_do = f"trỏ vào địa chỉ nội bộ ({base})" if la_noi_bo(base) else "chưa cấu hình"
            warnings.append(f"{url}: PUBLIC_BASE_URL {ly_do} — giữ URL gốc")
            continue
        table[url] = new_url
    return rewrite_urls(text, table), warnings


async def _fetch_one(http, url: str, *, store) -> tuple[str, str | None]:
    """Tải một ảnh → kho mình → thumb. Trả (KHOÁ của ảnh gốc, cảnh báo thumb hoặc None).

    Tải theo DÒNG và cắt ngay khi quá trần: đọc trọn thân rồi mới đo thì một
    phản hồi 2 GB đã nằm trong RAM trước khi ta kịp từ chối — đó là một điều ước, không
    phải một giới hạn.

    Lỗi mạng TẠM THỜI ném `TemporaryError` để người gọi viết cảnh báo đúng loại.
    Ảnh gốc lưu XONG trước thumb: thumb hỏng không làm mồ côi ảnh gốc, link vẫn được viết lại.
    """
    import httpx

    from portal.modules.kb.contracts import TemporaryError
    from portal.modules.kb.storage import thumbnail

    try:
        async with http.stream("GET", url) as r:
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if not ctype.startswith("image/"):
                raise ValueError(f"không phải ảnh: content-type={ctype!r}")
            buf = bytearray()
            async for part in r.aiter_bytes():
                buf.extend(part)
                if len(buf) > MAX_BYTES:
                    raise ValueError(f"ảnh vượt trần {MAX_BYTES} byte")
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise TemporaryError(f"{type(e).__name__}: {e}") from e
    data = bytes(buf)

    digest = hashlib.sha256(data).hexdigest()
    key = store.key(path=f"{settings.IMAGES_PREFIX}{digest}.{_ext(ctype, url)}")
    await store.put(key=key, data=data, content_type=ctype)
    # `is_internal_key(key)` True ⇒ thumb thành `kb/anh/<digest>.thumb.webp`.
    try:
        await thumbnail.sinh_va_luu(store, media_url=key, content_hash=digest, tai_ve=lambda: data)
    except TemporaryError:
        raise
    except Exception as e:  # noqa: BLE001 — thumb hỏng KHÔNG được xoá công lưu ảnh gốc
        return key, f"{url}: không sinh được ảnh thu nhỏ ({type(e).__name__}: {e})"
    return key, None


def _ext(ctype: str, url: str) -> str:
    """Đuôi tệp: theo content-type trước, rơi về đuôi trong URL, cuối cùng là `bin`."""
    if ctype in _EXT_BY_TYPE:
        return _EXT_BY_TYPE[ctype]
    name = url.split("?", 1)[0].split("#", 1)[0].rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext if ext.isalnum() and len(ext) <= 5 else "bin"
