"""Tệp → Markdown. PDF render trang rồi đẩy sang VLM; `pypdf` chỉ còn là đường lùi.

⚠️ ĐỔI 2026-08-25: trước đây PDF có ≥ NGUONG_CO_CHU ký tự lớp chữ thì trả `pypdf` và
KHÔNG OCR. `pypdf.extract_text()` cho VĂN BẢN PHẲNG — mất heading, và bảng thành chữ so
le, nên `chunker._cat_bang` (cắt theo hàng, lặp hàng tiêu đề) không bao giờ kích hoạt.
Với chính sách bán hàng thì bảng CHÍNH LÀ nội dung. Nay mọi PDF đi qua `ocr_markdown`;
lớp chữ chỉ dùng khi không có VLM hoặc khi OCR trả rỗng.

DOCX/XLSX bóc bằng `python-docx`/`openpyxl`, giữ heading và bảng ở dạng Markdown vì
`chunker` có strategy `structured_md` không cắt giữa khối bảng — bảng đúng định dạng là
tri thức giữ được nguyên vẹn, bảng thành text phẳng thì không.

⚠️ MỌI THƯ VIỆN Ở ĐÂY ĐỀU ĐỒNG BỘ VÀ NGỐN CPU. Gọi thẳng trong coroutine sẽ đóng băng
event loop của worker: mọi job khác đứng im, và triệu chứng nhìn giống "Qdrant chậm" chứ
không giống "đang bóc chữ". Mọi lời gọi ở đây đi qua `asyncio.to_thread`.
"""

import asyncio
import io
from dataclasses import dataclass

from portal.modules.kb import settings

DUOI_ANH = frozenset({"jpg", "jpeg", "png", "webp"})
DUOI_HO_TRO = frozenset({"pdf", "docx", "xlsx", "md"}) | DUOI_ANH

NGUONG_CO_CHU = 40


@dataclass(frozen=True, slots=True)
class ExtractResult:
    text: str
    da_ocr: bool = False
    da_cat: bool = False
    co_lop_chu: bool = False
    """PDF có lớp chữ đọc được — tức chữ OCR có bản đối chiếu, không cần người duyệt."""


def _pdf_text_sync(data: bytes) -> str:
    from pypdf import PdfReader

    trang = [(p.extract_text() or "").strip() for p in PdfReader(io.BytesIO(data)).pages]
    return "\n\n".join(t for t in trang if t)


def _docx_markdown_sync(data: bytes) -> str:
    import docx

    ra: list[str] = []
    tep = docx.Document(io.BytesIO(data))
    for p in tep.paragraphs:
        noi_dung = p.text.strip()
        if not noi_dung:
            continue
        bac = 0
        if p.style is not None and p.style.name and p.style.name.startswith("Heading"):
            duoi = p.style.name.removeprefix("Heading").strip()
            bac = int(duoi) if duoi.isdigit() else 1
        ra.append(f"{'#' * bac} {noi_dung}" if bac else noi_dung)
    for bang in tep.tables:
        ra.append(_bang_markdown([[o.text.strip() for o in h.cells] for h in bang.rows]))
    return "\n\n".join(x for x in ra if x.strip())


def _xlsx_markdown_sync(data: bytes) -> str:
    from openpyxl import load_workbook

    ra: list[str] = []
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        for sheet in wb.worksheets:
            hang = [
                ["" if o is None else str(o).strip() for o in h]
                for h in sheet.iter_rows(values_only=True)
                if any(o is not None and str(o).strip() for o in h)
            ]
            if hang:
                ra.append(f"## {sheet.title}\n\n{_bang_markdown(hang)}")
    finally:
        wb.close()
    return "\n\n".join(ra)


def _bang_markdown(hang: list[list[str]]) -> str:
    """Hàng đầu làm tiêu đề — quy ước của Markdown, và `chunker.structured_md` nhận diện
    khối bảng bằng chính hình dạng `| … |` này để không cắt đôi nó."""
    if not hang:
        return ""
    rong = max(len(h) for h in hang)
    dem = [h + [""] * (rong - len(h)) for h in hang]
    dong = ["| " + " | ".join(o.replace("|", r"\|") for o in h) + " |" for h in dem]
    return "\n".join([dong[0], "| " + " | ".join(["---"] * rong) + " |", *dong[1:]])


def _dem_trang(data: bytes) -> int:
    import pypdfium2

    doc = pypdfium2.PdfDocument(data)
    try:
        return len(doc)
    finally:
        doc.close()


def _render_pages(data: bytes, gioi_han: int) -> list[bytes]:
    """PDF → PNG từng trang. Chỉ gọi khi pypdf không tìm thấy lớp chữ."""
    import pypdfium2

    ra: list[bytes] = []
    doc = pypdfium2.PdfDocument(data)
    try:
        for i in range(min(len(doc), gioi_han)):
            buf = io.BytesIO()
            doc[i].render(scale=2).to_pil().save(buf, format="PNG")
            ra.append(buf.getvalue())
    finally:
        doc.close()
    return ra


class TextExtractor:
    def __init__(self, *, vlm=None) -> None:
        self._vlm = vlm

    async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
        # `filename` có thể là URL: `a.jpg?v=2` mà không cắt query thì ra đuôi `jpg?v=2`.
        ten = filename.split("?", 1)[0].split("#", 1)[0]
        duoi = ten.rsplit(".", 1)[-1].lower() if "." in ten else ""
        if duoi not in DUOI_HO_TRO:
            raise ValueError(f"đuôi tệp không hỗ trợ: {duoi!r} — chỉ {sorted(DUOI_HO_TRO)}")

        if duoi in DUOI_ANH:
            if self._vlm is None:
                return ExtractResult(text="")
            return ExtractResult(text=await self._vlm.ocr_page(data), da_ocr=True)

        if duoi == "md":
            # Markdown KHÔNG bóc gì — nó đã là định dạng `chunker.structured_md` chờ đợi.
            # `errors="replace"` chứ không ném: một byte hỏng giữa tệp không đáng đánh đổi
            # bằng việc mất cả tài liệu, và chỗ hỏng sẽ hiện ra dưới dạng ký tự thay thế.
            #
            # Chỉ rỗng khi CHỈ TOÀN khoảng trắng — nội dung thật giữ NGUYÊN VĂN (kể cả
            # newline đầu/cuối), vì đây là bản chép, không phải bản làm sạch.
            text = data.decode("utf-8", errors="replace")
            return ExtractResult(text="" if not text.strip() else text)

        if duoi == "docx":
            return ExtractResult(text=await asyncio.to_thread(_docx_markdown_sync, data))
        if duoi == "xlsx":
            return ExtractResult(text=await asyncio.to_thread(_xlsx_markdown_sync, data))

        text = await asyncio.to_thread(_pdf_text_sync, data)
        if self._vlm is None:
            # Không có VLM (đường kb_files) thì lớp chữ là tất cả những gì lấy được.
            return ExtractResult(text=text)

        tong = await asyncio.to_thread(_dem_trang, data)
        gioi_han = settings.OCR_MAX_PAGES
        pages = await asyncio.to_thread(_render_pages, data, gioi_han)
        phan = [await self._vlm.ocr_page(p) for p in pages]
        md = "\n\n".join(t for t in phan if t.strip())
        co_lop_chu = len(text) >= NGUONG_CO_CHU
        if md:
            return ExtractResult(text=md, da_ocr=True, da_cat=tong > gioi_han, co_lop_chu=co_lop_chu)
        # OCR không ra gì thì lớp chữ vẫn hơn không có gì.
        return ExtractResult(text=text)
