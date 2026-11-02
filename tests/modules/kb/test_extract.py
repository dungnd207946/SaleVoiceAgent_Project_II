"""Bóc chữ: pypdf cho PDF có lớp chữ, VLM cho PDF scan, python-docx/openpyxl cho office.

`da_cat` phải đúng — chạm OCR_MAX_PAGES mà báo thành công là trả về một tài liệu
cụt và không ai biết.
"""

from pathlib import Path

import pytest

from portal.modules.kb.clients.extract import NGUONG_CO_CHU, TextExtractor
from portal.modules.kb.contracts import LOAI_HO_TRO

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"


class VlmGia:
    def __init__(self, tra: str = "## Trang đã OCR") -> None:
        self.tra = tra
        self.so_lan = 0

    async def ocr_page(self, image_bytes: bytes, *, profile: str = "ocr_markdown") -> str:
        self.so_lan += 1
        return self.tra


@pytest.mark.skipif(not (FIXTURES / "chinh-sach.pdf").exists(), reason="chưa sinh fixture")
async def test_pdf_co_lop_chu_VAN_di_qua_ocr_markdown(monkeypatch):
    """ĐẢO luật cũ (2026-08-25). Trước đây PDF có lớp chữ trả thẳng `pypdf` để khỏi tốn
    tiền VLM — nhưng `pypdf` cho VĂN BẢN PHẲNG, mất heading và bảng thành chữ so le, nên
    `chunker._cat_bang` không bao giờ kích hoạt. Với chính sách bán hàng thì bảng CHÍNH LÀ
    nội dung, nên đổi lấy tiền OCR là có lý."""
    from portal.modules.kb.clients import extract as mod

    monkeypatch.setattr(mod, "_dem_trang", lambda data: 1)
    monkeypatch.setattr(mod, "_render_pages", lambda data, gioi_han: [b"trang1"])

    vlm = VlmGia()
    ra = await TextExtractor(vlm=vlm).extract((FIXTURES / "chinh-sach.pdf").read_bytes(), filename="a.pdf")
    assert ra.da_ocr is True
    assert vlm.so_lan == 1


async def test_pdf_khong_lop_chu_roi_sang_vlm(monkeypatch):
    from portal.modules.kb.clients import extract as mod

    monkeypatch.setattr(mod, "_pdf_text_sync", lambda data: "")
    monkeypatch.setattr(mod, "_dem_trang", lambda data: 2)
    monkeypatch.setattr(mod, "_render_pages", lambda data, gioi_han: [b"trang1", b"trang2"])

    vlm = VlmGia()
    ra = await TextExtractor(vlm=vlm).extract(b"%PDF-gia", filename="scan.pdf")
    assert ra.da_ocr is True
    assert vlm.so_lan == 2
    assert ra.text.count("## Trang đã OCR") == 2


async def test_vai_ky_tu_rac_van_coi_la_khong_co_lop_chu(monkeypatch):
    """PDF scan thường vẫn trả watermark hoặc số trang. Phép kiểm rỗng tuyệt đối sẽ
    cho ra "có chữ" rồi bỏ qua VLM, và người dùng nhận một ô gần trống không báo lỗi."""
    from portal.modules.kb.clients import extract as mod

    monkeypatch.setattr(mod, "_pdf_text_sync", lambda data: "trang 1")
    monkeypatch.setattr(mod, "_dem_trang", lambda data: 1)
    monkeypatch.setattr(mod, "_render_pages", lambda data, gioi_han: [b"t"])

    vlm = VlmGia()
    ra = await TextExtractor(vlm=vlm).extract(b"%PDF-gia", filename="scan.pdf")
    assert ra.da_ocr is True
    assert vlm.so_lan == 1


async def test_ocr_tra_rong_thi_roi_ve_lop_chu(monkeypatch):
    """Đường lùi: OCR im lặng (model trả rỗng) thì lớp chữ vẫn hơn không có gì. Không có
    vế này, một lượt OCR hỏng biến tài liệu có nội dung thành tài liệu trắng."""
    from portal.modules.kb.clients import extract as mod

    monkeypatch.setattr(mod, "_pdf_text_sync", lambda data: "x" * NGUONG_CO_CHU)
    monkeypatch.setattr(mod, "_dem_trang", lambda data: 1)
    monkeypatch.setattr(mod, "_render_pages", lambda data, gioi_han: [b"t"])

    vlm = VlmGia()
    vlm.tra = ""
    ra = await TextExtractor(vlm=vlm).extract(b"%PDF-gia", filename="co-chu.pdf")
    assert ra.da_ocr is False, "rơi về lớp chữ thì không được đánh dấu là OCR"
    assert ra.text == "x" * NGUONG_CO_CHU


async def test_cham_tran_so_trang_thi_bao_da_cat(monkeypatch):
    from portal.modules.kb import settings
    from portal.modules.kb.clients import extract as mod

    monkeypatch.setattr(mod, "_pdf_text_sync", lambda data: "")
    monkeypatch.setattr(mod, "_dem_trang", lambda data: settings.OCR_MAX_PAGES + 5)
    monkeypatch.setattr(mod, "_render_pages", lambda data, gioi_han: [b"t"] * gioi_han)

    ra = await TextExtractor(vlm=VlmGia()).extract(b"%PDF-gia", filename="dai.pdf")
    assert ra.da_cat is True


async def test_khong_qua_tran_thi_khong_bao_da_cat(monkeypatch):
    """Đối chứng cho test trên: số trang thật bằng đúng trần thì không được báo cắt."""
    from portal.modules.kb import settings
    from portal.modules.kb.clients import extract as mod

    monkeypatch.setattr(mod, "_pdf_text_sync", lambda data: "")
    monkeypatch.setattr(mod, "_dem_trang", lambda data: settings.OCR_MAX_PAGES)
    monkeypatch.setattr(mod, "_render_pages", lambda data, gioi_han: [b"t"] * gioi_han)

    ra = await TextExtractor(vlm=VlmGia()).extract(b"%PDF-gia", filename="vua-du.pdf")
    assert ra.da_cat is False


async def test_khong_co_vlm_thi_pdf_scan_tra_rong_khong_no(monkeypatch):
    """Enrich không được chết vì một PDF scan — ô để trống, người dùng tự dán."""
    from portal.modules.kb.clients import extract as mod

    monkeypatch.setattr(mod, "_pdf_text_sync", lambda data: "")

    ra = await TextExtractor(vlm=None).extract(b"%PDF-gia", filename="scan.pdf")
    assert ra.text == ""
    assert ra.da_ocr is False


@pytest.mark.skipif(not (FIXTURES / "anh-scan.pdf").exists(), reason="chưa sinh fixture")
async def test_pdf_scan_that_khong_lop_chu_goi_vlm():
    """Đối chứng bằng fixture thật (không monkeypatch): `anh-scan.pdf` chỉ có một hình
    chữ nhật, không có lớp chữ nào — phải rơi đúng nhánh VLM."""
    vlm = VlmGia()
    ra = await TextExtractor(vlm=vlm).extract((FIXTURES / "anh-scan.pdf").read_bytes(), filename="anh-scan.pdf")
    assert ra.da_ocr is True
    assert vlm.so_lan >= 1


@pytest.mark.skipif(not (FIXTURES / "bang-gia.xlsx").exists(), reason="chưa sinh fixture")
async def test_xlsx_ra_bang_markdown():
    """Bảng phải ra đúng hình dạng `| … |` — `chunker.structured_md` nhận diện khối bảng
    bằng chính hình dạng đó để không cắt đôi nó."""
    ra = await TextExtractor().extract((FIXTURES / "bang-gia.xlsx").read_bytes(), filename="bang-gia.xlsx")
    assert "| ---" in ra.text, "không sinh hàng ngăn cách của bảng Markdown"
    assert ra.da_ocr is False


async def test_docx_giu_heading_thanh_markdown():
    import io

    import docx

    tep = docx.Document()
    tep.add_heading("Chính sách bán hàng", level=1)
    tep.add_paragraph("Áp dụng từ quý 3.")
    bang = tep.add_table(rows=2, cols=2)
    bang.rows[0].cells[0].text = "Đợt"
    bang.rows[0].cells[1].text = "%"
    bang.rows[1].cells[0].text = "1"
    bang.rows[1].cells[1].text = "30"
    buf = io.BytesIO()
    tep.save(buf)

    ra = await TextExtractor().extract(buf.getvalue(), filename="csbh.docx")
    assert "# Chính sách bán hàng" in ra.text
    assert "Áp dụng từ quý 3." in ra.text
    assert "| Đợt | % |" in ra.text


async def test_duoi_tep_la_thi_bao_loi():
    with pytest.raises(ValueError, match="không hỗ trợ"):
        await TextExtractor().extract(b"x", filename="a.exe")


async def test_url_co_query_van_ra_dung_duoi_anh():
    """`filename` có thể là URL nguyên văn của tệp dán link. Không cắt query thì đuôi ra
    `jpg?v=2`, hàm ném ValueError và ảnh CSBH hợp lệ không bao giờ được OCR."""
    vlm = VlmGia()
    ra = await TextExtractor(vlm=vlm).extract(b"byte anh", filename="https://cdn.test/img/bang-gia__csbh.jpg?v=2#p1")
    assert ra.da_ocr is True
    assert vlm.so_lan == 1


def test_md_nam_trong_loai_ho_tro():
    assert "md" in LOAI_HO_TRO


async def test_boc_md_tra_nguyen_van():
    goc = "# Tiêu đề\n\nMột dòng có dấu tiếng Việt.\n\n![alt](https://s3.khach.vn/a.png)\n"
    ra = await TextExtractor(vlm=None).extract(goc.encode("utf-8"), filename="sotay.md")
    assert ra.text == goc
    assert ra.da_ocr is False


async def test_md_rong_khong_muon_thong_diep_lop_chu():
    """`.md` rỗng KHÔNG được rơi vào câu «không có lớp chữ» — câu đó nói về PDF scan."""
    from portal.modules.kb.contracts import MD_EMPTY_MESSAGE

    ra = await TextExtractor(vlm=None).extract(b"   \n\n  ", filename="rong.md")
    assert ra.text == ""
    assert "lớp chữ" not in MD_EMPTY_MESSAGE
