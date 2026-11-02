from portal.modules.kb.clients import external_images

MINH = "https://portal.noble.vn/api/v1/public/files/"


def test_tim_dung_thu_tu_va_bo_trung():
    text = (
        "Câu dẫn A.\n\n![a](https://s3.khach.vn/1.png)\n\n"
        "Câu dẫn B.\n\n![b](https://s3.khach.vn/2.png)\n\n"
        "Nhắc lại.\n\n![a lần hai](https://s3.khach.vn/1.png)\n"
    )
    assert external_images.find_external_images(text, own_prefix=MINH) == [
        "https://s3.khach.vn/1.png",
        "https://s3.khach.vn/2.png",
    ]


def test_bo_qua_anh_da_thuoc_kho_minh():
    text = f"![x]({MINH}tenants/t1/kb/anh/abc.png)"
    assert external_images.find_external_images(text, own_prefix=MINH) == []


def test_tien_to_rong_thi_KHONG_coi_moi_url_la_cua_minh():
    """`url.startswith("")` luôn True — không chặn thì chưa cấu hình base là không
    ảnh nào được kéo về, và không dấu hiệu nào."""
    text = "![x](https://s3.khach.vn/1.png)"
    assert external_images.find_external_images(text, own_prefix="") == ["https://s3.khach.vn/1.png"]


def test_bo_qua_link_khong_phai_anh():
    text = "[tài liệu](https://s3.khach.vn/a.pdf) và ![ảnh](https://s3.khach.vn/b.png)"
    assert external_images.find_external_images(text, own_prefix=MINH) == ["https://s3.khach.vn/b.png"]


def test_thay_dung_cho_giu_nguyen_alt():
    text = "Trước.\n\n![Màn đăng nhập](https://s3.khach.vn/1.png)\n\nSau."
    out = external_images.rewrite_urls(text, {"https://s3.khach.vn/1.png": f"{MINH}k/abc.png"})
    assert out == f"Trước.\n\n![Màn đăng nhập]({MINH}k/abc.png)\n\nSau."


def test_url_vang_trong_bang_giu_nguyen():
    text = "![a](https://s3.khach.vn/1.png)![b](https://s3.khach.vn/2.png)"
    out = external_images.rewrite_urls(text, {"https://s3.khach.vn/1.png": "X"})
    assert out == "![a](X)![b](https://s3.khach.vn/2.png)"


def test_text_khong_anh_tra_nguyen_van():
    text = "Chỉ có chữ, không ảnh nào."
    assert external_images.find_external_images(text, own_prefix=MINH) == []
    assert external_images.rewrite_urls(text, {}) == text


def test_url_co_dau_ngoac_tron_binh_thuong():
    """URL với dấu ngoặc tròn cân bằng phải được trích đầy đủ.

    S3 key như `file(1).png` là legal. Markdown cho phép một cấp ngoặc tròn lồng
    trong URL của hình ảnh.
    """
    text = "![a](https://s3.khach.vn/file(1).png)"
    # Extract should get the full URL with parentheses
    urls = external_images.find_external_images(text, own_prefix=MINH)
    assert urls == ["https://s3.khach.vn/file(1).png"]

    # Rewrite should replace the whole URL, not leave dangling ).png)
    new_url = f"{MINH}rewritten.png"
    rewritten = external_images.rewrite_urls(text, {"https://s3.khach.vn/file(1).png": new_url})
    assert rewritten == f"![a]({new_url})"
    # Make sure no dangling characters
    assert ").png)" not in rewritten
