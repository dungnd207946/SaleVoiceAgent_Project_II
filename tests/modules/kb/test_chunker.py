"""Chunker là hàm thuần — test không cần Docker, không cần DB.

MỘT chiến lược duy nhất từ 2026-08-14 (trước đó năm cái). Biên quan trọng hơn đường
thường: `overlap >= max_chars` là vòng lặp vô hạn nếu cài ẩu, text rỗng phải trả `[]` chứ
không phải một chunk rỗng (nó vẫn tốn một lần embed và một point), và bảng bị xé mất hàng
tiêu đề là agent đọc số mà không biết đó là giá hay diện tích.
"""

from portal.modules.kb.contracts import ChunkSpec
from portal.modules.kb.index import chunker

SPEC = ChunkSpec(max_chars=1000, overlap=100, min_chars=300)


def _texts(text: str, spec: ChunkSpec = SPEC, **kw) -> list[str]:
    return [c.text for c in chunker.split(text, spec, **kw)]


def test_text_rong_tra_list_rong():
    assert chunker.split("", SPEC) == []
    assert chunker.split("   \n  ", SPEC) == []


def test_quick_fact_ngan_gop_thanh_mot_chunk():
    """11 field mỗi cái một `##` một dòng — cắt theo section thuần sẽ ra 11 chunk ~30 ký
    tự. Đây là ca chống-cắt-vụn quan trọng nhất vì nó là hình dạng của MỌI dự án."""
    text = "\n\n".join(f"## Trường {i}\ngiá trị {i}" for i in range(11))
    ra = chunker.split(text, SPEC)
    assert len(ra) == 1, [c.text[:30] for c in ra]
    assert "Trường 0" in ra[0].text and "Trường 10" in ra[0].text


def test_gop_cung_cha_mang_duong_dan_CHA_khong_bia_nhan_ghep():
    text = "# Chính sách\n\n## Đợt 1\nnội dung một\n\n## Đợt 2\nnội dung hai"
    ra = chunker.split(text, SPEC)
    assert len(ra) == 1
    assert ra[0].section_path == ("Chính sách",), ra[0].section_path


def test_khong_gop_xuyen_cha():
    """Hai section khác cha nói hai chuyện — gói chung là trộn ngữ cảnh."""
    text = "# A\n\n## A1\n" + "x" * 400 + "\n\n# B\n\n## B1\n" + "y" * 400
    ra = chunker.split(text, SPEC)
    duong_dan = [c.section_path for c in ra]
    assert ("A", "A1") in duong_dan and ("B", "B1") in duong_dan, duong_dan
    for c in ra:
        assert not ("x" * 10 in c.text and "y" * 10 in c.text), "trộn hai nhánh vào một chunk"


def test_section_path_theo_dung_thu_bac():
    text = "# Một\n\n## Hai\n\n### Ba\n" + "z" * 500
    ra = chunker.split(text, SPEC)
    assert ra[-1].section_path == ("Một", "Hai", "Ba"), ra[-1].section_path


def test_nhay_cap_tieu_de_khong_no():
    """`### x` ngay sau `# a` — markdown thật đầy trường hợp này."""
    ra = chunker.split("# a\n\n### x\n" + "q" * 500, SPEC)
    assert ra[-1].section_path == ("a", "x")


def test_root_khong_can_co_mat_trong_text():
    """Tên phân khu và tiêu đề tài liệu vào `root`, không prepend một dòng `#` vào text."""
    ra = chunker.split("## Tổng quan\n" + "n" * 500, SPEC, root=("Phân khu Ven Sông",))
    assert ra[0].section_path == ("Phân khu Ven Sông", "Tổng quan")
    assert "Phân khu Ven Sông" not in ra[0].text


def test_van_ban_khong_co_tieu_de_nao_van_ra_chunk_hop_le():
    ra = chunker.split("một đoạn văn xuôi không có dấu thăng nào cả.", SPEC)
    assert len(ra) == 1 and ra[0].section_path == ()


def test_hashtag_khong_phai_tieu_de():
    """`#hashtag` thiếu khoảng trắng — không được nhận là tiêu đề."""
    ra = chunker.split("#khongphaitieude\nnội dung", SPEC)
    assert ra[0].section_path == ()


def test_bang_dai_bi_cat_va_MOI_manh_co_hang_tieu_de():
    """Luật cũ giữ nguyên khối bảng "dù vượt max_chars" — ở trần 1000 khối đó vượt cửa sổ
    512 token của model, nên phần đuôi bị cắt cụt lúc nhúng và nửa dưới bảng KHÔNG được
    nhúng gì. Nay cắt theo hàng và lặp tiêu đề, nên mỗi mảnh vẫn đọc được độc lập."""
    bang = "| Đợt | % |\n| --- | --- |\n" + "".join(f"| đợt số {i} | 10 |\n" for i in range(60))
    ra = _texts(f"## Tiến độ\n{bang}", ChunkSpec(max_chars=300, overlap=0, min_chars=0))
    assert len(ra) > 1, "bảng này phải bị cắt, nếu không test không đo gì"
    for manh in ra:
        assert "| Đợt | % |" in manh, f"mảnh thiếu hàng tiêu đề: {manh[:60]!r}"
        assert "| --- | --- |" in manh, "mảnh thiếu dòng phân cách — không còn là bảng markdown"
    assert "| đợt số 59 |" in ra[-1], "hàng cuối bảng bị mất"


def test_bang_khong_co_dong_phan_cach_van_cat_duoc():
    bang = "".join(f"| {i} | x |\n" for i in range(60))
    ra = _texts(bang, ChunkSpec(max_chars=200, overlap=0, min_chars=0))
    assert len(ra) > 1
    assert "| 59 | x |" in ra[-1]


def test_bang_ma_rieng_tieu_de_da_qua_tran_thi_giu_nguyen_khoi():
    """Lặp một tiêu đề dài hơn trần vào mỗi mảnh làm MỌI mảnh vượt trần — mất mát đó lớn
    hơn mất mát khi để nguyên một khối."""
    tieu_de = "| " + "cột rất dài " * 20 + "|"
    bang = f"{tieu_de}\n| --- |\n| a |\n| b |\n"
    ra = _texts(bang, ChunkSpec(max_chars=100, overlap=0, min_chars=0))
    assert len(ra) == 1


def test_doan_van_dai_bi_cat_khong_giua_tu():
    """Chunk mở đầu bằng "hiết khấu" là một vector không tra cứu được bằng gì."""
    doan = "Khách hàng thanh toán sớm 95% giá trị căn hộ được chiết khấu ba phần trăm. "
    ra = _texts(doan * 40, ChunkSpec(max_chars=800, overlap=150, min_chars=0))
    assert len(ra) > 1, "văn bản này phải bị cắt, nếu không test không đo gì"
    for c in ra:
        assert c[0].isupper() or c[0].isdigit(), f"chunk mở đầu giữa từ: {c[:40]!r}"


def test_doan_van_ket_thuc_tron_cau():
    doan = "Chiết khấu ba phần trăm cho khách thanh toán sớm chín mươi lăm phần trăm. "
    ra = _texts(doan * 40, ChunkSpec(max_chars=800, overlap=150, min_chars=0))
    for c in ra[:-1]:
        assert c.endswith((".", "!", "?", ";", ":")), f"chunk cắt ngang câu: …{c[-40:]!r}"


def test_overlap_chi_dung_trong_mot_doan_van_lien_tuc():
    text = "".join(f"câu số {i}. " for i in range(300))
    spec = ChunkSpec(max_chars=400, overlap=100, min_chars=0)
    ra = _texts(text, spec)
    assert ra[0][-50:] in ra[1], "chunk sau không mang đuôi của chunk trước"
    khong = _texts(text, ChunkSpec(max_chars=400, overlap=0, min_chars=0))
    assert khong[0][-50:] not in khong[1], "phép đo phải phân biệt có và không overlap"


def test_khong_overlap_giua_hai_section():
    """`section_path` đã cấp ngữ cảnh — nhân bản chữ ở mép section là tốn vô cớ."""
    text = "## A\n" + "a" * 600 + "\n\n## B\n" + "b" * 600
    ra = _texts(text, SPEC)
    assert len(ra) == 2
    assert "a" not in ra[1] and "b" not in ra[0]


def test_overlap_lon_hon_max_chars_khong_treo():
    """Cấu hình sai không được thành vòng lặp vô hạn — nó phải kết thúc, kể cả xấu."""
    ra = _texts("x" * 1000, ChunkSpec(max_chars=100, overlap=500, min_chars=0))
    assert 0 < len(ra) < 100


def test_manh_vun_gop_vao_chunk_truoc():
    """Mảnh ngắn đứng riêng thiếu ngữ cảnh nhưng vẫn cạnh tranh khi tìm kiếm."""
    doan = "Một câu dài vừa đủ để đẩy phần dư sang chunk kế tiếp cho ngắn. "
    ra = _texts(doan * 15, ChunkSpec(max_chars=500, overlap=80, min_chars=200))
    assert all(len(c) >= 200 for c in ra), [len(c) for c in ra]


def test_min_chars_bang_khong_thi_tat_phep_gop():
    doan = "Câu ngắn. "
    ra = _texts(doan * 60, ChunkSpec(max_chars=200, overlap=0, min_chars=0))
    assert any(len(c) < 200 for c in ra), "phải còn mảnh ngắn khi tắt phép gộp"


def test_moi_chunk_khong_vuot_tran_tru_bang_khong_cat_duoc():
    text = "# Dự án\n\n" + "\n\n".join(f"## Mục {i}\n" + "chữ " * 300 for i in range(4))
    for c in chunker.split(text, SPEC):
        assert len(c.text) <= SPEC.max_chars, f"chunk {len(c.text)} ký tự vượt trần"


def test_anh_khong_roi_cau_dan():
    """Dòng trống giữa câu dẫn và ảnh làm `_tach_khoi` xả thành hai khối; khi mép gói
    rơi đúng đó thì chunk sau MỞ ĐẦU bằng ảnh và mất câu giải thích nó là ảnh gì.
    Đo trên sổ tay CTV: 2/33 chunk dính lỗi này.

    Đoạn lấp `filler` là bắt buộc để đo đúng lỗi: không có nó, ba khối (câu dẫn/ảnh/câu
    sau) cộng lại chưa tới `max_chars` nên `_goi_cung_cha` gói cả section vào một chunk
    và không khối nào bị xả ĐÚNG giữa câu dẫn và ảnh — bài kiểm xanh dù lỗi còn nguyên.
    Độ dài 900 đặt mép gói (972 ký tự cộng tiêu đề) rơi lọt vào khoảng giữa câu dẫn và
    ảnh, đúng kịch bản đo trên sổ tay CTV.
    """
    from portal.modules.kb.contracts import ChunkSpec
    from portal.modules.kb.index import chunker

    filler = (
        "Đây là đoạn hướng dẫn chi tiết cho nhân viên mới về quy trình sử dụng hệ thống "
        "AINA khi hỗ trợ khách hàng qua tổng đài. " * 8
    )[:900]
    text = (
        "## Đăng nhập\n\n"
        f"{filler}\n\n"
        "Ở màn đăng nhập, bấm **Quên mật khẩu**.\n\n"
        "![Màn đăng nhập AINA](https://portal.vn/api/v1/public/files/a.png)\n\n"
        "Nhập số điện thoại đã đăng ký.\n"
    )
    parts = chunker.split(text, ChunkSpec(max_chars=1000, overlap=100, min_chars=300))
    assert len(parts) > 1, "văn bản này phải bị gói thành nhiều chunk, nếu không test không đo gì"
    for m in parts:
        assert not m.text.lstrip().startswith("!["), f"chunk mở đầu bằng ảnh: {m.text[:60]!r}"


def test_anh_dau_tai_lieu_khong_co_cau_dan_van_chay():
    """Không có khối nào trước thì ảnh đứng một mình — không được nổ."""
    from portal.modules.kb.contracts import ChunkSpec
    from portal.modules.kb.index import chunker

    text = "![chỉ có ảnh](https://portal.vn/api/v1/public/files/a.png)\n\nSau đó là chữ.\n"
    parts = chunker.split(text, ChunkSpec(max_chars=1000, overlap=100, min_chars=300))
    assert parts and "chỉ có ảnh" in parts[0].text


def test_anh_khong_gop_xuyen_section():
    """Bài cũ dựng A/B nhỏ tới mức luôn gói chung thành MỘT chunk — `section_path` của
    chunk gộp là CHA CHUNG rỗng (`A`/`B` là anh em cấp 1), nên danh sách `cua_a` (lọc
    theo `section_path` khác rỗng) luôn rỗng và assertion đi qua bất kể code làm gì.

    Viết lại với A và B ở hai nhánh `#` KHÁC NHAU (không anh em, `_cung_cha` trả False
    thật sự) và B đủ nhiều ảnh để phải tách hơn một chunk — vừa để `section_path` của
    A/B không co về rỗng (lọc còn có ý nghĩa), vừa để việc dựng chunk có cửa để phá vỡ:
    bản trước khi sửa (ba cơ chế cũ) đẩy con số của SECTION B lên tới 1857 ký tự (gần
    gấp đôi trần) vì chunk cuối ảnh gộp nguyên chunk trước bất kể lệch nhánh cha hay
    không. Chunk mang nhãn A không được chứa ảnh của B, và không chunk nào (kể cả của
    B) được vượt `max_chars + overlap` — mức trần mà `_repair_leading_images` giữ."""
    duong_dan = "".join(f"![anh B {i}](https://portal.vn/api/v1/public/files/b{i}.png)\n\n" for i in range(30))
    text = "# P1\n\n## A\n" + ("Nội dung riêng của A. " * 40) + "DẤU_HIỆU_CUỐI_A.\n\n# P2\n\n## B\n\n" + duong_dan
    spec = ChunkSpec(max_chars=1000, overlap=100, min_chars=0)
    parts = chunker.split(text, spec)
    cua_a = [m for m in parts if m.section_path and m.section_path[-1] == "A"]
    assert cua_a, "phải còn chunk mang nhãn A, nếu không test không đo gì"
    assert all("anh B" not in m.text for m in cua_a), "ảnh của B bị kéo vào chunk của A"
    tran = spec.max_chars + spec.overlap + 2
    for m in parts:
        assert len(m.text) <= tran, f"chunk {len(m.text)} ký tự vượt {tran} (max_chars+overlap+2)"


def test_qua_tran_do_lui_overlap_dam_dung_anh_khong_dong_trong_bao():
    """Route thứ nhất review đo được, ngoài ba cơ chế cũ: `_diem_cat` chọn một điểm cắt
    AN TOÀN (mảnh sau không mở đầu bằng ảnh), nhưng `_diem_lui` sau đó lùi lại tối đa
    `overlap` ký tự để tìm ranh giới tự nhiên — và trên đường lùi đó có thể đi NGANG QUA
    một dòng ảnh, khiến mảnh THỰC SỰ được cắt lại mở đầu bằng ảnh. Hai bài cũ của file
    này chỉ dùng `overlap=0` nên không đo được lỗi này. Dựng bằng `ChunkSpec()` mặc
    định (`overlap=100`, đúng cấu hình production) và một khối liền không dấu cách
    (không xuống dòng kép) trước ảnh — hình dạng hay gặp khi bóc từ docx/PDF."""
    cau = "Khach hang thanh toan som duoc chiet khau ba phan tram tren tong gia tri hop dong. "
    anh = "![anh](https://portal.vn/api/v1/public/files/x.png)"
    text = (cau * 10) + "\n" + anh + "\n" + (cau * 4)
    parts = chunker.split(text, ChunkSpec())
    assert len(parts) > 1, "văn bản này phải bị cắt, nếu không test không đo gì"
    for p in parts:
        assert not p.text.lstrip().startswith("!["), f"chunk mở đầu bằng ảnh: {p.text[:60]!r}"


def test_tai_lieu_toan_anh_cham_hard_cut_khong_xe_doi_the_anh():
    """Route thứ hai: `_diem_cat` bản CŨ từ chối MỌI ranh giới nếu mảnh sau mở đầu bằng
    ảnh — trên một tài liệu CHỈ TOÀN ẢNH thì mọi ranh giới đều dẫn tới ảnh, guard từ
    chối sạch từng loại rồi rơi về `return max_chars` MÙ, cắt ngay giữa một thẻ
    `![...](...)`. Mảnh vỡ ra không còn khớp mẫu ảnh nên `_khong_de_anh_mo_dau_chunk`
    cũ (dựa vào khớp trọn dòng) không nhận ra để vá — một mã ảnh bị xé làm đôi, mất
    vĩnh viễn với bất kỳ ai tra theo URL đó. Bản giản lược (bỏ guard) không còn cơ chế
    nào từ chối ranh giới nữa nên `_diem_cat` cắt sạch tại `\\n\\n` như bình thường."""
    anh = [f"![anh {i}](https://portal.vn/api/v1/public/files/x{i}.png)" for i in range(40)]
    text = "\n\n".join(anh)
    parts = _texts(text, ChunkSpec(max_chars=1000, overlap=0, min_chars=0))
    assert len(parts) > 1, "phải bị cắt, nếu không test không đo gì"
    noi_dung = "\n".join(parts)
    for a in anh:
        assert a in noi_dung, f"mã ảnh bị xé đôi, mất khỏi mọi chunk: {a!r}"


def test_bang_roi_toi_nhieu_anh_khong_xe_va_khong_mo_dau_bang_anh():
    """Bảng đứng trước một LOẠT ảnh (18 tấm) — tổ hợp đủ để vừa cần vá chunk mở đầu
    bằng ảnh (mượn hàng cuối của bảng làm câu dẫn), vừa có nguy cơ chạm hard-cut fallback
    nếu nhóm ảnh gộp lại vượt trần. Bản cũ (ba cơ chế) từng xé một mã ảnh làm đôi ở
    đúng tổ hợp này."""
    bang = "| Cot A | Cot B |\n| --- | --- |\n" + "".join(f"| Hang {i} | gia tri {i} |\n" for i in range(10))
    anh = [f"![screenshot {i}](https://portal.vn/api/v1/public/files/s{i}.png)" for i in range(18)]
    text = "## Ket qua\n" + bang + "\n" + "\n\n".join(anh) + "\n"
    parts = _texts(text, ChunkSpec(max_chars=1000, overlap=0, min_chars=0))
    assert len(parts) > 1, "phải bị cắt, nếu không test không đo gì"
    noi_dung = "\n".join(parts)
    for a in anh:
        assert a in noi_dung, f"mã ảnh bị xé đôi: {a!r}"
    for p in parts:
        assert not p.lstrip().startswith("!["), f"chunk mở đầu bằng ảnh: {p[:60]!r}"


def test_von_gop_cau_dan_gioi_han_boi_max_chars_cong_overlap():
    """Trần THẬT của cách vá bằng cách mượn: `max_chars + overlap + 2` (2 ký tự nối
    `\\n\\n`), KHÔNG phải gần gấp đôi `max_chars` như cách gộp nguyên chunk trước từng
    đo được (1679 ký tự trên trần 1000). Dựng một chunk toàn ảnh sát trần đứng ngay sau
    một câu dẫn dài — chunk vá phải VƯỢT `max_chars` (chứng minh phép vá có chạy, không
    phải một chunk tình cờ vừa khít) nhưng không được vượt trần mới."""
    cau_dai = (
        "Day la mot cau van rat dai duoc viet ra chi de lam day dong cuoi cung cua doan "
        "van dan truoc anh cho du dai vuot qua gioi han muon toi da " * 2
    )[:200]
    spec = ChunkSpec()
    prose = ("Gioi thieu chung. " * 40)[: spec.max_chars - len(cau_dai) - 4]
    lead = f"{prose}\n{cau_dai}"
    anh = [f"![screenshot {i}](https://portal.vn/api/v1/public/files/s{i}.png)" for i in range(20)]
    text = f"{lead}\n\n" + "\n\n".join(anh) + "\n"
    parts = chunker.split(text, spec)
    tran = spec.max_chars + spec.overlap + 2
    assert any(len(p.text) > spec.max_chars for p in parts), "phải có chunk vượt max_chars, nếu không phép vá chưa chạy"
    for p in parts:
        assert len(p.text) <= tran, f"chunk {len(p.text)} ký tự vượt trần vá {tran}"


def test_khoi_gop_qua_tran_bi_cat_lai_dung_mep_anh():
    """Câu dẫn 880 ký tự + dòng ảnh 196 ký tự vượt `max_chars=1000` — khối đã được
    `_attach_image_to_lead_in` gộp lại rơi vào nhánh `_cat_van`. Cắt tại đúng dòng
    trống giữa câu dẫn và ảnh (điểm gộp) tái tạo lại chính lỗi vừa vá: chunk sau chỉ
    còn mỗi ảnh. `min_chars=0` để tắt hai lưới an toàn dựa vào độ dài (`_can_lai_duoi`,
    `_gop_manh_vun`) — chúng tình cờ né được lỗi này ở kích thước khác, không phải vì
    đã sửa đúng chỗ."""
    filler = (
        "Đây là đoạn hướng dẫn chi tiết cho nhân viên mới về quy trình sử dụng hệ thống "
        "AINA khi hỗ trợ khách hàng qua tổng đài. " * 12
    )
    lead_in = filler[:880]
    duoi_dai = "a" * (196 - len("![Ảnh minh hoạ](https://portal.vn/api/v1/public/files/.png)"))
    image_line = f"![Ảnh minh hoạ](https://portal.vn/api/v1/public/files/{duoi_dai}.png)"
    assert len(image_line) == 196
    text = f"{lead_in}\n\n{image_line}\n"
    parts = _texts(text, ChunkSpec(max_chars=1000, overlap=0, min_chars=0))
    assert len(parts) > 1, "văn bản này phải bị cắt, nếu không test không đo gì"
    for m in parts:
        assert not m.lstrip().startswith("!["), f"chunk mở đầu bằng ảnh: {m[:60]!r}"


def test_bang_sat_tran_roi_toi_anh_khong_de_anh_mo_dau_chunk():
    """Bảng ~992 ký tự (dưới trần) rồi tới một dòng ảnh — `_attach_image_to_lead_in`
    cố ý không gộp vì khối trước là bảng (tránh đi sai nhánh `_cat_bang`), nên mép gói
    của `_goi_cung_cha` rơi đúng giữa hai khối và chunk ảnh đứng một mình."""

    def bang(so_hang: int, dem: int) -> str:
        hang = "".join(
            f"| Hàng {i} | Giá trị dài hơn một chút để đạt độ dài mong muốn {i}{'x' * dem} |\n" for i in range(so_hang)
        )
        return "| Cột A | Cột B |\n| --- | --- |\n" + hang

    bang_text = bang(14, 4)
    assert len(bang_text) == 992
    image_line = "![Ảnh chụp màn hình kết quả](https://portal.vn/api/v1/public/files/screenshot.png)"
    text = f"{bang_text}\n{image_line}\n"
    parts = _texts(text, ChunkSpec(max_chars=1000, overlap=0, min_chars=0))
    assert any("Hàng 13" in m for m in parts), "mất nội dung bảng"
    assert any("screenshot.png" in m for m in parts), "mất nội dung ảnh"
    for m in parts:
        assert not m.lstrip().startswith("!["), f"chunk mở đầu bằng ảnh: {m[:60]!r}"


def test_dong_dai_muon_tron_cau_khong_cat_giua_tu():
    """Ca thật đo trên `hdsd-s3-khach.md`: nguồn ngắt dòng cứng giữa "phòng" và "ngủ"
    (một đoạn văn, hai dòng vật lý, không có dòng trắng ở giữa). Bản cũ chỉ nhìn dòng
    vật lý CUỐI CÙNG rồi cắt mù theo ký tự, nên mượn nguyên "ngủ, khu vực. Dùng khi
    khách chưa chốt dự án nào." — mở đầu chunk bằng đúng nửa sau bị bổ đôi của "phòng
    ngủ". Câu dẫn đúng phải gộp lại đoạn rồi mượn trọn câu, không đứt ở giữa từ."""
    text = (
        "Tra cứu sản phẩm tìm xuyên nhiều dự án theo nhu cầu của khách: khoảng giá, "
        "diện tích, số phòng\nngủ, khu vực. Dùng khi khách chưa chốt dự án nào."
    )
    cau_dan = chunker._muon_cau_dan(text, 100)
    assert cau_dan == "khoảng giá, diện tích, số phòng ngủ, khu vực. Dùng khi khách chưa chốt dự án nào."


def test_muon_cau_dan_cat_mu_theo_ky_tu_be_doi_mot_tu():
    """Cùng lỗi ở dạng đơn giản nhất, không cần ngắt dòng cứng: cắt mù theo ký tự trên
    MỘT dòng vật lý vẫn có thể rơi ngay giữa một từ của câu đứng trước câu cuối. Bản cũ
    `s[-42:]` bổ đôi "khu" thành "kh" + "u"."""
    line = "Bán kính khoảng giá, diện tích, số phòng ngủ, khu vực. Dùng khi khách chưa chốt dự án nào."
    cau_dan = chunker._muon_cau_dan(line, 42)
    assert cau_dan == "Dùng khi khách chưa chốt dự án nào."


def test_cau_qua_dai_lui_ve_ranh_gioi_tu_khong_vuot_gioi_han():
    """Câu cuối cùng dài hơn `gioi_han` và không có dấu câu nào bên trong để bám vào —
    quyết định: lùi về ranh giới TỪ gần nhất, GIỮ TRONG `gioi_han` (không cố giữ trọn
    câu bằng cách vượt trần). Trần `max_chars + overlap + 2` tồn tại để chặn kích thước
    chunk sau khi vá; một câu dài vô hạn thì bất kỳ ưu tiên "giữ trọn câu" nào cũng làm
    trần đó vô nghĩa, trong khi kết quả vẫn chỉ là MỘT MẢNH câu dù có vượt trần hay
    không. Lùi tới ranh giới từ (thay vì cắt mù) là cải thiện đáng giá mà không tốn cái
    giá đó."""
    line = "Day la mot cau rat dai khong co dau cham nao ben trong de dua vao lam ranh gioi tu nhien ca"
    cau_dan = chunker._muon_cau_dan(line, 20)
    assert cau_dan == "gioi tu nhien ca"
    assert len(cau_dan) <= 20


def test_so_thu_tu_kieu_3_3_khong_tinh_la_het_cau():
    """ "3.3." (mã mục, toàn chữ số và dấu chấm) không phải dấu chấm hết câu — nó xuất
    hiện y hệt vậy trong đề mục thật của sổ tay CTV ("### 3.3. Tra cứu sản phẩm"). Tách
    sai ở đó cho ra một "câu" chỉ vỏn vẹn "3.3.", dễ bị loại khi câu thật theo sau nó
    không đủ chỗ trong `gioi_han`."""
    assert chunker._tach_cau("3.3. Tra cứu sản phẩm giúp khách tìm nhanh hơn.") == [
        "3.3. Tra cứu sản phẩm giúp khách tìm nhanh hơn."
    ]
    assert chunker._tach_cau("Câu Một. 3.3. Câu Hai theo sau mã mục.") == [
        "Câu Một.",
        "3.3. Câu Hai theo sau mã mục.",
    ]


def test_dong_ngan_vua_du_giu_nguyen():
    """Dòng đã nằm gọn trong `gioi_han` — hành vi cũ (trả nguyên dòng) không đổi."""
    assert chunker._muon_cau_dan("Câu ngắn vừa đủ.", 100) == "Câu ngắn vừa đủ."


def test_toan_anh_khong_co_gi_de_muon():
    """Mọi dòng đều là ảnh — không có câu văn xuôi nào, trả `None`."""
    text = "![a](https://portal.vn/api/v1/public/files/a.png)\n\n![b](https://portal.vn/api/v1/public/files/b.png)"
    assert chunker._muon_cau_dan(text, 100) is None


def test_ranh_gioi_khong_duoc_roi_giua_mot_section():
    """`## A` gần đầy trần rồi tới `## B` gồm HAI đoạn cách nhau bằng dòng trống — hai
    `_Khoi` cùng path. Gói ở tầng KHỐI (cũ) làm tổng dồn tích luỹ tràn ĐÚNG GIỮA hai
    đoạn của B (B1 nhét vừa với A, B2 thì không), xẻ B ra hai chunk dù B tự nó rất nhỏ.
    Gói ở tầng SECTION thì A một mình bị đẩy sang chunk riêng, B đi trọn vào chunk sau."""
    text = "## A\n" + "x" * 700 + "\n\n## B\n" + "y" * 200 + "\n\n" + "z" * 200
    ra = chunker.split(text, ChunkSpec(max_chars=1000, overlap=0, min_chars=0))
    ca_b = [c for c in ra if ("y" * 200 in c.text) or ("z" * 200 in c.text)]
    assert any("y" * 200 in c.text and "z" * 200 in c.text for c in ca_b), [c.text[:20] for c in ca_b]


def test_section_qua_tran_moi_manh_mang_full_duong_dan():
    """Section `Ba` (cấp 3, dưới `Một › Hai`) một mình vượt trần — mọi mảnh sinh ra,
    không riêng mảnh cuối, phải mang ĐỦ đường dẫn ba cấp chứ không phải chỉ `("Ba",)`."""
    text = "# Một\n\n## Hai\n\n### Ba\n" + ("đoạn dài để vượt trần. " * 30)
    ra = chunker.split(text, ChunkSpec(max_chars=300, overlap=0, min_chars=0))
    assert len(ra) > 1, "phải bị cắt ra nhiều mảnh, nếu không test không đo gì"
    for c in ra:
        assert c.section_path == ("Một", "Hai", "Ba"), c.section_path


def test_khoi_chi_co_gach_ngang_khong_sinh_chunk():
    """`---` (hr markdown) không mang một từ nào — không chunk nào được phép chỉ chứa
    nó, kể cả khi nó đứng lẻ loi không kèm tiêu đề nào."""
    assert chunker.split("---", SPEC) == []


def test_trang_bia_chi_co_tieu_de_noi_vao_doan_sau():
    """Đo trên CSBH thật: trang bìa (tiêu đề + «Tháng 07.2026») đứng riêng một chunk ~90 ký tự."""
    text = (
        "# CHÍNH SÁCH BÁN HÀNG\n## DỰ ÁN VINHOMES WONDER CITY\n--- Tháng 07.2026---\n\n"
        "### I. VỀ GIÁ BÁN\n" + "Giá bán đã bao gồm VAT và kinh phí bảo trì. " * 30
    )
    ra = chunker.split(text, SPEC)
    assert "CHÍNH SÁCH BÁN HÀNG" in ra[0].text and "Giá bán" in ra[0].text
    assert all(len(c.text) <= SPEC.max_chars for c in ra)


def test_cau_dan_ket_thuc_bang_hai_cham_di_cung_bang_ngay_sau():
    bang = "| Đợt | Tỷ lệ |\n| --- | --- |\n" + "".join(f"| Đợt {i} | {i}% giá trị hợp đồng |\n" for i in range(60))
    ra = _texts(f"## Tiến độ\n3. Tiến độ giải ngân:\n\n{bang}")
    assert not any(c.strip() == "3. Tiến độ giải ngân:" for c in ra)
    assert "3. Tiến độ giải ngân:" in ra[0] and "| Đợt 0 |" in ra[0]
    assert all(len(c) <= SPEC.max_chars for c in ra)


def test_doan_ngan_khong_phai_cau_dan_thi_khong_noi_sang_khoi_khac():
    dau = "## Khu vực\nQuảng Ninh\n\n## Chủ đầu tư\nVinhomes"
    text = f"{dau}\n\n## Cơ cấu\n### Phân khu\n" + "Gồm nhiều phân khu. " * 60
    ra = chunker.split(text, SPEC)
    assert ra[0].text == dau


def test_hang_bang_qua_tran_cat_theo_o_va_giu_ten_hang():
    """Đo trên CSBH thật: bảng song ngữ có một hàng 2.224 ký tự — model chỉ nhúng phần đầu."""
    dai = "Thanh toán theo tiến độ xây dựng, kèm điều kiện ký hợp đồng mua bán. " * 12
    bang = (
        "| Đợt thanh toán | Lịch thanh toán | Thanh toán chuẩn |\n|---|---|---|\n"
        f"| **Đợt 1** | {dai} | {dai} |\n| Đợt 2 | Sau 30 ngày | 20% |\n"
    )
    ra = _texts(f"## Lịch thanh toán\n{bang}")
    assert all(len(c) <= SPEC.max_chars for c in ra), [len(c) for c in ra]
    cua_dot_1 = [c for c in ra if "Đợt thanh toán: **Đợt 1**" in c]
    assert len(cua_dot_1) >= 2, "hàng dài phải ra nhiều mảnh, mảnh nào cũng mang tên hàng"
    assert all(c.startswith("## Lịch thanh toán") for c in cua_dot_1)
    assert any("| Đợt 2 | Sau 30 ngày | 20% |" in c for c in ra), "hàng thường vẫn giữ dạng bảng"
