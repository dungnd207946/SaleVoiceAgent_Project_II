"""Markdown → list chunk có đường dẫn section. Hàm thuần: không I/O, không DB.

MỘT chiến lược duy nhất (2026-08-14). Trước đó có năm: `facts`/`atomic`/`per_row` gộp
nguyên văn, `markdown` cắt theo độ dài, `structured_md` giữ nguyên khối bảng. Ba lý do
thay hẳn:

1. `structured_md` giữ nguyên khối bảng "dù vượt max_chars" — ở trần 1000 luật đó TỰ PHÁ
   CHÍNH NÓ: một bảng 40 hàng ra chunk ~5000 ký tự ≈ 1250 token, vượt cửa sổ 512 token của
   e5-large ⇒ model cắt cụt phần đuôi và nửa dưới bảng KHÔNG được nhúng gì, im lặng. Nay
   bảng bị cắt theo HÀNG và mỗi mảnh LẶP LẠI hàng tiêu đề + dòng phân cách, nên mỗi mảnh
   vẫn là một bảng markdown đọc được độc lập.
2. Cắt theo độ dài không biết nội dung thuộc phần nào. Nay cắt theo CẤP TIÊU ĐỀ và mỗi
   chunk mang `section_path`, nên chunk thứ 5 của một tài liệu vẫn biết nó là "Chính sách
   bán hàng › Đợt 2 › Ưu đãi thanh toán".
3. `facts` không cắt gì cả, nên một dự án luôn là một chunk bất kể dài bao nhiêu.

ĐỔI TRẦN 1800 → 1000, và đó là một quyết định NGƯỢC với comment cũ trong `settings.py`
("số cũ 800 xé vụn vô cớ") — KHÔNG phải một lần gõ nhầm. Lý do: khi cắt theo cấp tiêu đề,
mỗi chunk là một đơn vị ngữ nghĩa thật chứ không phải một đoạn cắt theo độ dài; ở chế độ đó
chunk nhỏ cho độ chính xác tra cứu cao hơn, và `section_path` bù lại phần ngữ cảnh đã mất.

CHỐNG CẮT VỤN là phần khó nhất, không phải phần cắt. Nội dung dự án là 11 quick-fact, mỗi
cái một dòng dưới một `##` riêng; cắt theo section thuần sẽ ra 11 chunk ~30 ký tự. Nên các
section CÙNG CHA được gói chung tới sát trần (`_goi_cung_cha`), và chunk gói chung mang
đường dẫn của CHA. Không gói xuyên cha: hai section khác cha nói hai chuyện khác nhau.
"""

import re
from dataclasses import dataclass

from portal.modules.kb.contracts import ChunkSpec

_TIEU_DE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_HANG_BANG = re.compile(r"^\s*\|.*\|\s*$")
_PHAN_CACH_BANG = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")
_CO_CHU = re.compile(r"\w", re.UNICODE)

_RANH = ("\n\n", "\n", ". ", "! ", "? ", "; ", ": ", ", ", " ")
_LUI_TOI_DA = 0.4


@dataclass(frozen=True, slots=True)
class Chunk:
    """`text` là nội dung THUẦN — chưa gắn tiền tố tên dự án.

    Tiền tố do `clients/rag.py` gắn khi dựng chuỗi đem nhúng, và `content_hash` tính
    trên `text` này chứ KHÔNG trên chuỗi đã gắn tiền tố: nhờ vậy đổi tên dự án không
    làm đổi dấu tay, nên không phải nhúng lại cả cây con (xem hợp đồng payload §4).
    """

    text: str
    section_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Khoi:
    """Một khối liền mạch trong MỘT section: đoạn văn, hoặc một bảng."""

    text: str
    path: tuple[str, ...]
    la_bang: bool


@dataclass(frozen=True, slots=True)
class _Section:
    """MỘT section thật: tiêu đề (nếu có) cộng toàn bộ thân, kể cả khi thân bị
    `_tach_khoi` xé thành nhiều `_Khoi` (dòng trống, chuyển bảng ↔ văn xuôi). Đây là
    ĐƠN VỊ ranh giới — `_goi_cung_cha` không bao giờ cắt vào giữa một `_Section`."""

    path: tuple[str, ...]
    khoi: tuple[_Khoi, ...]
    text: str


def _gom_section(khoi: list[_Khoi]) -> list[_Section]:
    """`_Khoi` LIÊN TIẾP cùng path gộp thành một section — nguồn xé chúng ra chỉ vì
    dòng trống hoặc chuyển bảng/văn xuôi bên trong CÙNG một tiêu đề, không phải vì đó
    là hai section khác nhau."""
    ra: list[_Section] = []
    nhom: list[_Khoi] = []
    for k in khoi:
        if nhom and nhom[-1].path != k.path:
            ra.append(_Section(nhom[0].path, tuple(nhom), "\n\n".join(x.text for x in nhom)))
            nhom = []
        nhom.append(k)
    if nhom:
        ra.append(_Section(nhom[0].path, tuple(nhom), "\n\n".join(x.text for x in nhom)))
    return ra


def split(text: str, spec: ChunkSpec, *, root: tuple[str, ...] = ()) -> list[Chunk]:
    """`root` là đường dẫn tổ tiên KHÔNG có mặt trong `text`.

    Dùng cho tên phân khu và tiêu đề tài liệu: đặt chúng vào `root` thay vì prepend một
    dòng `#` vào nội dung, vì chữ bóc từ docx/xlsx đã mang sẵn `#`/`##` của chính nó —
    thêm một cấp vào text sẽ làm tiêu đề của tài liệu thành ANH EM với tiêu đề ta chèn,
    không phải con của nó.
    """
    if not text.strip():
        return []
    khoi = _tach_khoi(text, root)
    if not khoi:
        return []
    return _goi_cung_cha(khoi, spec)


def _tach_khoi(text: str, root: tuple[str, ...]) -> list[_Khoi]:
    """Đi một lượt qua dòng, dựng cây bằng một ngăn xếp tiêu đề.

    Ngăn xếp thay cho cây thật vì ta chỉ cần ĐƯỜNG DẪN của từng khối, không cần đi lại
    cây. Tiêu đề cấp N đẩy hết cấp ≥ N ra khỏi ngăn xếp — nhờ đó `### x` ngay sau `# a`
    (nhảy cấp, markdown thật đầy trường hợp này) vẫn ra đường dẫn `a › x` chứ không nổ.

    DÒNG TIÊU ĐỀ Ở LẠI TRONG TEXT của khối đầu tiên thuộc section đó. Hai lý do, cả hai
    đều là lỗi nếu bỏ nó đi:
    · nội dung dự án là `## Khu vực` + một dòng giá trị — bỏ tiêu đề thì chunk còn lại
      `Long Biên\n\nNoble\n\n12000`, một dãy giá trị không nhãn;
    · `content_hash` băm text này, nên đổi tiêu đề một mục phải được nhận là thay đổi
      thật. Nhãn ở `section_path` KHÔNG vào dấu tay (đó là chỗ cho tên dự án đổi mà không
      phải nhúng lại), nên nếu tiêu đề cũng chỉ nằm ở đó thì đổi nó là thay đổi vô hình.
    """
    ra: list[_Khoi] = []
    ngan_xep: list[tuple[int, str]] = []
    dem: list[str] = []
    trong_bang = False
    cho: list[tuple[int, str]] = []

    def xa():
        noi_dung = "\n".join(dem).strip()
        dem.clear()
        if not noi_dung or not _CO_CHU.search(noi_dung):
            return  # "---"/"***" một mình không mang một từ nào — không đáng một chunk
        if cho:
            noi_dung = "\n".join([*(d for _, d in cho), noi_dung])
            cho.clear()
        ra.append(_Khoi(noi_dung, root + tuple(t for _, t in ngan_xep), trong_bang))

    for dong in text.splitlines():
        m = _TIEU_DE.match(dong)
        if m:
            xa()
            trong_bang = False
            cap = len(m.group(1))
            while ngan_xep and ngan_xep[-1][0] >= cap:
                ngan_xep.pop()
            while cho and cho[-1][0] >= cap:
                cho.pop()
            ngan_xep.append((cap, m.group(2)))
            cho.append((cap, dong.strip()))
            continue

        la_bang = bool(_HANG_BANG.match(dong))
        if la_bang != trong_bang or (not dong.strip() and not la_bang):
            xa()
            trong_bang = la_bang
        dem.append(dong)

    xa()
    return ra


def _starts_with_image(text: str) -> bool:
    """Dòng không-trắng ĐẦU TIÊN của `text` bắt đầu bằng một thẻ ảnh Markdown — kiểm
    tiền tố, không đòi khớp trọn dòng: một dòng bị hard-cut xén dở dang vẫn phải bị
    nhận ra, không thì nó lọt qua `_repair_leading_images`."""
    for dong in text.splitlines():
        if dong.strip():
            return dong.lstrip().startswith("![")
    return False


def _goi_cung_cha(khoi: list[_Khoi], spec: ChunkSpec) -> list[Chunk]:
    """Gói các SECTION (không phải khối con) liên tiếp CÙNG CHA tới sát trần — một
    chunk chứa một hoặc nhiều section TRỌN VẸN. Ranh giới chỉ được phép rơi GIỮA hai
    section; một section một mình đã vượt trần là ngoại lệ DUY NHẤT bị tách, và tách
    ở `_cat_section` chứ không phải ở đây."""
    ra: list[Chunk] = []
    dem: list[_Section] = []

    def xa():
        if dem:
            ra.append(Chunk("\n\n".join(s.text for s in dem), _duong_dan_chung([s.path for s in dem])))
            dem.clear()

    for s in _gom_section(khoi):
        qua_dai = len(s.text) > spec.max_chars
        dan = None
        if qua_dai and dem and _ngan(dem, spec) and _la_dan(dem[-1].text) and _lien_quan(dem[-1].path, s.path):
            dan = "\n\n".join(x.text for x in dem)
            dem.clear()
        if qua_dai or (dem and not _cung_cha(dem[-1].path, s.path)):
            xa()
        if qua_dai:
            ra.extend(Chunk(m, s.path) for m in _co_dan(dan, lambda sp, s=s: _cat_section(s, sp), spec))
            continue
        da_co = sum(len(x.text) + 2 for x in dem)
        # Gom cho ĐỦ, không gom cho ĐẦY: qua sàn rồi thì thôi hút thêm mục. Gói tới sát
        # trần làm loãng chunk — đo trên sổ tay AINA, «9.3 Điều kiện để rút» gói chung
        # với «9.4 Rút tiền» thành 996 ký tự và rơi khỏi top-3 của chính câu hỏi về nó.
        # Không khai sàn ⇒ đích là trần, đúng hành vi cũ (`min_chars=0` = "không có sàn",
        # không phải "sàn bằng 0" — đọc theo nghĩa sau thì mọi mục đứng riêng một chunk).
        du = spec.min_chars or spec.max_chars
        if dem and (da_co >= du or da_co + len(s.text) > spec.max_chars):
            xa()
        dem.append(s)

    xa()
    return _gop_manh_vun(_repair_leading_images(ra, spec), spec)


def _cat_section(s: _Section, spec: ChunkSpec) -> list[str]:
    """`s` một mình đã vượt `max_chars` — nơi DUY NHẤT ranh giới được phép rơi vào
    giữa một section. Gói các `_Khoi` con của nó tới sát trần y hệt `_goi_cung_cha`
    (không cần xét cùng cha — mọi khối ở đây vốn đã cùng một section); một khối con tự
    nó cũng vượt trần (một bảng dài, một đoạn văn dài) thì cắt riêng bằng `_cat_bang`
    hoặc `_cat_van` như trước. Mọi mảnh trả về mang chung `s.path` — FULL đường dẫn phân
    cấp, không chỉ tiêu đề trong cùng — do `_goi_cung_cha` tự gắn ở nơi gọi."""
    ra: list[str] = []
    dem: list[_Khoi] = []

    def xa():
        if dem:
            ra.append("\n\n".join(k.text for k in dem))
            dem.clear()

    for k in s.khoi:
        qua_dai = len(k.text) > spec.max_chars
        if qua_dai:
            dan = None
            if dem and sum(len(x.text) + 2 for x in dem) < spec.min_chars and _la_dan(dem[-1].text):
                dan = "\n\n".join(x.text for x in dem)
                dem.clear()
            xa()
            cat = _cat_bang if k.la_bang else _cat_van
            ra.extend(_co_dan(dan, lambda sp, t=k.text, c=cat: c(t, sp), spec))
            continue
        if dem and sum(len(x.text) + 2 for x in dem) + len(k.text) > spec.max_chars:
            xa()
        dem.append(k)

    xa()
    return ra


def _repair_leading_images(chunks: list[Chunk], spec: ChunkSpec) -> list[Chunk]:
    """BẤT BIẾN DUY NHẤT: không chunk nào được mở đầu bằng ảnh — một URL không mang
    nghĩa gì cho embedding model, chunk như vậy trống rỗng với tìm kiếm ngữ nghĩa dù
    không hề trống ký tự. Đây là nơi DUY NHẤT luật này được cưỡng chế (dọn từ ba cơ chế
    rải rác — gộp khối lúc dựng cây, từ chối điểm cắt, một lượt hậu xử lý — hai cái đầu
    vẫn lọt: `_diem_lui` lùi ngược lên đúng một ảnh sau khi điểm cắt đã an toàn, và
    guard cũ tự cắn đuôi trên tài liệu toàn ảnh — mọi ranh giới đều dẫn tới ảnh, guard
    từ chối sạch rồi rơi về cắt mù giữa dòng).

    Mượn CÓ GIỚI HẠN (`spec.overlap`) đúng MỘT dòng văn xuôi gần cuối nhất của chunk
    TRƯỚC, không gộp nguyên cả chunk trước: gộp nguyên đo được ra chunk 1679 ký tự trên
    trần 1000, và trần tồn tại vì model cắt cụt PHẦN ĐUÔI lúc nhúng — gộp nguyên đẩy
    đúng nội dung thật của chunk đang sửa ra khỏi cửa sổ đó. Mượn một dòng thì trần mới
    là `max_chars + overlap`, cùng bậc với overlap đã dùng ở `_cat_van`.

    Chunk trước không còn dòng văn xuôi nào để mượn (chính nó cũng toàn ảnh) thì CHỊU,
    không sửa: ép mượn một dòng ảnh khác dán vào chỉ đổi chỗ ảnh mở đầu, không giải
    quyết gì. Cùng lý do khi không có chunk trước cùng cha.

    Một dãy dài các khối toàn-ảnh cùng cha, chỉ có đúng một câu mở đầu, làm câu đó LAN
    TRUYỀN qua suốt dãy: chunk vừa được sửa lại đóng vai "chunk trước" cho lượt mượn kế
    tiếp, và câu nó mang cũng chính là câu đã mượn. Đo được: 150 ảnh liên tiếp cắt thành
    5 chunk, cả 5 mang nguyên byte một câu. Chấp nhận có chủ ý: một câu lặp lại vẫn hơn
    hẳn một chunk mở đầu bằng ảnh và không một chữ nào.
    """
    ra: list[Chunk] = []
    for c in chunks:
        if ra and _starts_with_image(c.text) and _cung_cha(ra[-1].section_path, c.section_path):
            cau_dan = _muon_cau_dan(ra[-1].text, spec.overlap)
            if cau_dan is not None:
                ra.append(Chunk(f"{cau_dan}\n\n{c.text}", c.section_path))
                continue
        ra.append(c)
    return ra


_KET_THUC_CAU = re.compile(r"[.?!:;]+(?=\s|$)")
_SO_THU_TU = re.compile(r"^[\d.]+$")


def _doan_van(dong: str) -> bool:
    """`dong` là một dòng văn xuôi tiếp nối được — không trắng, không ảnh, không tiêu
    đề, không hàng bảng. Dùng để gộp lại các dòng bị ngắt cứng của CÙNG một câu trước
    khi cắt câu trong `_muon_cau_dan`."""
    s = dong.strip()
    return bool(s) and not s.startswith("![") and not _TIEU_DE.match(dong) and not _HANG_BANG.match(dong)


def _tach_cau(doan: str) -> list[str]:
    """Cắt `doan` thành câu theo `.?!:;`. Số thứ tự kiểu "3.3." (từ đầu câu tới dấu
    chấm chỉ toàn chữ số và dấu chấm) không tính là hết câu — nó là mã mục lục/đề mục,
    không phải dấu câu, và nếu tách ở đó thì "3.3." dễ bị mất khi câu thật theo sau nó
    không đủ chỗ trong `gioi_han`."""
    cau: list[str] = []
    dau = 0
    for m in _KET_THUC_CAU.finditer(doan):
        manh = doan[dau : m.end()]
        if not _SO_THU_TU.match(manh.strip()):
            cau.append(manh)
            dau = m.end()
    duoi = doan[dau:]
    if duoi.strip():
        cau.append(duoi)
    return [c.strip() for c in cau if c.strip()]


def _muon_cau_dan(text: str, gioi_han: int) -> str | None:
    """Câu (hoặc vài câu cuối) văn xuôi gần cuối nhất của `text`, đủ `gioi_han` ký tự
    (`<= 0` = không giới hạn, cùng quy ước `min_chars` của file này). `None` nếu mọi
    dòng đều là ảnh — không có gì để mượn.

    GỘP các dòng vật lý LIỀN NHAU của cùng một đoạn trước khi cắt câu: nguồn docx/md hay
    ngắt dòng cứng GIỮA CÂU (đó không phải ranh giới đoạn) — nhìn đúng một dòng vật lý
    như bản cũ từng mượn một mẩu bắt đầu giữa từ: "ngủ, khu vực. Dùng khi khách chưa
    chốt dự án nào." là phần ĐUÔI bị ngắt dòng cứng của "...số phòng ngủ, khu vực...",
    ranh giới cắt nằm ở chỗ nguồn xuống dòng chứ không phải do `gioi_han`. Dừng gộp ở
    dòng trắng, dòng ảnh, dòng tiêu đề, hoặc dòng bảng — các dòng đó không phải phần
    tiếp nối của cùng một câu.

    Mượn CẢ CÂU, không cắt mù giữa từ. Câu cuối cùng một mình đã vượt `gioi_han` (không
    còn dấu câu nào bên trong để dựa vào — một đoạn liền không chấm câu) thì lùi về
    RANH GIỚI TỪ gần nhất trong đúng `gioi_han` ký tự cuối, bỏ từ đầu bị cắt dở thay vì
    giữ nguyên và xé đôi nó: kết quả vẫn luôn `<= gioi_han` như quy ước cũ (trần
    `max_chars + overlap + 2` không đổi), chỉ đổi ĐIỂM lùi từ giữa từ sang đầu từ kế
    tiếp. Không giữ nguyên cả câu bất kể độ dài: trần này chặn kích thước chunk sau khi
    vá (mục đích ban đầu của `overlap`), câu dài vô hạn thì trần đó mất tác dụng."""
    dong = text.splitlines()
    cuoi = len(dong) - 1
    while cuoi >= 0 and (not dong[cuoi].strip() or dong[cuoi].strip().startswith("![")):
        cuoi -= 1
    if cuoi < 0:
        return None

    bat = cuoi
    while bat > 0 and _doan_van(dong[bat]) and _doan_van(dong[bat - 1]):
        bat -= 1
    doan = " ".join(d.strip() for d in dong[bat : cuoi + 1])
    if gioi_han <= 0:
        return doan

    cau = _tach_cau(doan) or [doan]
    cuoi_cau = cau[-1]
    if len(cuoi_cau) > gioi_han:
        if cuoi_cau[-gioi_han - 1] == " ":
            return cuoi_cau[-gioi_han:]  # đã đúng ranh giới từ, khỏi lùi thêm
        cat = cuoi_cau[-gioi_han:]
        vt = cat.find(" ")
        return cat[vt + 1 :] if vt != -1 else cat

    muon = [cuoi_cau]
    do_dai = len(cuoi_cau)
    for c in reversed(cau[:-1]):
        them = len(c) + 1
        if do_dai + them > gioi_han:
            break
        muon.insert(0, c)
        do_dai += them
    return " ".join(muon)


def _cung_cha(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Cùng cha = cùng đường dẫn, hoặc là hai section anh em (khác nhau ở cấp cuối).

    Một khối nằm ngay dưới cha (đoạn mở đầu, đường dẫn NGẮN hơn một cấp) cũng tính là
    cùng cha với các con của nó: `["Chính sách"]` gói được với `["Chính sách","Đợt 1"]`.
    """
    return a == b or a[:-1] == b[:-1] or a == b[:-1] or a[:-1] == b


def _lien_quan(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Cùng cha, hoặc `b` nằm trong `a` ở bất kỳ độ sâu nào (gốc `()` không tính là tổ tiên)."""
    return _cung_cha(a, b) or (len(a) > 0 and b[: len(a)] == a)


def _ngan(dem: list, spec: ChunkSpec) -> bool:
    return sum(len(x.text) + 2 for x in dem) < spec.min_chars


def _co_dan(dan: str | None, cat, spec: ChunkSpec) -> list[str]:
    """Nối đoạn dẫn ngắn vào đầu mảnh đầu tiên do `cat(spec)` cắt ra.

    Mảnh đầu không còn chỗ thì cắt lại với trần trừ đi phần dẫn; trần còn lại quá thấp thì
    để đoạn dẫn đứng riêng như cũ.
    """
    manh = cat(spec)
    if not dan or not manh:
        return ([dan] if dan else []) + manh
    if len(dan) + 2 + len(manh[0]) > spec.max_chars:
        tran = spec.max_chars - len(dan) - 2
        if tran < spec.max_chars // 2:
            return [dan, *manh]
        manh = cat(ChunkSpec(max_chars=tran, overlap=min(spec.overlap, tran // 4), min_chars=spec.min_chars))
    return [f"{dan}\n\n{manh[0]}", *manh[1:]]


_KET_CAU = (".", "!", "?", ";", "…")


def _la_dan(text: str) -> bool:
    """Đoạn chỉ có tiêu đề / câu dẫn: dòng cuối là tiêu đề hoặc kết thúc bằng «:», hoặc là một dòng
    ngắn không dấu kết câu đứng ngay sau toàn tiêu đề (trang bìa: tiêu đề + «Tháng 07.2026»)."""
    dong = [d.strip() for d in text.splitlines() if d.strip()]
    if not dong or _HANG_BANG.match(dong[-1]):
        return False
    cuoi = dong[-1].strip("*_ ")
    if dong[-1].startswith("#") or cuoi.endswith(":"):
        return True
    return (
        len(dong) > 1 and all(d.startswith("#") for d in dong[:-1]) and len(cuoi) <= 40 and not cuoi.endswith(_KET_CAU)
    )


def _duong_dan_chung(duong_dan: list[tuple[str, ...]]) -> tuple[str, ...]:
    """Mọi đường dẫn giống nhau → dùng nguyên. Khác nhau → dùng CHA chung.

    Không bịa một nhãn ghép ("Đợt 1 + Đợt 2"): nhãn đó không có trong tài liệu nào và
    người đọc sẽ đi tìm nó.
    """
    dau = duong_dan[0]
    if all(p == dau for p in duong_dan):
        return dau
    ngan_nhat = min(len(p) for p in duong_dan)
    chung: list[str] = []
    for i in range(ngan_nhat):
        muc = duong_dan[0][i]
        if all(p[i] == muc for p in duong_dan):
            chung.append(muc)
        else:
            break
    return tuple(chung)


def _cat_bang(text: str, spec: ChunkSpec) -> list[str]:
    """Cắt bảng theo HÀNG, lặp phần đầu (dòng tiêu đề section + hàng tiêu đề bảng + dòng
    phân cách) ở mỗi mảnh.

    Không giữ nguyên khối như luật cũ: khối vượt cửa sổ 512 token của model thì phần đuôi
    bị cắt cụt lúc nhúng, im lặng — tức "bảo vệ bảng" lại là cách chắc chắn nhất để mất
    nửa dưới của nó.

    Phần đầu gồm cả dòng `##` nếu có: `_tach_khoi` gắn tiêu đề section vào khối đầu tiên
    của section, mà với một section chỉ có bảng thì khối đó CHÍNH LÀ bảng. Lặp nó vào mỗi
    mảnh làm mỗi mảnh tự nói được nó thuộc mục nào.
    """
    dong = [d for d in text.splitlines() if d.strip()]
    if not dong:
        return []
    i = 0
    while i < len(dong) and not _HANG_BANG.match(dong[i]):
        i += 1
    dau: list[str] = dong[:i]
    if i < len(dong):
        dau.append(dong[i])
        if i + 1 < len(dong) and _PHAN_CACH_BANG.match(dong[i + 1]):
            dau.append(dong[i + 1])
    than = dong[len(dau) :]
    if not than:
        return ["\n".join(dau)]

    tien_to = "\n".join(dau)

    if len(tien_to) + 2 >= spec.max_chars:
        return [text.strip()]

    ra: list[str] = []
    hien_tai: list[str] = []
    for d in than:
        if len(tien_to) + 1 + len(d) > spec.max_chars:
            if hien_tai:
                ra.append("\n".join([tien_to, *hien_tai]))
                hien_tai = []
            ra.extend(_cat_hang(dau, d, spec))
            continue
        thu = len(tien_to) + 1 + sum(len(x) + 1 for x in hien_tai) + len(d)
        if hien_tai and thu > spec.max_chars:
            ra.append("\n".join([tien_to, *hien_tai]))
            hien_tai = []
        hien_tai.append(d)
    if hien_tai:
        ra.append("\n".join([tien_to, *hien_tai]))
    return ra


def _o(dong: str) -> list[str]:
    return [o.strip().replace("<br>", " / ") for o in re.split(r"(?<!\\)\|", dong.strip().strip("|"))]


def _cat_hang(dau: list[str], hang: str, spec: ChunkSpec) -> list[str]:
    """Một hàng bảng tự nó đã vượt trần: thành các dòng «Cột: giá trị», mảnh nào cũng mở bằng
    tiêu đề mục và ô đầu của hàng để còn biết đang nói về hàng nào."""
    tieu_de = [d for d in dau if not _HANG_BANG.match(d)]
    cot = next((_o(d) for d in dau if _HANG_BANG.match(d) and not _PHAN_CACH_BANG.match(d)), [])
    o = _o(hang)
    ten = cot if len(cot) == len(o) else [f"Cột {i + 1}" for i in range(len(o))]
    dong = [f"{t}: {v}" if t else v for t, v in zip(ten, o, strict=True) if v]
    if not dong:
        return [hang]
    mo = "\n".join([*tieu_de, dong[0]])
    if len(mo) > spec.max_chars // 2:
        mo, dong = "\n".join(tieu_de)[: spec.max_chars // 4], dong
    else:
        dong = dong[1:]
    ra: list[str] = []
    hien: list[str] = []
    for d in dong:
        if len(mo) + 1 + len(d) > spec.max_chars:
            if hien:
                ra.append("\n".join([mo, *hien]))
                hien = []
            tran = spec.max_chars - len(mo) - 1
            ra.extend(f"{mo}\n{m}" for m in _cat_van(d, ChunkSpec(tran, min(spec.overlap, tran // 4), 0)))
            continue
        if hien and len(mo) + 1 + sum(len(x) + 1 for x in hien) + len(d) > spec.max_chars:
            ra.append("\n".join([mo, *hien]))
            hien = []
        hien.append(d)
    if hien or not ra:
        ra.append("\n".join([mo, *hien]))
    return ra


def _diem_cat(text: str, max_chars: int) -> int:
    """Vị trí cắt ≤ `max_chars`, lùi về ranh giới tự nhiên gần nhất.

    KHÔNG né ảnh ở đây — né rồi vẫn lọt (guard cũ tự cắn đuôi trên tài liệu toàn ảnh:
    mọi ranh giới đều dẫn tới ảnh, từ chối sạch rồi rơi về cắt mù giữa dòng, tệ hơn
    không né gì cả). Một chunk mở đầu bằng ảnh sau khi cắt ở đây được sửa MỘT LẦN, ở
    `_repair_leading_images` sau khi mọi chunk đã thành hình — xem docstring ở đó.

    Không tìm được ranh giới nào (một khối liền không dấu cách nào trong cửa sổ) thì
    trả `max_chars` như cũ — vẫn phải kết thúc chứ không được từ chối vô hạn.
    """
    if len(text) <= max_chars:
        return len(text)
    som_nhat = int(max_chars * (1 - _LUI_TOI_DA))
    for d in _RANH:
        vt = text.rfind(d, som_nhat, max_chars)
        if vt != -1:
            return vt + len(d)
    return max_chars


def _diem_lui(text: str, cat: int, overlap: int) -> int:
    """Lùi `overlap` rồi tiến tới ranh giới gần nhất. `overlap >= cat` là cấu hình sai —
    bỏ overlap, đừng để bước tiến còn ~1 ký tự và sinh nghìn chunk gần trùng."""
    tho = max(cat - overlap, 1) if overlap < cat else cat
    for d in _RANH:
        vt = text.find(d, tho, cat)
        if vt != -1:
            return vt + len(d)
    return tho


def _cat_van(text: str, spec: ChunkSpec) -> list[str]:
    """Đoạn văn dài hơn trần — chỗ DUY NHẤT còn dùng overlap.

    Mép giữa hai section không cần overlap vì `section_path` đã cấp ngữ cảnh; mép giữa
    hai nửa của một câu chuyện liên tục thì cần, không thì nửa sau mất chủ ngữ.
    """
    ra: list[str] = []
    con = text
    while len(con) > spec.max_chars:
        cat = _diem_cat(con, spec.max_chars)
        ra.append(con[:cat].strip())
        con = con[_diem_lui(con, cat, spec.overlap) :].lstrip()
    con = con.strip()
    if con:
        ra.append(con)
    return _can_lai_duoi(ra, spec)


def _can_lai_duoi(manh: list[str], spec: ChunkSpec) -> list[str]:
    """Đuôi ngắn hơn `min_chars` thì CHIA LẠI hai mảnh cuối cho đều, không dồn vào mảnh
    trước.

    Dồn vào mảnh trước là cách cũ, và nó cho ra chunk VƯỢT TRẦN — đúng thứ trần tồn tại
    để chặn, vì vượt cửa sổ 512 token của model là phần đuôi bị cắt cụt lúc nhúng, im
    lặng. Chia lại thì cả hai mảnh đều ≤ trần (tổng ≤ trần + min < 2×trần) và không mảnh
    nào còn quá ngắn.
    """
    if spec.min_chars <= 0 or len(manh) < 2 or len(manh[-1]) >= spec.min_chars:
        return manh
    gop = f"{manh[-2]} {manh[-1]}".strip()
    if len(gop) <= spec.max_chars:
        return [*manh[:-2], gop]
    giua = _diem_cat(gop, len(gop) // 2 + 1)
    return [*manh[:-2], gop[:giua].strip(), gop[giua:].strip()]


def _gop_manh_vun(chunks: list[Chunk], spec: ChunkSpec) -> list[Chunk]:
    """Mảnh ngắn hơn `min_chars` gộp vào chunk TRƯỚC nếu cùng cha.

    Chạy sau cùng vì mảnh vụn sinh ra ở ba đường khác nhau (đuôi của `_cat_van`, mảnh
    cuối của `_cat_bang`, một section ngắn không gói được với ai) — vá ở từng đường là
    ba bản sao của cùng một luật.

    CHỈ gộp khi kết quả VẪN dưới trần. Thà để một chunk ngắn hơn ngưỡng còn hơn một chunk
    vượt trần: chunk ngắn chỉ kém ngữ cảnh, chunk vượt trần bị model cắt cụt lúc nhúng và
    phần đuôi biến mất mà không có lỗi nào.
    """
    if spec.min_chars <= 0:
        return chunks
    ra: list[Chunk] = []
    for c in chunks:
        vua = ra and len(ra[-1].text) + len(c.text) + 2 <= spec.max_chars
        ngan = len(c.text) < spec.min_chars and not _la_dan(c.text)
        if vua and ngan and _cung_cha(ra[-1].section_path, c.section_path):
            truoc = ra[-1]
            ra[-1] = Chunk(f"{truoc.text}\n\n{c.text}", _duong_dan_chung([truoc.section_path, c.section_path]))
        else:
            ra.append(c)
    return _noi_dan_vao_sau(ra, spec)


def _noi_dan_vao_sau(chunks: list[Chunk], spec: ChunkSpec) -> list[Chunk]:
    """Chunk chỉ có tiêu đề / câu dẫn nối vào chunk ngay sau nếu liên quan và vừa trần."""
    ra: list[Chunk] = []
    i = 0
    while i < len(chunks):
        c = chunks[i]
        nx = chunks[i + 1] if i + 1 < len(chunks) else None
        if (
            nx is not None
            and len(c.text) < spec.min_chars
            and _la_dan(c.text)
            and len(c.text) + 2 + len(nx.text) <= spec.max_chars
            and _lien_quan(c.section_path, nx.section_path)
        ):
            chunks[i + 1] = Chunk(f"{c.text}\n\n{nx.text}", nx.section_path)
        else:
            ra.append(c)
        i += 1
    return ra
