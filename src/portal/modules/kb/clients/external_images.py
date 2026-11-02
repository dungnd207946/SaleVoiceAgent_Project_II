"""Ảnh ngoài trong Markdown → kho của mình.

Khách gửi sổ tay Markdown mà ảnh nằm trên S3 của họ. Ba lý do phải kéo về:
· kho khách đổi quyền hoặc xoá tệp là ảnh vỡ phía người dùng cuối, không lỗi nào phía ta;
· URL của họ đi thẳng vào vector làm nhiễu phép tìm (đo được: hạng 1 từ 7/10 lên 8/10 khi
  bỏ URL khỏi chuỗi nhúng, và URL S3 thật dài gấp đôi URL trong bài đo);
· không cầm byte trong tay thì không sinh được thumbnail.

Phần PHÂN TÍCH là hàm thuần — không mạng, không kho, test được không cần Docker. Phần
KÉO VỀ (`mirror_images`) mới chạm mạng và kho.
"""

import hashlib
import re

# Dùng chung với `rag._text_de_nhung` (cả hai gọi là "khớp một thẻ ảnh Markdown", và
# hai bản chép tay từng LỆCH NHAU — bản của rag.py không cân bằng ngoặc tròn nên cắt
# cụt `https://s3.khach.vn/file(1).png` tại dấu `)` đầu, dán phần đuôi vào ảnh kế tiếp).
IMG_MD_RE = re.compile(r"!\[([^\]]*)\]\((https?://(?:[^()\s]|\([^)]*\))*)\)")

MAX_IMAGES = 100
MAX_BYTES = 10 * 1024 * 1024
TIMEOUT_SEC = 15.0

# Cùng tinh thần LANE_ENRICH (contracts.py): không giới hạn thì 100 ảnh × TIMEOUT_SEC
# tuần tự giữ một worker gần nửa giờ cho MỘT tài liệu.
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


async def mirror_images(text: str, *, tenant_id: str, store) -> tuple[str, list[str]]:
    """Kéo mọi ảnh ngoài về kho mình, sinh thumb, viết lại link. Trả (text mới, cảnh báo).

    KHÔNG NÉM vì một ảnh hỏng, dù VĨNH VIỄN (404, sai content-type, vượt trần) hay TẠM
    THỜI (`httpx.TimeoutException`/`TransportError` — một cơn nghẽn mạng phía kho
    khách) — cùng lý lẽ `jobs._thumb_neu_thieu` đã ghi: tài liệu là sản phẩm chính, ảnh
    là minh hoạ. Một tài liệu 27 ảnh mà 1 ảnh timeout vài giây vẫn phải nạp được; đánh
    dấu cả tệp `loi` là bắt người dùng tải lại một tệp không hề sai.

    ⚠️ KHÔNG theo doctrine `TemporaryError` mà `jobs._tai_anh`/`_thumb_neu_thieu` theo
    (né ở `_fetch_one` ném lên tận đây rồi CỐ Ý không ném tiếp): hàm này chạy trong
    `handle_kb_file_index`, đăng ký `retries=0` (`jobs.py`, cuối file) — ném lên đó
    không mua được một lượt thử lại nào, nó chỉ đổi "1 ảnh timeout, 26 ảnh vẫn nạp,
    một dòng cảnh báo" thành "27 ảnh mất trắng, tệp `loi`, người dùng phải tự tải lại
    tay". Doctrine đó đúng cho `handle_enrich`, đăng ký `retries=RETRY_VIEC_KB` — ném
    ở đó THẬT SỰ mua một lượt thử lại. Cảnh báo vẫn phân biệt hai loại lỗi (tạm thời vs
    vĩnh viễn) vì người đọc log cần biết tải lại tệp có ích không.

    Tải ĐỒNG THỜI có giới hạn (`MAX_CONCURRENT_FETCHES`, cùng tinh thần `LANE_ENRICH`)
    chứ không tuần tự — cảnh báo vẫn theo ĐÚNG THỨ TỰ NGUỒN (`to_fetch`), không theo
    thứ tự hoàn tất, vì `asyncio.gather` trả kết quả cùng thứ tự đối số.

    IDEMPOTENT: sau lượt đầu, link trong `text` đã trỏ kho mình nên lượt sau không tìm
    thấy ảnh ngoài và không tải lại gì. `documents.body` được nhúng lại MỖI LẦN SỬA, nên
    tính chất này là bắt buộc chứ không phải tiện tay.
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
            return await _fetch_one(http, url, tenant_id=tenant_id, store=store)

    async with httpx.AsyncClient(timeout=TIMEOUT_SEC, follow_redirects=True) as http:
        results = await asyncio.gather(*(_bounded(http, url) for url in to_fetch), return_exceptions=True)

    table: dict[str, str] = {}
    for url, result in zip(to_fetch, results, strict=True):
        if isinstance(result, TemporaryError):
            # KHÔNG `raise result` — xem docstring ở trên: `retries=0` làm cho ném ở
            # đây tương đương với mất cả tài liệu, không phải một lượt thử lại. Nói rõ
            # "tạm thời" trong câu cảnh báo (khác nhánh dưới) vì đó là thông tin hành
            # động được: tải lại tệp NHIỀU KHẢ NĂNG sẽ lấy được ảnh này, khác một 404
            # vĩnh viễn mà tải lại không đổi được gì.
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


async def _fetch_one(http, url: str, *, tenant_id: str, store) -> tuple[str, str | None]:
    """Tải một ảnh → kho mình → thumb. Trả (KHOÁ của ảnh gốc, cảnh báo thumb hoặc None).

    Tải theo DÒNG và cắt ngay khi quá trần: đọc trọn thân rồi mới đo thì một
    phản hồi 2 GB đã nằm trong RAM trước khi ta kịp từ chối — đó là một điều ước, không
    phải một giới hạn.

    Lỗi mạng TẠM THỜI (`httpx.TimeoutException`/`TransportError`) NÉM `TemporaryError`
    — không phải để lan tới job (xem docstring `mirror_images`: người gọi CỐ Ý không
    ném tiếp), mà để người gọi phân biệt được nó với lỗi VĨNH VIỄN (404, content-type
    sai, vượt trần) và viết cảnh báo đúng loại.

    Ảnh gốc lưu XONG trước khi sinh thumb; nếu thumb hỏng, ảnh gốc KHÔNG bị mồ côi và
    link vẫn được viết lại — thumb chỉ là tối ưu hiển thị (cùng lý lẽ
    `jobs._thumb_neu_thieu`), không phải điều kiện để coi ảnh là đã mirror thành công.
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
    key = store.key(tenant_id=tenant_id, path=f"kb/anh/{digest}.{_ext(ctype, url)}")
    await store.put(key=key, data=data, content_type=ctype)
    # `key` đã mang tiền tố tenant; `store.key()` idempotent nên truyền lại là an toàn,
    # và `is_internal_key(key)` True ⇒ thumb thành `.../kb/anh/<digest>.thumb.webp`.
    try:
        await thumbnail.sinh_va_luu(store, tenant_id=tenant_id, media_url=key, content_hash=digest, tai_ve=lambda: data)
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
