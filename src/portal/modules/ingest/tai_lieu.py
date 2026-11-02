"""Tài liệu OpenAPI cho DEV BÊN KHÁCH — SINH từ `HOP_DONG`, không chép tay.

Vì sao tồn tại: `BanGhiIn.data` là `dict` trần nên OpenAPI chỉ hiện `object` —
tên trường, trường bắt buộc, giá trị enum đều vô hình với người cầm Swagger,
trong khi `docsUrl` của màn quản trị trỏ thẳng khách vào đúng trang đó. Trước
bản này, cách duy nhất để một dev bên khách biết `productType` nhận giá trị gì
là gửi sai rồi đọc lỗi — mỗi trường một vòng thử-sai.

Vì sao SINH chứ không viết tay: `HOP_DONG`/`QUAN_HE` đã có cổng parity với DB
thật (`test_hop_dong_khop_schema.py`), nên văn bản dựng từ chúng thừa hưởng
luôn bảo đảm đó. Một bản chép tay là một `lib/tools.ts` thứ hai — lệch không
cổng nào đỏ. `test_tai_lieu.py` canh phép sinh đủ và văn bản có THẬT SỰ gắn
vào route.

BỐ CỤC VIẾT CHO SWAGGER UI, không phải cho một trang markdown tuỳ ý — viết lại
2026-08-21 sau phản hồi «mọi thứ rối loạn với nhau». Bốn luật rút được từ bản
render thật, đừng phá:

  · MỖI BULLET MỘT Ý, và các ý CÙNG HỌ nhóm dưới một tiêu đề `####` — bản đầu
    dồn 8 bullet đủ mọi chủ đề vào một danh sách «đáng tiền nhất», render ra
    một bức tường chữ đặc.
  · Ô BẢNG KHÔNG CHỨA ĐOẠN VĂN. Swagger UI kẻ bảng rất mảnh, một ô dài là cả
    hàng vỡ — ghi chú dài của một trường tách xuống danh sách «Ghi chú» ngay
    dưới bảng, ô chỉ giữ chip enum hoặc vài chữ.
  · KHÔNG Ô TRỐNG: cột «Bắt buộc» điền `—` cho trường tuỳ chọn. Ô trống trong
    bảng gần-không-kẻ đọc thành lỗi layout, không đọc thành «không».
  · KHOÁ CHA NẰM TRONG BẢNG của thực thể (hàng đầu, ghi chú «khoá cha») thay
    vì một dòng văn xuôi lửng lơ phía trên — người viết adapter cần MỘT chỗ
    liệt kê đủ mọi khoá được phép xuất hiện trong `data`.

HAI LUẬT VĂN PHONG (người dùng chốt 2026-08-21):
  · «Odyssey» là tên dự án NỘI BỘ — văn bản khách đọc dùng tên chính thức
    **NobleX Agent Platform** (nhắc lại trong câu thì «nền tảng» cho gọn).
  · Thuật ngữ kỹ thuật KHÔNG dịch: kiểu dữ liệu là `string`/`number`/`integer`/
    `enum`, bắt buộc là `true` — «chuỗi»/«số»/«có» bắt dev bên khách dịch ngược
    lại sang thứ họ sẽ gõ.

HÀM THUẦN, chạy MỘT lần lúc import `router.py` — không có I/O, không settings.
"""

from portal.modules.ingest import contracts
from portal.modules.ingest.doi_soat import TRAN_BAN_KE
from portal.modules.ingest.hop_dong import HOP_DONG, QUAN_HE, Truong

_TEN_KIEU = {
    "chuoi": "string",
    "so": "number",
    "nguyen": "integer",
    "enum": "enum",
    "enum_nhieu": "enum[]",
    "ban_giao": "string | object[]",
}

_NHAN_ENTITY = {
    "project": "Dự án",
    "zone": "Phân khu",
    "unit": "Căn / sản phẩm",
    "document": "Tài liệu",
    "media": "Ảnh & video",
}

# Ghi chú DÀI của một trường — tách khỏi ô bảng (xem luật bố cục ở docstring).
# Khoá theo tên trường: các tên này chỉ xuất hiện ở đúng một thực thể.
#
# Sáu ghi chú media/document thêm 2026-08-25 sau khi review hai adapter thật (AINA,
# NBX Sales): mỗi ghi chú là một hành vi adapter đã phải tự mò ra bằng thử-sai —
# tour_360 bị sync `link360` xoá mất, PDF chỉ được đọc 43 ký tự metadata, caption
# tiến độ sai khuôn nên timeline gộp một mốc, video mp4 không phát được…
_GHI_CHU_TRUONG = {
    "code": "mã người-đọc-được (vd slug của bạn), chỉ dùng lúc **tạo** — không gửi thì suy từ "
    "`externalId`; update bỏ qua trường này.",
    "loai": "không phải cột riêng — được nhập vào `title` thành tiền tố.",
    "body": "nội dung tài liệu, viết markdown được. Có `fileUrl` thì `body` chỉ cần tóm tắt/siêu dữ liệu "
    "(phạm vi, hiệu lực…) — phần chữ trong tệp nền tảng tự bóc và nối sau `body`.",
    "fileUrl": "URL **công khai** của tệp (PDF · DOCX · XLSX · ảnh). Nền tảng tải về và **bóc chữ** cho agent; "
    "PDF scan / ảnh đọc bằng OCR phải được quản trị workspace **duyệt** trong portal trước khi agent thấy.",
    "mediaUrl": "`image`: URL ảnh tải trực tiếp được. `video`: URL **trang** video (YouTube, Google Drive…), "
    "không phải tệp mp4 — YouTube và Google Drive nhúng được trong app, host khác chỉ mở link.",
    "contentType": "`tour_360` là loại nền tảng **tự sinh** từ `project.link360` (một hàng mỗi dự án, "
    "tự cập nhật/xoá theo link) — gửi tour 360 qua `link360`, **đừng** gửi media `tour_360` trực tiếp.",
    "caption": "chú thích agent đọc và app hiển thị. Với `category: tien_do` dùng khuôn "
    "**`Tiến độ dd/mm/yyyy — <tên mốc>`** (thêm ` — <chú thích riêng>` nếu có): timeline tiến độ trên "
    "nền tảng nhóm ảnh theo đúng tiền tố này; caption khác khuôn rơi về ngày nhận.",
    "fileName": "tên hiển thị của media trên nền tảng (đứng trước `caption`); video theo link thì bỏ trống.",
    "handoverStandard": "danh sách hạng mục `{item, material, brand, origin, note}` (chỉ `item` bắt buộc), "
    'ví dụ `[{"item": "Thiết bị vệ sinh", "brand": "TOTO"}]`. Gửi chuỗi vẫn được: '
    "nền tảng lưu thành một hạng mục «Tiêu chuẩn chung».",
}

_DAU_TRANG_EVENTS = """\
Nhận một **lô** bản ghi từ hệ thống của bạn — tối đa {tran_lo} bản ghi mỗi lô.

Response `200` luôn kèm kết quả của **từng bản ghi** (`accepted` · `rejected` · `stale`):
một bản ghi hỏng không làm rớt phần còn lại của lô, mã HTTP chỉ nói về request.

#### Thứ tự và ghi đè

- `occurredAt` quyết định bản nào mới hơn. Bắt buộc có múi giờ — `2026-08-16T09:00:00+07:00` hoặc `…Z`.
- Sự kiện cũ hơn bản đang có → `stale`: bị bỏ qua, không phải lỗi — gửi lại (retry) vô hại.
- Bản mới hơn **thay trọn bản ghi**: trường không gửi trở về giá trị mặc định, không giữ giá trị cũ.
- `op: delete` chỉ cần `externalId` — bản ghi được **ẩn** (`status` → `archived`, agent không thấy),
  không xoá vật lý; `upsert` lại là sống lại.
- Gửi con trước cha vẫn hợp lệ — bản ghi được nhận và tự hiện ra khi cha tới, không cần sắp thứ tự.

#### Payload

- Vỏ bản ghi là bốn trường định danh `entity` · `externalId` · `op` · `occurredAt` —
  sai một trường là `422` cho cả request.
- Trong `data`, trường lạ được bỏ qua im lặng. Bảng trường của từng thực thể ở ngay dưới.
- Mọi khoá cha (`projectExternalId`…) dùng **mã của chính bạn**, không phải mã do nền tảng sinh.
- Không gửi `status` thì mặc định `published`. Muốn nạp mà chưa cho agent thấy: gửi `"draft"`.

#### Khi viết adapter

- Thêm `?dryRun=true`: kiểm cả lô (cảnh báo cả «đang trỏ vào cha chưa tồn tại») và không
  ghi gì — dùng suốt giai đoạn phát triển.
- `429` kèm header `Retry-After` (giây) là vượt nhịp: chờ rồi gửi lại. `401` mới là token
  sai — đừng phát lại token khi gặp `429`.

## Trường `data` theo thực thể
"""


def _hang(ten: str, kieu: str, bat_buoc: bool, gia_tri: str) -> str:
    return f"| `{ten}` | {kieu} | {'**true**' if bat_buoc else '—'} | {gia_tri} |"


def _hang_truong(t: Truong) -> str:
    gia_tri = " · ".join(f"`{v}`" for v in t.gia_tri)
    if t.ten in _GHI_CHU_TRUONG:
        gia_tri = (gia_tri + " " if gia_tri else "") + "xem ghi chú dưới bảng"
    return _hang(t.ten, _TEN_KIEU[t.kieu], t.bat_buoc, gia_tri)


def _muc_thuc_the(entity: str) -> str:
    dong = [
        f"### `{entity}` — {_NHAN_ENTITY[entity]}",
        "",
        "| Trường | Kiểu | Bắt buộc | Giá trị nhận |",
        "|---|---|---|---|",
    ]
    # Khoá cha đứng ĐẦU bảng: nó là thứ nối bản ghi vào cây dữ liệu, người viết
    # adapter cần thấy trước cả trường nội dung.
    dong += [
        _hang(ten, "string", bat_buoc, f"khoá cha — `externalId` của `{cha}` bên bạn")
        for ten, cha, bat_buoc in QUAN_HE[entity]
    ]
    dong += [_hang_truong(t) for t in HOP_DONG[entity]]

    ghi_chu = [f"- `{t.ten}` — {_GHI_CHU_TRUONG[t.ten]}" for t in HOP_DONG[entity] if t.ten in _GHI_CHU_TRUONG]
    if ghi_chu:
        dong += ["", "Ghi chú:", ""] + ghi_chu
    return "\n".join(dong)


def mo_ta_events() -> str:
    """Markdown cho `description` của `POST …/events` — thứ Swagger UI hiển thị."""
    dau = _DAU_TRANG_EVENTS.format(tran_lo=contracts.TRAN_LO)
    return dau + "\n" + "\n\n".join(_muc_thuc_the(e) for e in HOP_DONG)


_VI_DU_DATA: dict[str, dict] = {
    "project": {"name": "Khu đô thị Ánh Dương", "region": "Đà Nẵng", "salePhase": "dang_ban"},
    "zone": {"name": "Phân khu The Sun", "projectExternalId": "crm-pr-001"},
    "unit": {
        "unitCode": "S1-1203",
        "saleStatus": "available",
        "productType": "chung_cu",
        "priceVnd": 3500000000,
        "projectExternalId": "crm-pr-001",
        "zoneExternalId": "crm-zn-001",
    },
    "document": {"title": "Chính sách bán hàng T8", "loai": "csbh", "body": "…", "projectExternalId": "crm-pr-001"},
    "media": {
        "mediaUrl": "https://cdn.cua-ban.vn/anh/tien-do-05-2026.jpg",
        "contentType": "image",
        "category": "tien_do",
        "caption": "Tiến độ 01/05/2026 — Cất nóc toà A",
        "fileName": "tien-do-05-2026.jpg",
        "projectExternalId": "crm-pr-001",
    },
}


def vi_du_events() -> dict:
    """`openapi_extra` cho `POST …/events` — một ví dụ MỖI thực thể trong Swagger.

    FastAPI deep-merge dict này vào operation đã sinh, nên `examples` nằm CẠNH
    `schema`, không thay thế nó. `test_tai_lieu.py` bắt từng ví dụ phải qua được
    chính `hop_dong.kiem()` — ví dụ hỏng là dạy khách bắt đầu từ một payload hỏng.
    """
    vi_du = {
        entity: {
            "summary": f"Một {entity}",
            "value": {
                "records": [
                    {
                        "entity": entity,
                        "externalId": f"crm-{entity}-001",
                        "op": "upsert",
                        "occurredAt": "2026-08-16T09:00:00+07:00",
                        "data": data,
                    }
                ],
                "syncId": "sync-2026-08-16-001",
            },
        }
        for entity, data in _VI_DU_DATA.items()
    }
    return {"requestBody": {"content": {"application/json": {"examples": vi_du}}}}


def mo_ta_manifest() -> str:
    """Markdown cho `description` của `POST …/manifest` — ba cạnh sắc nhất nằm đây."""
    tran = f"{TRAN_BAN_KE:,}".replace(",", ".")
    return f"""\
Bản kê đối soát của **một** thực thể — ảnh chụp `{{externalId, updatedAt}}` của toàn bộ
bản ghi đang tồn tại bên bạn. Chạy định kỳ, khuyến nghị hằng đêm.

Response là hai danh sách, mỗi danh sách một việc:

- `externalIdLech` — bên bạn mới hơn: **đẩy lại những mã này qua `/events`**. Không có
  webhook gọi ngược; response này chính là yêu cầu đẩy lại.
- `externalIdNghiMatTich` — nền tảng có mà bản kê không có: chỉ **gắn cờ** để người vận hành
  đối chiếu, không tự xoá gì.

#### Ba chỗ dễ sai — sai là gắn cờ nhầm hàng loạt

1. **Sắp theo thứ tự byte** (`sorted()` của Python, `ORDER BY … COLLATE "C"`). Sắp có
   ngôn ngữ hoặc không phân biệt hoa thường làm ranh giới trang lệch, bản ghi bị gắn cờ sai.
2. `afterExternalId` = mã lớn nhất **đã gửi** ở trang trước — không phải «đã quét». `null` = trang đầu.
3. `isLastPage` mặc định `true` (bản kê một trang không phải khai gì thêm). Khi phân trang,
   trang giữa **phải đặt `false`** — quên là trang đó tự nhận phủ tới +∞ và mọi bản ghi sau nó
   bị nghi mất tích.

#### Phân trang

- Trần **{tran} mục mỗi trang** — quá thì chia trang. Đừng gửi một nửa rồi dừng: đoạn không
  trang nào phủ sẽ không bao giờ được kiểm.
- `externalId` trùng nhau trong một trang → `422`.

#### Khi viết adapter

- `?dryRun=true` — kiểm và so như thật, trả đúng hai danh sách, nhưng không cờ nào được
  gắn/gỡ và không cảnh báo vận hành nào phát ra. Dùng nó cho tới khi adapter chạy đúng.
- Nhịp riêng, thưa hơn `/events` (mặc định 30 request/giờ) — vượt trả `429` kèm header `Retry-After`.
"""
