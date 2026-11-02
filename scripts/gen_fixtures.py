"""Sinh fixture PDF/DOCX/XLSX cho test M6. Chạy MỘT LẦN, kết quả commit vào git.

Vì sao commit file thay vì sinh lúc chạy test: fixture sinh lúc chạy là fixture
do CHÍNH thư viện ta đang test tạo ra, nên nó chỉ chứng minh "đọc được thứ mình
vừa ghi". Một file commit sẵn thì đứng yên, và nếu ai đó nâng pypdf mà cách bóc
chữ đổi thì test đỏ — đó là điều ta muốn.

⚠️ `fpdf2` là dev-dependency CHỈ cho script này. Portal chỉ ĐỌC pdf.

Chạy: uv run python -m scripts.gen_fixtures
"""

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

NOI_DUNG = [
    "Chính sách bán hàng An Phú Land",
    "Đặt cọc 100 triệu đồng, thanh toán theo 5 đợt.",
    "Chiết khấu 3% cho khách thanh toán sớm 95%.",
]

NOI_DUNG_ASCII = [
    "Chinh sach ban hang An Phu Land",
    "Dat coc 100 trieu dong, thanh toan theo 5 dot.",
    "Chiet khau 3 phan tram cho khach thanh toan som.",
]


def pdf() -> None:
    from fpdf import FPDF

    d = FPDF()
    d.add_page()
    d.set_font("helvetica", size=12)
    # Nội dung ASCII SOẠN RIÊNG, không phải bản cắt dấu của NOI_DUNG: font mặc
    # định của fpdf2 là Latin-1, và `encode("ascii","ignore")` XOÁ HẲN ký tự có
    # dấu ("đặt" -> "t") chứ không chuyển thành không dấu. Mục đích fixture này
    # là kiểm ĐƯỜNG BÓC CHỮ của pypdf; fixture tiếng Việt có dấu ở docx/xlsx.
    for dong in NOI_DUNG_ASCII:
        d.cell(0, 10, dong, new_x="LMARGIN", new_y="NEXT")
    d.output(str(FIXTURES / "chinh-sach.pdf"))


def pdf_khong_lop_chu() -> None:
    """PDF chỉ có hình, không có lớp chữ — ảnh scan. Phải rơi vào ER_03."""
    from fpdf import FPDF

    d = FPDF()
    d.add_page()
    d.rect(20, 20, 80, 40, style="F")
    d.output(str(FIXTURES / "anh-scan.pdf"))


def docx() -> None:
    from docx import Document

    d = Document()
    # Dòng đầu là heading (style "Heading 1") để test được nhánh chuyển style → `#`
    # của extract.py — nếu chỉ toàn Normal thì không phân biệt được "đã đọc style"
    # với "chỉ nối chuỗi thô".
    d.add_heading(NOI_DUNG[0], level=1)
    for dong in NOI_DUNG[1:]:
        d.add_paragraph(dong)
    d.save(str(FIXTURES / "chinh-sach.docx"))


def xlsx() -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Hạng mục", "Giá trị"])
    ws.append(["Đặt cọc", "100 triệu"])
    ws.append(["Chiết khấu", "3%"])
    wb.save(str(FIXTURES / "bang-gia.xlsx"))


if __name__ == "__main__":
    FIXTURES.mkdir(parents=True, exist_ok=True)
    pdf()
    pdf_khong_lop_chu()
    docx()
    xlsx()
    print(f"đã sinh fixture vào {FIXTURES}")
