"""Tệp → Markdown cho kho «Tài liệu tra cứu».

PDF: lớp chữ qua `pypdf` (PDF scan không có lớp chữ ⇒ rỗng ⇒ hàng `error` kèm hướng dẫn).
DOCX/XLSX bóc bằng `python-docx`/`openpyxl`, GIỮ heading và bảng dạng Markdown: `chunker`
không cắt giữa khối bảng và lặp hàng tiêu đề khi phải cắt — bảng thành chữ phẳng thì
thông số mất cột, agent đọc sai.

⚠️ Mọi thư viện ở đây đồng bộ và ngốn CPU — gọi qua `asyncio.to_thread`, không thì cả
event loop của worker đứng im suốt lúc bóc chữ.
"""

import asyncio
import io
from dataclasses import dataclass

DUOI_HO_TRO = frozenset({"pdf", "docx", "xlsx", "md"})


@dataclass(frozen=True, slots=True)
class ExtractResult:
    text: str


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


class TextExtractor:
    async def extract(self, data: bytes, *, filename: str) -> ExtractResult:
        ten = filename.split("?", 1)[0].split("#", 1)[0]
        duoi = ten.rsplit(".", 1)[-1].lower() if "." in ten else ""
        if duoi not in DUOI_HO_TRO:
            raise ValueError(f"đuôi tệp không hỗ trợ: {duoi!r} — chỉ {sorted(DUOI_HO_TRO)}")

        if duoi == "md":
            # Markdown đã đúng định dạng chunker chờ. `errors="replace"`: một byte hỏng không
            # đáng đánh đổi bằng mất cả tài liệu. Chỉ rỗng khi TOÀN khoảng trắng.
            text = data.decode("utf-8", errors="replace")
            return ExtractResult(text="" if not text.strip() else text)
        if duoi == "docx":
            return ExtractResult(text=await asyncio.to_thread(_docx_markdown_sync, data))
        if duoi == "xlsx":
            return ExtractResult(text=await asyncio.to_thread(_xlsx_markdown_sync, data))
        return ExtractResult(text=await asyncio.to_thread(_pdf_text_sync, data))
