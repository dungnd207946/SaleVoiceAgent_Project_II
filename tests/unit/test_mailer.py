import pytest

from portal.core import mailer


def _cau_hinh(monkeypatch, **kw):
    from portal.core.config import Settings

    c = Settings(_env_file=None, **kw)
    monkeypatch.setattr("portal.core.mailer.get_settings", lambda: c)
    return c


def test_tat_khi_thieu_smtp_host(monkeypatch):
    _cau_hinh(monkeypatch, public_base_url="https://p.vn")
    assert mailer.dang_bat() is False


def test_tat_khi_thieu_public_base_url(monkeypatch):
    """Gửi một thư chứa link gãy tệ hơn không gửi."""
    _cau_hinh(monkeypatch, smtp_host="smtp.vn", smtp_from="a@b.vn")
    assert mailer.dang_bat() is False


def test_bat_khi_du_ba_truong(monkeypatch):
    _cau_hinh(monkeypatch, smtp_host="smtp.vn", smtp_from="a@b.vn", public_base_url="https://p.vn")
    assert mailer.dang_bat() is True


def test_url_tuyet_doi_khong_nhan_doi_dau_gach(monkeypatch):
    _cau_hinh(monkeypatch, smtp_host="s", smtp_from="a@b.vn", public_base_url="https://p.vn/")
    assert mailer.url_tuyet_doi("/invite/abc") == "https://p.vn/invite/abc"


@pytest.mark.anyio
async def test_gui_tra_false_khi_tat_va_khong_nem(monkeypatch):
    _cau_hinh(monkeypatch)
    ok = await mailer.gui(den="x@y.vn", tieu_de="t", than_text="a", than_html="<p>a</p>")
    assert ok is False


@pytest.mark.anyio
async def test_gui_tat_in_than_thu_ra_stdout(monkeypatch, capsys):
    """Spec §5.2: mailer tắt phải IN THƯ RA STDOUT (không chỉ log warning) — dev
    copy link đặt mật khẩu từ console. Thân thư (chứa link) phải xuất hiện,
    không chỉ người nhận/tiêu đề."""
    _cau_hinh(monkeypatch)
    ok = await mailer.gui(
        den="nguoi_nhan@x.vn",
        tieu_de="Hoàn tất đăng ký",
        than_text="Đặt mật khẩu tại: https://portal.noblex.vn/invite/token-thu-nghiem",
        than_html="<p>...</p>",
    )
    assert ok is False, "vẫn phải trả False dù đã in ra stdout — invitePath phụ thuộc giá trị này"
    ra = capsys.readouterr().out
    assert "nguoi_nhan@x.vn" in ra
    assert "Hoàn tất đăng ký" in ra
    assert "https://portal.noblex.vn/invite/token-thu-nghiem" in ra, "thân thư (có link) phải in ra, không chỉ tiêu đề"


@pytest.mark.anyio
async def test_gui_nuot_loi_smtp_va_tra_false(monkeypatch):
    """§5.4: giao dịch đã commit trước khi gửi. Ném ra ngoài = 500 mô tả sai
    trạng thái hệ thống (tài khoản ĐÃ được tạo)."""
    _cau_hinh(monkeypatch, smtp_host="smtp.vn", smtp_from="a@b.vn", public_base_url="https://p.vn")

    async def _no(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr("portal.core.mailer.aiosmtplib.send", _no)
    ok = await mailer.gui(den="x@y.vn", tieu_de="t", than_text="a", than_html="<p>a</p>")
    assert ok is False


@pytest.mark.anyio
async def test_gui_nuot_loi_header_hop_le_va_tra_false(monkeypatch):
    """EmailMessage construction có thể ném khi header chứa ký tự xuống dòng.
    Phải nuốt lỗi này để không thành 500 khi account đã được tạo."""
    _cau_hinh(monkeypatch, smtp_host="smtp.vn", smtp_from="a@b.vn", public_base_url="https://p.vn")
    ok = await mailer.gui(den="x@y.vn", tieu_de="title\nBcc: attacker@evil.com", than_text="a", than_html="<p>a</p>")
    assert ok is False


# ── Ảnh nhúng CID ───────────────────────────────────────────────────────────


async def _bat_thu(monkeypatch, **kw):
    """Chặn `aiosmtplib.send` và trả về CHÍNH `EmailMessage` đã dựng.

    Canh cấu trúc MIME thật chứ không canh "hàm chạy không ném": phần `cid` sai
    vẫn gửi thành công, chỉ là ảnh không hiện ở phía người nhận — nên `return
    True` không chứng minh được gì.
    """
    _cau_hinh(monkeypatch, smtp_host="smtp.vn", smtp_from="a@b.vn", public_base_url="https://p.vn")
    giu = {}

    async def _send(msg, **_):
        giu["msg"] = msg

    monkeypatch.setattr("portal.core.mailer.aiosmtplib.send", _send)
    ok = await mailer.gui(den="x@y.vn", tieu_de="T", than_text="text", than_html="<p>html</p>", **kw)
    assert ok is True
    return giu["msg"]


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


@pytest.mark.anyio
async def test_khong_co_anh_thi_cau_truc_giu_nguyen_alternative(monkeypatch):
    """Bảo hiểm cho mọi thư KHÁC: thêm nhánh ảnh không được đổi hình dạng thư cũ."""
    msg = await _bat_thu(monkeypatch)
    assert msg.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in msg.get_payload()] == ["text/plain", "text/html"]


@pytest.mark.anyio
async def test_anh_nhung_dung_cay_alternative_related(monkeypatch):
    """Cấu trúc PHẢI là `alternative > [text, related > [html, ảnh]]`.

    Gọi `add_related` trên `msg` thay vì trên phần HTML biến thư thành `mixed` và
    ảnh rơi xuống thành một tệp ĐÍNH KÈM: bản text mất người đọc, còn người nhận
    thấy một thư có attachment lạ. Cả hai vẫn "gửi thành công".
    """
    msg = await _bat_thu(monkeypatch, anh_nhung=("logo-nx-agent", PNG))
    assert msg.get_content_type() == "multipart/alternative"
    text, lien_quan = msg.get_payload()
    assert text.get_content_type() == "text/plain"
    assert lien_quan.get_content_type() == "multipart/related", "ảnh phải nằm TRONG nhánh HTML"
    html, anh = lien_quan.get_payload()
    assert html.get_content_type() == "text/html"
    assert anh.get_content_type() == "image/png"


@pytest.mark.anyio
async def test_content_id_co_dau_ngoac_va_khop_cid_ben_html(monkeypatch):
    """`Content-ID` CÓ `<>`, còn `src="cid:…"` thì KHÔNG.

    Lệch một trong hai chỗ là ảnh không hiện và không lỗi nào phát ra — đúng loại
    lỗi chỉ phát hiện được bằng cách mở một thư thật ra xem, nên nó phải có test.
    """
    msg = await _bat_thu(monkeypatch, anh_nhung=("logo-nx-agent", PNG))
    anh = msg.get_payload()[1].get_payload()[1]
    assert anh["Content-ID"] == "<logo-nx-agent>"
    assert anh["Content-ID"][1:-1] == "logo-nx-agent"


@pytest.mark.anyio
async def test_anh_la_inline_khong_phai_dinh_kem(monkeypatch):
    """`inline` giữ ảnh khỏi danh sách đính kèm của client. Không có nó, người nhận
    thấy một thư có tệp lạ kèm theo — và với thư đặt mật khẩu thì đó là tín hiệu
    lừa đảo, không phải một chi tiết trình bày.
    """
    msg = await _bat_thu(monkeypatch, anh_nhung=("logo-nx-agent", PNG))
    anh = msg.get_payload()[1].get_payload()[1]
    assert anh.get_content_disposition() == "inline"


@pytest.mark.anyio
async def test_mailer_tat_khong_nem_du_co_anh(monkeypatch, capsys):
    """Nhánh in-ra-stdout không chạm tới ảnh (stdout không hiện được ảnh, và thứ
    lập trình viên cần copy là cái link) — nhưng nó cũng không được vỡ vì kwarg mới.
    """
    _cau_hinh(monkeypatch)
    assert (
        await mailer.gui(den="x@y.vn", tieu_de="T", than_text="link đây", than_html="<p>h</p>", anh_nhung=("c", PNG))
        is False
    )
    assert "link đây" in capsys.readouterr().out
