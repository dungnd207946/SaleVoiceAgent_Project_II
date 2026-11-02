"""Bộ test cho `modules/auth/thu.py` — nội dung hai thư đặt mật khẩu.

KHÔNG cần Docker: `thu.py` là hàm thuần, nhận chuỗi trả chuỗi. Đó chính là lý do
nội dung thư được tách khỏi `router.py` — ở trong router thì muốn canh một dòng
chữ cũng phải dựng cả app + Postgres.

Test ở đây canh HÌNH DẠNG (nút là bảng, không có `<style>`, URL có ở cả hai bản,
tên được escape), KHÔNG canh từng câu chữ. Canh câu chữ nghĩa là mỗi lần sửa
giọng văn phải sửa test — mà giọng văn thì còn sửa nhiều.
"""

import pytest

from portal.modules.auth import thu

URL = "https://portal.noblex.vn/invite/abc123XYZ"


@pytest.fixture(params=["dang_ky", "loi_moi_moi", "loi_moi_da_co"])
def mot_thu(request: pytest.FixtureRequest) -> thu.Thu:
    """Cả ba thư đi qua CÙNG bộ test hình dạng.

    Ba thư khác nhau ở đoạn mở đầu, giống nhau ở mọi thứ còn lại — nên mọi bất
    biến dưới đây phải đúng cho cả ba. Tham số hoá thay vì viết ba lần: bản
    trước của cặp thư này lệch nhau vì được sửa rời (một bản có dòng hạn 7 ngày
    ở thân, bản kia chỉ có ở cuối).
    """
    if request.param == "dang_ky":
        return thu.thu_dang_ky(ten="Nguyễn Văn A", email="a@x.vn", url=URL)
    if request.param == "loi_moi_moi":
        return thu.thu_loi_moi_moi(email="a@x.vn", ten_workspace="WS", url=URL)
    return thu.thu_loi_moi_da_co(email="a@x.vn", ten_workspace="WS", url=URL)


# ── Nút ─────────────────────────────────────────────────────────────────────


def test_nut_la_bang_co_bgcolor_khong_phai_link_tran(mot_thu: thu.Thu):
    """Yêu cầu người dùng 2026-08-22: nút bấm phải có UI như một button.

    `<a>` trần với `background-color` KHÔNG đủ — Outlook (Word engine) bỏ qua
    `padding` trên thẻ inline, nút teo lại thành một chữ có màu. Phép bọc
    `<table><td bgcolor>` là cách duy nhất ra được một khối bấm được ở cả Outlook
    lẫn Gmail; `bgcolor` là thuộc tính HTML nên nó sống sót qua cả những client
    lược bớt CSS.
    """
    h = mot_thu.than_html
    assert 'bgcolor="#0d7a5f"' in h, "nút phải có bgcolor accent ở thẻ td, không chỉ CSS"
    assert "display:inline-block" in h, "thẻ a phải là inline-block để padding có tác dụng"
    assert "padding:13px 26px" in h, "nút phải có padding thật, không phải một link có màu"


def test_nut_tro_dung_url_va_khong_gach_chan(mot_thu: thu.Thu):
    h = mot_thu.than_html
    assert f'href="{URL}"' in h
    assert "text-decoration:none" in h, "nút gạch chân thì đọc ra link, không ra nút"


# ── Bất biến của HTML thư ───────────────────────────────────────────────────


def test_khong_dung_the_style_va_khong_dung_class(mot_thu: thu.Thu):
    """Gmail CẮT BỎ `<style>` và mọi `class` trong thư.

    Nên toàn bộ trình bày phải là `style=` nội tuyến. Test này là cái chặn thói
    quen: người quen viết web sẽ tự nhiên gom CSS vào `<style>`, và thư vẫn "trông
    ổn" ở máy họ (Apple Mail giữ `<style>`) rồi vỡ ở Gmail — nơi phần lớn người
    nhận đang đọc.
    """
    h = mot_thu.than_html
    assert "<style" not in h, "Gmail cắt <style> — dùng style= nội tuyến"
    assert "class=" not in h, "Gmail cắt class — dùng style= nội tuyến"


def test_co_nen_trang_tuong_minh_tren_body(mot_thu: thu.Thu):
    """Client tối màu tự tô nền của nó nếu thư không tự khai — chữ `#14161a` trên
    nền đen là một thư không đọc được. Khai nền tường minh, đừng thừa hưởng.
    """
    assert "background-color:#f4f4f1" in mot_thu.than_html


def test_url_tran_co_mat_cho_client_chan_nut(mot_thu: thu.Thu):
    """Nút bị chặn / bị viết lại là chuyện thường ở mail doanh nghiệp. Không có
    URL dán tay được thì người nhận bế tắc mà không biết vì sao.

    `word-break:break-all` vì URL dài hơn khung 560px sẽ đẩy giãn cả bảng.
    """
    h = mot_thu.than_html
    assert h.count(URL) >= 2, "URL phải có ở CẢ nút và dòng dán tay"
    assert "word-break:break-all" in h


# ── Bản text ────────────────────────────────────────────────────────────────


def test_ban_text_khong_chua_the_html(mot_thu: thu.Thu):
    """`multipart/alternative` nghĩa là client CHỌN một trong hai bản. Bản text
    lọt thẻ HTML thì người đọc nó thấy mã nguồn.
    """
    t = mot_thu.than_text
    assert "<" not in t and ">" not in t, f"bản text lọt thẻ: {t!r}"


def test_ban_text_du_day_khong_phai_ba_dong(mot_thu: thu.Thu):
    """HTML dày kèm bản text ba dòng là đúng hình dạng bị bộ lọc chấm điểm spam
    cao — mà docstring `mailer.gui()` nói thư này PHẢI vào hộp thư chính.

    Ngưỡng 400 ký tự là một cái sàn thô, không phải một con số có ý nghĩa: nó chỉ
    ở đó để bản text không lặng lẽ tụt về một dòng khi ai đó sửa HTML mà quên nó.
    """
    assert len(mot_thu.than_text) > 400


def test_ban_text_giu_duoc_phep_trich_token_cua_conftest(mot_thu: thu.Thu):
    """`mailer_stub` ở conftest trích token bằng
    `than_text.split("/invite/")[-1].split()[0]`.

    Nghĩa là URL phải nằm RIÊNG MỘT DÒNG và là lần xuất hiện `/invite/` CUỐI CÙNG
    trong bản text. Dán URL giữa câu ("... tại {url}.") làm dấu chấm dính vào
    token và mọi test tròn vòng đăng ký đỏ với thông báo hoàn toàn vô nghĩa
    ("token không hợp lệ"). Canh ở đây để lỗi đó chết ngay tại chỗ sinh ra nó.
    """
    trich = mot_thu.than_text.split("/invite/")[-1].split()[0]
    assert trich == "abc123XYZ", f"phép trích token của conftest vỡ: lấy ra {trich!r}"


# ── An toàn ─────────────────────────────────────────────────────────────────


def test_ten_duoc_escape_truoc_khi_vao_html():
    """`name` là input người dùng (form đăng ký) và giờ nó ĐI VÀO thân HTML.

    Trước 2026-08-22 thân thư không nội suy gì nên không có lỗ; thêm lời chào là
    tự mở ra. Escape ở `thu.py` chứ không ở người gọi: người gọi thứ hai sẽ không
    biết mà escape.
    """
    t = thu.thu_dang_ky(ten="<script>alert(1)</script>", email="a@x.vn", url=URL)
    assert "<script>" not in t.than_html
    assert "&lt;script&gt;" in t.than_html


def test_email_cung_duoc_escape():
    """Cùng lý lẽ với `ten`. `email` đã qua validator của Pydantic, nhưng
    validator đó canh hình dạng email — nó không phải một phép escape HTML, và
    đừng để lớp sau phải tin vào ý định của lớp trước.
    """
    t = thu.thu_loi_moi_moi(email="a<b>@x.vn", ten_workspace="WS", url=URL)
    assert "a<b>@x.vn" not in t.than_html
    assert "a&lt;b&gt;@x.vn" in t.than_html


# ── Nội dung nghiệp vụ ──────────────────────────────────────────────────────


def test_ca_hai_ban_deu_noi_han_7_ngay(mot_thu: thu.Thu):
    """Hạn 7 ngày là `HAN_MOI` phía service. Người nhận không đọc được hằng số đó
    ở đâu ngoài thư này — bỏ nó ra là để họ tự phát hiện link đã chết.
    """
    assert "7 ngày" in mot_thu.than_text
    assert "7 ngày" in mot_thu.than_html


def test_co_duong_ra_cho_nguoi_nhan_lam(mot_thu: thu.Thu):
    """Thư đặt mật khẩu gửi tới hộp thư mà CHƯA AI xác nhận là của người đăng ký
    — đó là cả điểm của luồng này. Nên nó phải nói được cho người nhận nhầm biết
    họ không cần làm gì, và vì sao im lặng là an toàn.
    """
    assert "bỏ qua" in mot_thu.than_text.lower()


def test_hai_thu_khac_tieu_de(mot_thu: thu.Thu):
    """Người tự đăng ký đọc "Bạn được mời tham gia" là một câu SAI SỰ THẬT — cùng
    lý lẽ đã sinh ra `kind` ở `TokenXemRa`. Hai tiêu đề phải phân biệt được.
    """
    assert mot_thu.tieu_de
    assert (
        thu.thu_dang_ky(ten="A", email="a@x.vn", url=URL).tieu_de
        != thu.thu_loi_moi_moi(email="a@x.vn", ten_workspace="WS", url=URL).tieu_de
    )


def test_thu_dang_ky_chao_theo_ten():
    t = thu.thu_dang_ky(ten="Nguyễn Văn A", email="a@x.vn", url=URL)
    assert "Nguyễn Văn A" in t.than_html
    assert "Nguyễn Văn A" in t.than_text


def test_thu_loi_moi_khong_doi_ten_nguoi_nhan():
    """Quyết định 2026-08-22: giữ thư mời không mang TÊN NGƯỜI NHẬN (khác tên
    workspace, đã đảo lại cùng ngày — xem khối test ở cuối file).

    Không hàm nào trong hai hàm mời có nó trong tay: `thanh_vien.moi` chỉ có
    email, và kéo tên xuống đó là một chuỗi thay đổi qua `moi_thanh_vien` +
    `tao_user`. Chữ ký hai hàm này là chỗ ghi lại quyết định đó — test đỏ nếu ai
    thêm tham số mà không đọc.
    """
    import inspect

    for ham in (thu.thu_loi_moi_moi, thu.thu_loi_moi_da_co):
        tham_so = set(inspect.signature(ham).parameters)
        assert tham_so == {"email", "ten_workspace", "url"}, f"chữ ký {ham.__name__} đổi: {tham_so}"


# ── Logo ────────────────────────────────────────────────────────────────────


def test_logo_di_bang_cid_khong_bang_url_hay_data(mot_thu: thu.Thu):
    """`cid:` là đường DUY NHẤT còn lại cho ảnh trong thư.

    Ảnh remote (`https://…`) bị chặn mặc định ở phần lớn mail doanh nghiệp; `data:`
    URI thì Gmail và Outlook đều chặn trong `<img>`. Cả hai đều cho ra một ô vuông
    vỡ ở đúng chỗ nhận diện thương hiệu, và cả hai đều "trông ổn" trên máy người
    viết — nên phải có một bài canh chứ không phải một quy ước.
    """
    h = mot_thu.than_html
    assert f'src="cid:{thu.CID_LOGO}"' in h
    assert "<img" in h
    assert 'src="data:' not in h, "data: URI bị Gmail/Outlook chặn"
    assert 'src="http' not in h, "ảnh remote bị chặn mặc định — dùng cid:"


def test_thu_mang_theo_anh_va_no_la_png_that(mot_thu: thu.Thu):
    """Ảnh đi CÙNG `Thu`, không để người gọi tự nhớ ghép.

    Kiểm magic number chứ không chỉ kiểm khác rỗng: một tệp rỗng hoặc một tệp SVG
    bị đặt sai tên vẫn qua được phép kiểm `len() > 0`, rồi thư gửi đi với một ảnh
    không client nào mở được.
    """
    assert mot_thu.anh_nhung is not None
    cid, png = mot_thu.anh_nhung
    assert cid == thu.CID_LOGO
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_logo_dung_96x96_va_du_nho_de_gui():
    """96px cho một logo hiện ở 48px — 2× của màn retina, không hơn.

    Đọc kích thước từ chunk IHDR (byte 16-24 của PNG) thay vì qua Pillow: bài test
    này không có lý do gì để phụ thuộc một thư viện ảnh.

    Trần 20 KB vì ảnh này đi kèm MỌI thư đặt mật khẩu. Một PNG bị thay bằng bản
    2048px vẫn hiện đúng ở 48px nên không ai nhìn ra, chỉ có thư nặng lên.
    """
    _, png = thu.thu_loi_moi_moi(email="a@x.vn", ten_workspace="WS", url=URL).anh_nhung
    assert int.from_bytes(png[16:20], "big") == 96
    assert int.from_bytes(png[20:24], "big") == 96
    assert len(png) < 20_000, f"logo {len(png)} byte — quá nặng cho thứ đi kèm mọi thư"


def test_ten_he_thong_con_doc_duoc_khi_anh_bi_chan(mot_thu: thu.Thu):
    """`alt` ở đây là NỘI DUNG DỰ PHÒNG, không phải một thuộc tính a11y cho có.

    Người nhận chặn ảnh phải vẫn đọc được tên hệ thống ở đúng chỗ đó — và khối chữ
    cạnh logo cũng tồn tại vì lý do này: mất ảnh thì tên vẫn nguyên.
    """
    h = mot_thu.than_html
    assert 'alt="NobleX Agent Portal"' in h
    assert ">NobleX<" in h and ">Agent Portal<" in h


def test_logo_va_chu_nam_tren_MOT_hang_bang():
    """Hai ô của một `<tr>`, KHÔNG `display:flex` — Word engine của Outlook không
    có flex và hai khối sẽ rơi xuống hai dòng.
    """
    h = thu.thu_dang_ky(ten="A", email="a@x.vn", url=URL).than_html
    dau = h[h.index("<img") - 400 : h.index("<img") + 400]
    assert "display:flex" not in h
    assert "<td" in dau and "<tr>" in dau


def test_khong_con_chu_NobleX_Portal_cu():
    """Tên đúng là "NobleX Agent Portal" (yêu cầu người dùng 2026-08-22). Bản trước
    ghi "NobleX Portal" — thiếu chữ giữa, và đó là tên của một sản phẩm khác.
    """
    h = thu.thu_dang_ky(ten="A", email="a@x.vn", url=URL).than_html
    assert ">Portal</span>" not in h, "còn sót wordmark cũ"


def test_ten_he_thong_o_MOI_chuoi_deu_du_ba_tu(mot_thu: thu.Thu):
    """Tên hệ thống là "NobleX Agent Portal" — ĐỦ BA TỪ, ở mọi chỗ người nhận đọc.

    Bài này sinh ra từ một lỗi thật: đợt gắn logo chỉ đổi tên ở lockup và `alt`,
    còn TIÊU ĐỀ thư, thân thư và dòng ký vẫn ghi "NobleX Portal" — nên cùng một
    lá thư gọi hệ thống bằng hai cái tên, và cái tên sai lại nằm ở chỗ dễ thấy
    nhất (dòng tiêu đề trong hộp thư).

    Quét CẢ tiêu đề, CẢ hai thân: sửa từng chỗ một là đúng cách để bỏ sót chỗ thứ
    năm. `replace` rồi kiểm phần còn lại, thay vì đếm — đếm thì thêm một câu mới
    có tên đúng cũng làm test đỏ.
    """
    for nhan, chuoi in (("tiêu đề", mot_thu.tieu_de), ("text", mot_thu.than_text), ("html", mot_thu.than_html)):
        con_lai = chuoi.replace("NobleX Agent Portal", "")
        assert "NobleX Portal" not in con_lai, f"{nhan} còn tên thiếu chữ 'Agent'"


# ═══════════════════════════════════════════════════════════════════════════════
#  2026-08-22 — hai thư mời, cả hai NÓI TÊN WORKSPACE
# ═══════════════════════════════════════════════════════════════════════════════
#
# ĐẢO LẠI quyết định 2026-08-15 ("thư mời không mang tên workspace"). Lý lẽ cũ —
# "người nhận chưa có ngữ cảnh workspace nào, một cái tên lạ là thêm một câu hỏi"
# — viết khi câu hỏi của thư là "đặt mật khẩu đi". Nay câu hỏi là "có tham gia hay
# không", và không nói tham gia CÁI GÌ thì đó là câu hỏi không trả lời được.


def test_thu_moi_email_chua_co_tai_khoan_noi_ten_workspace():
    t = thu.thu_loi_moi_moi(email="a@x.vn", ten_workspace="An Phú Land", url="https://p.vn/invite/tk")
    assert "An Phú Land" in t.than_text
    assert "An Phú Land" in t.than_html
    assert "An Phú Land" in t.tieu_de


def test_thu_moi_email_chua_co_tai_khoan_khong_hua_tai_khoan_da_tao():
    """Bản cũ viết «Một tài khoản đã được tạo sẵn cho địa chỉ …» — nay là lời NÓI DỐI:
    không có gì được tạo cho tới khi người nhận bấm nút."""
    t = thu.thu_loi_moi_moi(email="a@x.vn", ten_workspace="An Phú Land", url="https://p.vn/invite/tk")
    assert "đã được tạo sẵn" not in t.than_text


def test_thu_moi_email_da_co_tai_khoan_noi_ten_workspace_va_email():
    t = thu.thu_loi_moi_da_co(email="b@x.vn", ten_workspace="Sunrise", url="https://p.vn/invite/tk")
    assert "Sunrise" in t.than_text
    assert "b@x.vn" in t.than_text


def test_ca_hai_thu_dung_nhan_nut_tham_gia_workspace():
    for t in (
        thu.thu_loi_moi_moi(email="a@x.vn", ten_workspace="WS", url="https://p.vn/invite/tk"),
        thu.thu_loi_moi_da_co(email="a@x.vn", ten_workspace="WS", url="https://p.vn/invite/tk"),
    ):
        assert "Tham gia workspace" in t.than_html
        assert "Đặt mật khẩu</a>" not in t.than_html


def test_thu_dang_ky_van_giu_nhan_dat_mat_khau():
    """Thư tự đăng ký KHÔNG có workspace nào để nói, và nút của nó vẫn đúng nghĩa."""
    t = thu.thu_dang_ky(ten="A", email="a@x.vn", url="https://p.vn/invite/tk")
    assert "Đặt mật khẩu</a>" in t.than_html


def test_ten_workspace_duoc_escape():
    t = thu.thu_loi_moi_moi(email="a@x.vn", ten_workspace="<script>x</script>", url="https://p.vn/invite/tk")
    assert "<script>" not in t.than_html


def test_ca_hai_thu_giu_duoc_phep_trich_token_cua_conftest():
    """⚠ BẤT BIẾN CHẾT NGƯỜI. `mailer_stub` trích token bằng
    `than_text.split("/invite/")[-1].split()[0]`. Dán URL giữa câu, hoặc nhắc lại
    `/invite/` sau URL, làm mọi test tròn vòng đỏ với một thông báo vô nghĩa."""
    for t in (
        thu.thu_loi_moi_moi(email="a@x.vn", ten_workspace="WS", url="https://p.vn/invite/tokenthat"),
        thu.thu_loi_moi_da_co(email="a@x.vn", ten_workspace="WS", url="https://p.vn/invite/tokenthat"),
    ):
        assert t.than_text.split("/invite/")[-1].split()[0] == "tokenthat"


def test_thu_loi_moi_cu_da_bi_go():
    """Hàm cũ không mang tên workspace nên không còn ai được gọi nó."""
    assert not hasattr(thu, "thu_loi_moi")
