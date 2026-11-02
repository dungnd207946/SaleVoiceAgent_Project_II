async def test_extract_nhan_anh_va_danh_dau_ocr():
    """CSBH có thể là một tấm ảnh chụp bảng giá — vẫn thuộc `documents`, và chữ trên ảnh
    phải OCR ra thì agent mới trả lời được (D17). Trước 2026-08-15 extractor từ chối
    thẳng mọi đuôi ảnh, nên 34 hàng vừa di trú không có đường nào tới agent."""
    from portal.modules.kb.clients.extract import TextExtractor

    class _Vlm:
        async def ocr_page(self, data: bytes, *, profile: str = "ocr_markdown") -> str:
            return "| Đợt | Tỷ lệ |\n| --- | --- |\n| 1 | 30% |"

    ra = await TextExtractor(vlm=_Vlm()).extract(b"\x89PNG-gia-lap", filename="tenants/x/csbh.png")
    assert "Tỷ lệ" in ra.text
    assert ra.da_ocr is True, "chữ do model đọc phải qua van duyệt"


async def test_extract_anh_khong_co_vlm_thi_tra_rong():
    from portal.modules.kb.clients.extract import TextExtractor

    ra = await TextExtractor(vlm=None).extract(b"x", filename="a.jpg")
    assert ra.text == "" and ra.da_ocr is False
