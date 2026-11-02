"""Demo client E2E cho cổng nạp dữ liệu ngoài (module `ingest`).

Đóng HAI vai, đúng như một khách hàng thật:
  · **Quản trị workspace** (cookie phiên + WORKSPACE_ADMIN) — tạo/xoá token nạp,
    đọc tổng quan và bảng lỗi.
  · **Adapter bên khách** (Bearer token nạp) — đẩy events, gửi bản kê đối soát.

Kịch bản chạy TUẦN TỰ, mỗi bước in ✓/✗ và tự dọn dẹp ở cuối (xoá mềm mọi bản
ghi tạo ra, xoá token). Mọi `externalId` mang tiền tố duy nhất theo lượt chạy
nên chạy lại bao nhiêu lần cũng không giẫm lên nhau.

⚠️ BẢN KÊ ĐỐI SOÁT LUÔN KHOANH VÙNG (`afterExternalId` = tiền tố lượt chạy,
`isLastPage: false`): phép tìm «nghi mất tích» quét bảng của mình theo KHOẢNG
trang tự khai, nên một bản kê `isLastPage: true` từ script demo sẽ gắn cờ nhầm
mọi bản ghi CÓ SẴN của tenant dev nằm sau khoảng đó. Đừng "sửa" thành true.

Chạy (backend phải đang chạy, mặc định cổng 8100):

    uv run python scripts/demo_cong_nap_e2e.py
    uv run python scripts/demo_cong_nap_e2e.py --rate-limit   # kèm bài 429, ~120 request

Thoát mã 0 nếu mọi bước xanh, 1 nếu có bước đỏ.
"""

import argparse
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

MAU_XANH = "\033[32m"
MAU_DO = "\033[31m"
MAU_HET = "\033[0m"

GOC_INGEST = "/api/v1/ingest/realestate/v1"


@dataclass
class BoiCanh:
    """Trạng thái dùng chung giữa các kịch bản của MỘT lượt chạy."""

    admin: httpx.Client
    khach: httpx.Client
    tien_to: str
    t0: datetime
    token: str = ""
    token_id: int = 0
    so_nhan_24h_goc: int = -1
    project_code: str = ""
    ket_qua: list[tuple[str, bool, str]] = field(default_factory=list)

    def ghi(self, ten: str, dat: bool, chi_tiet: str = "") -> None:
        dau = f"{MAU_XANH}✓{MAU_HET}" if dat else f"{MAU_DO}✗{MAU_HET}"
        duoi = f" — {chi_tiet}" if chi_tiet and not dat else ""
        print(f"  {dau} {ten}{duoi}")
        self.ket_qua.append((ten, dat, chi_tiet))

    def ma(self, duoi: str) -> str:
        return f"{self.tien_to}-{duoi}"

    def luc(self, phut: int = 0) -> str:
        return (self.t0 + timedelta(minutes=phut)).isoformat()

    # ── hai đường HTTP của adapter bên khách ────────────────────────────────

    def day_lo(self, records: list[dict], *, dry_run: bool = False, token: str | None = None) -> httpx.Response:
        return self.khach.post(
            f"{GOC_INGEST}/events",
            params={"dryRun": "true"} if dry_run else None,
            json={"records": records, "syncId": f"{self.tien_to}-sync"},
            headers={"Authorization": f"Bearer {token if token is not None else self.token}"},
        )

    def gui_ban_ke(
        self, muc: list[dict], *, after: str | None = None, la_trang_cuoi: bool = False, dry_run: bool = False
    ) -> httpx.Response:
        # `isLastPage` mặc định FALSE ở đây (ngược mặc định của hợp đồng), và
        # `after` mặc định là tiền tố lượt chạy — xem cảnh báo ở docstring đầu tệp.
        return self.khach.post(
            f"{GOC_INGEST}/manifest",
            params={"dryRun": "true"} if dry_run else None,
            json={
                "entity": "unit",
                "records": muc,
                "afterExternalId": after if after is not None else f"{self.tien_to}-",
                "isLastPage": la_trang_cuoi,
            },
            headers={"Authorization": f"Bearer {self.token}"},
        )

    # ── đường xác minh qua API quản trị (module realestate) ────────────────

    def tim_du_an(self, ten: str) -> dict | None:
        r = self.admin.get("/api/v1/projects", params={"search": ten})
        r.raise_for_status()
        items = [x for x in r.json()["items"] if x["name"] == ten]
        return items[0] if items else None

    def liet_ke(self, nhanh: str) -> list[dict]:
        r = self.admin.get(f"/api/v1/projects/{self.project_code}/{nhanh}")
        r.raise_for_status()
        return r.json()["items"]


# ─── Kịch bản ────────────────────────────────────────────────────────────────


def kb_dang_nhap_va_tong_quan(bc: BoiCanh, email: str, mat_khau: str) -> None:
    print("\n■ 1. Đăng nhập quản trị + tổng quan cổng nạp")
    r = bc.admin.post("/api/v1/auth/login", json={"email": email, "password": mat_khau})
    bc.ghi("đăng nhập trả 200 kèm phiên", r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}")
    # Cookie phiên mang cờ `Secure` (mặc định của backend); jar của httpx sẽ KHÔNG
    # gửi lại nó qua `http://localhost`. Chép tay giá trị vào jar — trình duyệt
    # thật được miễn trừ localhost nên chỉ client script mới cần bước này.
    for ten, gia_tri in r.cookies.items():
        bc.admin.cookies.set(ten, gia_tri)
    r = bc.admin.get(f"{GOC_INGEST}/tong-quan")
    ok = r.status_code == 200
    bc.ghi("GET /tong-quan trả 200", ok, f"HTTP {r.status_code}: {r.text[:200]}")
    if ok:
        than = r.json()
        bc.so_nhan_24h_goc = than["thongKe"]["soNhan24h"]
        bc.ghi("diemNap trỏ đúng endpoint events", than["diemNap"].endswith(f"{GOC_INGEST}/events"))


def kb_vong_doi_token(bc: BoiCanh) -> None:
    print("\n■ 2. Vòng đời token nạp")
    nhan = bc.tien_to
    r = bc.admin.post(f"{GOC_INGEST}/keys", json={"label": nhan})
    ok = r.status_code == 201
    bc.ghi("tạo token trả 201", ok, f"HTTP {r.status_code}: {r.text[:200]}")
    if ok:
        than = r.json()
        bc.token, bc.token_id = than["token"], than["id"]
        bc.ghi("token mang tiền tố ody_in_", bc.token.startswith("ody_in_"), bc.token[:12])
    r = bc.admin.post(f"{GOC_INGEST}/keys", json={"label": nhan})
    bc.ghi("nhãn trùng trả 409 TEN_TRUNG", r.status_code == 409, f"HTTP {r.status_code}: {r.text[:200]}")


def kb_token_sai(bc: BoiCanh) -> None:
    print("\n■ 3. Token sai bị chặn")
    r = bc.day_lo([_project(bc, "p1")], token="ody_in_gia-mao-khong-ton-tai")
    bc.ghi("401 INVALID_INGEST_TOKEN", r.status_code == 401, f"HTTP {r.status_code}: {r.text[:200]}")


def kb_dry_run(bc: BoiCanh) -> None:
    print("\n■ 4. dryRun kiểm mà không ghi")
    hong = _unit(bc, "u-hong", "z1")
    del hong["data"]["productType"]
    r = bc.day_lo([_project(bc, "p0"), hong], dry_run=True)
    ok = r.status_code == 200
    bc.ghi("dryRun trả 200", ok, f"HTTP {r.status_code}: {r.text[:200]}")
    if ok:
        than = r.json()
        dat = than["dryRun"] and than["accepted"] == 1 and than["rejected"] == 1
        bc.ghi("dryRun=true, 1 accepted + 1 rejected", dat, str(than))
    bc.ghi("dự án dryRun KHÔNG được ghi", bc.tim_du_an(f"Demo dryRun {bc.tien_to}") is None)
    r = bc.admin.get(f"{GOC_INGEST}/loi")
    co_loi_dry = any(x["externalId"] == bc.ma("u-hong") for x in r.json()["loi"])
    bc.ghi("dryRun KHÔNG ghi vào bảng lỗi", not co_loi_dry)


def kb_lo_day_du(bc: BoiCanh) -> None:
    print("\n■ 5. Lô đầy đủ: project → zone → unit → document → media")
    lo = [
        _project(bc, "p1"),
        _zone(bc, "z1"),
        _unit(bc, "u01", "z1"),
        _unit(bc, "u02", None),  # `zoneExternalId` tuỳ chọn từ 0902 — căn không phân khu
        _unit(bc, "u04", None),
        _document(bc, "d1"),
        _media(bc, "m1"),
    ]
    r = bc.day_lo(lo)
    ok = r.status_code == 200
    bc.ghi("lô 7 bản ghi trả 200", ok, f"HTTP {r.status_code}: {r.text[:300]}")
    if not ok:
        return
    than = r.json()
    bc.ghi("cả 7 accepted", than["accepted"] == 7 and than["rejected"] == 0, str(than["results"]))

    du_an = bc.tim_du_an(f"Demo Ingest {bc.tien_to}")
    bc.ghi("project xuất hiện trong danh mục", du_an is not None)
    if du_an is None:
        return
    bc.project_code = du_an["projectCode"]
    bc.ghi("project mặc định published", du_an.get("status", "published") in ("published",), str(du_an.get("status")))
    zones = bc.liet_ke("zones")
    bc.ghi("zone z1 đã chiếu", any(z["name"] == f"Phân khu {bc.tien_to}-z1" for z in zones), str(zones)[:200])
    units = {u["unitCode"]: u for u in bc.liet_ke("units")}
    bc.ghi("3 căn đã chiếu", all(bc.ma(m) in units for m in ("u01", "u02", "u04")), str(sorted(units)))
    if bc.ma("u01") in units:
        bc.ghi("giá căn u01 đúng", units[bc.ma("u01")]["priceVnd"] == 3_500_000_000, str(units.get(bc.ma("u01"))))
    tai_lieu = bc.liet_ke("documents")
    co_d1 = any(t["loai"] == "csbh" and bc.tien_to in t["title"] for t in tai_lieu)
    bc.ghi("document d1 đã chiếu, loai=csbh", co_d1, str(tai_lieu)[:200])
    media = bc.liet_ke("media")
    bc.ghi("media m1 đã chiếu", any(m["fileName"] == f"{bc.tien_to}-m1.jpg" for m in media), str(media)[:200])


def kb_ban_ghi_hong(bc: BoiCanh) -> None:
    print("\n■ 6. Bản ghi hỏng bị từ chối TỪNG DÒNG, lô vẫn 200")
    thieu = _unit(bc, "e-thieu", "z1")
    del thieu["data"]["productType"]
    enum_sai = _unit(bc, "e-enum", "z1")
    enum_sai["data"]["saleStatus"] = "sold_out"
    khong_cha = _zone(bc, "e-cha")
    del khong_cha["data"]["projectExternalId"]
    r = bc.day_lo([thieu, enum_sai, khong_cha, _zone(bc, "z9")])
    ok = r.status_code == 200
    bc.ghi("lô lẫn lộn vẫn trả 200", ok, f"HTTP {r.status_code}: {r.text[:300]}")
    if not ok:
        return
    than = r.json()
    kq = {x["externalId"]: x for x in than["results"]}
    bc.ghi("1 accepted + 3 rejected", than["accepted"] == 1 and than["rejected"] == 3, str(than))
    thieu_kq, enum_kq, cha_kq = kq[bc.ma("e-thieu")], kq[bc.ma("e-enum")], kq[bc.ma("e-cha")]
    bc.ghi("thiếu productType → field=productType", thieu_kq["field"] == "productType", str(thieu_kq))
    bc.ghi("enum sai → reason liệt kê giá trị hợp lệ", "available" in enum_kq["reason"], str(enum_kq))
    bc.ghi("thiếu khoá cha → field=projectExternalId", cha_kq["field"] == "projectExternalId", str(cha_kq))
    loi = bc.admin.get(f"{GOC_INGEST}/loi").json()["loi"]
    ma_loi = {x["externalId"] for x in loi}
    du_3_dong = {bc.ma("e-thieu"), bc.ma("e-enum"), bc.ma("e-cha")} <= ma_loi
    bc.ghi("bảng /loi cho quản trị thấy đủ 3 dòng", du_3_dong, str(sorted(ma_loi))[:300])


def kb_stale_va_upsert(bc: BoiCanh) -> None:
    print("\n■ 7. Trọng tài thứ tự: stale bị bỏ qua, bản mới hơn thay trọn")
    cu = _unit(bc, "u01", "z1", phut=-60)
    cu["data"]["priceVnd"] = 1
    r = bc.day_lo([cu])
    than = r.json()
    bc.ghi("occurredAt cũ hơn → stale", than["stale"] == 1 and than["results"][0]["status"] == "stale", str(than))
    units = {u["unitCode"]: u for u in bc.liet_ke("units")}
    bc.ghi("giá KHÔNG đổi sau stale", units[bc.ma("u01")]["priceVnd"] == 3_500_000_000, str(units.get(bc.ma("u01"))))

    moi = _unit(bc, "u01", "z1", phut=60)
    moi["data"]["priceVnd"] = 3_600_000_000
    del moi["data"]["bedrooms"]  # upsert mới thay TRỌN bản ghi — trường vắng mặt về NULL
    r = bc.day_lo([moi])
    bc.ghi("bản mới hơn → accepted", r.json()["accepted"] == 1, r.text[:200])
    units = {u["unitCode"]: u for u in bc.liet_ke("units")}
    u01 = units.get(bc.ma("u01"), {})
    bc.ghi("giá đã cập nhật", u01.get("priceVnd") == 3_600_000_000, str(u01))
    bc.ghi("bedrooms vắng mặt → về NULL (thay trọn)", u01.get("bedrooms") is None, str(u01))


def kb_con_truoc_cha(bc: BoiCanh) -> None:
    print("\n■ 8. Con tới trước cha: chờ, rồi tự chiếu khi cha tới")
    r = bc.day_lo([_unit(bc, "u03", "z2", phut=10)])  # z2 CHƯA tồn tại
    bc.ghi("con mồ côi vẫn accepted (chờ cha)", r.json()["accepted"] == 1, r.text[:200])
    units = {u["unitCode"] for u in bc.liet_ke("units")}
    bc.ghi("u03 CHƯA xuất hiện khi cha chưa tới", bc.ma("u03") not in units, str(sorted(units)))
    r = bc.day_lo([_zone(bc, "z2", phut=10)])
    bc.ghi("đẩy zone z2 → accepted", r.json()["accepted"] == 1, r.text[:200])
    units = {u["unitCode"] for u in bc.liet_ke("units")}
    bc.ghi("u03 tự chiếu theo cascade", bc.ma("u03") in units, str(sorted(units)))


def kb_delete_mem(bc: BoiCanh) -> None:
    print("\n■ 9. op=delete là xoá MỀM")
    r = bc.day_lo([_xoa(bc, "unit", "u02", phut=20)])
    bc.ghi("delete accepted", r.json()["accepted"] == 1, r.text[:200])
    # Xoá MỀM: hàng ở lại với `status='archived'` (có thể đã lên Qdrant — spec §6),
    # và danh mục QUẢN TRỊ cố ý không lọc status nên vẫn thấy nó ở đây.
    units = {u["unitCode"]: u for u in bc.liet_ke("units")}
    u02 = units.get(bc.ma("u02"), {})
    bc.ghi("u02 chuyển status=archived (xoá mềm)", u02.get("status") == "archived", str(u02))


def kb_doi_soat(bc: BoiCanh) -> None:
    print("\n■ 10. Đối soát bản kê (khoanh vùng theo tiền tố lượt chạy)")
    # u02 đã delete — bản kê không liệt kê nó và nó KHÔNG được tính mất tích.
    du = [_muc(bc, "u01", 60), _muc(bc, "u03", 10), _muc(bc, "u04", 0)]
    r = bc.gui_ban_ke(du)
    ok = r.status_code == 200
    bc.ghi("bản kê khớp trả 200", ok, f"HTTP {r.status_code}: {r.text[:200]}")
    if ok:
        than = r.json()
        bc.ghi("khớp: 0 lệch, 0 nghi mất tích", than["soLech"] == 0 and than["soNghiMatTich"] == 0, str(than))

    lech = [_muc(bc, "u01", 120), _muc(bc, "u03", 10), _muc(bc, "u04", 0)]
    than = bc.gui_ban_ke(lech).json()
    bc.ghi("khách mới hơn → externalIdLech", than["externalIdLech"] == [bc.ma("u01")], str(than))

    thieu = [_muc(bc, "u01", 60), _muc(bc, "u04", 0)]  # bỏ sót u03, khoảng vẫn phủ nó qua u04
    than = bc.gui_ban_ke(thieu, dry_run=True).json()
    dung = than["dryRun"] is True and than["externalIdNghiMatTich"] == [bc.ma("u03")]
    bc.ghi("dryRun manifest: so thật, không gắn cờ", dung, str(than))

    than = bc.gui_ban_ke(thieu).json()
    bc.ghi("mình có mà kê thiếu → nghi mất tích", than["externalIdNghiMatTich"] == [bc.ma("u03")], str(than))

    bc.day_lo([_unit(bc, "u03", "z2", phut=30)])  # xuất hiện lại → cờ tự gỡ
    than = bc.gui_ban_ke([_muc(bc, "u01", 60), _muc(bc, "u03", 30), _muc(bc, "u04", 0)]).json()
    bc.ghi("đẩy lại → cờ tự gỡ, bản kê sạch", than["soLech"] == 0 and than["soNghiMatTich"] == 0, str(than))

    r = bc.gui_ban_ke([_muc(bc, "u01", 60), _muc(bc, "u01", 60)])
    trung_422 = r.status_code == 422 and "BAN_KE_KHONG_HOP_LE" in r.text
    bc.ghi("externalId trùng → 422 BAN_KE_KHONG_HOP_LE", trung_422, f"HTTP {r.status_code}: {r.text[:200]}")

    # Phân trang bằng KHOẢNG: trang sau nối đúng chỗ trang trước kết thúc.
    t1 = bc.gui_ban_ke([_muc(bc, "u01", 60), _muc(bc, "u03", 30)]).json()
    t2 = bc.gui_ban_ke([_muc(bc, "u04", 0)], after=bc.ma("u03")).json()
    sach = all(t["soLech"] == 0 and t["soNghiMatTich"] == 0 for t in (t1, t2))
    bc.ghi("bản kê 2 trang nối khoảng, cả hai sạch", sach, f"t1={t1} t2={t2}")


def kb_thong_ke(bc: BoiCanh) -> None:
    print("\n■ 11. Thống kê 24h trên tổng quan nhích lên")
    than = bc.admin.get(f"{GOC_INGEST}/tong-quan").json()["thongKe"]
    delta = f"{bc.so_nhan_24h_goc} → {than['soNhan24h']}"
    bc.ghi("soNhan24h tăng so với đầu lượt", than["soNhan24h"] > bc.so_nhan_24h_goc, delta)
    bc.ghi("soHong24h đếm được lỗi", than["soHong24h"] >= 3, str(than))


def kb_don_dep(bc: BoiCanh) -> None:
    print("\n■ 12. Dọn dẹp: xoá mềm bản ghi, xoá token, token chết bị chặn")
    xoa = [
        _xoa(bc, "media", "m1", phut=90),
        _xoa(bc, "document", "d1", phut=90),
        _xoa(bc, "unit", "u01", phut=90),
        _xoa(bc, "unit", "u03", phut=90),
        _xoa(bc, "unit", "u04", phut=90),
        _xoa(bc, "zone", "z1", phut=90),
        _xoa(bc, "zone", "z2", phut=90),
        _xoa(bc, "zone", "z9", phut=90),
        _xoa(bc, "project", "p1", phut=90),
    ]
    r = bc.day_lo(xoa)
    bc.ghi("xoá mềm toàn bộ dữ liệu demo", r.status_code == 200 and r.json()["accepted"] == len(xoa), r.text[:300])
    r = bc.admin.delete(f"{GOC_INGEST}/keys/{bc.token_id}")
    bc.ghi("xoá token trả 204", r.status_code == 204, f"HTTP {r.status_code}")
    r = bc.day_lo([_project(bc, "p1")])
    bc.ghi("token đã xoá → 401", r.status_code == 401, f"HTTP {r.status_code}: {r.text[:200]}")


def kb_rate_limit(bc: BoiCanh) -> None:
    """Chạy CUỐI CÙNG và dùng token RIÊNG: chạm trần là token đó bị 429 tới hết
    cửa sổ 60 giây, mọi bài sau dùng chung token sẽ đỏ oan."""
    print("\n■ 13. Giới hạn tốc độ /events (120/phút, đếm REQUEST)")
    r = bc.admin.post(f"{GOC_INGEST}/keys", json={"label": f"{bc.tien_to}-rl"})
    token, token_id = r.json()["token"], r.json()["id"]
    ma_cuoi = 0
    for i in range(1, 131):
        rr = bc.day_lo([_xoa(bc, "unit", "rl", phut=0)], dry_run=True, token=token)
        ma_cuoi = rr.status_code
        if ma_cuoi == 429:
            bc.ghi(f"429 xuất hiện ở request thứ {i}", 100 < i <= 130, rr.text[:200])
            retry = rr.headers.get("retry-after", "")
            bc.ghi("429 mang header Retry-After (giây)", retry.isdigit() and int(retry) >= 1, f"Retry-After={retry!r}")
            break
    else:
        bc.ghi("không thấy 429 sau 130 request", False, f"mã cuối {ma_cuoi}")
    bc.admin.delete(f"{GOC_INGEST}/keys/{token_id}")


# ─── Khuôn bản ghi — dữ liệu mẫu tối thiểu nhưng hợp lệ ─────────────────────


def _vo(bc: BoiCanh, entity: str, duoi: str, data: dict, phut: int = 0) -> dict:
    return {"entity": entity, "externalId": bc.ma(duoi), "op": "upsert", "occurredAt": bc.luc(phut), "data": data}


def _project(bc: BoiCanh, duoi: str) -> dict:
    ten = f"Demo Ingest {bc.tien_to}" if duoi == "p1" else f"Demo dryRun {bc.tien_to}"
    data = {"name": ten, "region": "Đà Nẵng", "salePhase": "dang_ban", "category": ["chung_cu"]}
    return _vo(bc, "project", duoi, data)


def _zone(bc: BoiCanh, duoi: str, phut: int = 0) -> dict:
    return _vo(bc, "zone", duoi, {"name": f"Phân khu {bc.tien_to}-{duoi}", "projectExternalId": bc.ma("p1")}, phut)


def _unit(bc: BoiCanh, duoi: str, zone_duoi: str | None, phut: int = 0) -> dict:
    data = {
        "unitCode": bc.ma(duoi),
        "saleStatus": "available",
        "productType": "chung_cu",
        "priceVnd": 3_500_000_000,
        "bedrooms": 2,
        "projectExternalId": bc.ma("p1"),
    }
    if zone_duoi is not None:
        data["zoneExternalId"] = bc.ma(zone_duoi)
    return _vo(bc, "unit", duoi, data, phut)


def _document(bc: BoiCanh, duoi: str) -> dict:
    data = {"title": f"Chính sách {bc.tien_to}", "loai": "csbh", "body": "Chiết khấu 5% demo."}
    data["projectExternalId"] = bc.ma("p1")
    return _vo(bc, "document", duoi, data)


def _media(bc: BoiCanh, duoi: str) -> dict:
    data = {
        "mediaUrl": f"https://example.com/{bc.tien_to}-{duoi}.jpg",
        "contentType": "image",
        "category": "tong_quan",
        "fileName": f"{bc.tien_to}-{duoi}.jpg",
        "projectExternalId": bc.ma("p1"),
    }
    return _vo(bc, "media", duoi, data)


def _xoa(bc: BoiCanh, entity: str, duoi: str, phut: int) -> dict:
    return {"entity": entity, "externalId": bc.ma(duoi), "op": "delete", "occurredAt": bc.luc(phut), "data": {}}


def _muc(bc: BoiCanh, duoi: str, phut: int) -> dict:
    return {"externalId": bc.ma(duoi), "updatedAt": bc.luc(phut)}


# ─── main ────────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--base-url", default="http://localhost:8100")
    p.add_argument("--email", default="dang@anphuland.vn")
    p.add_argument("--password", default="odyssey-dev")
    p.add_argument("--rate-limit", action="store_true", help="kèm bài 429 (~120 request, chiếm 1 phút cửa sổ)")
    args = p.parse_args()

    t0 = datetime.now(UTC).replace(microsecond=0)
    bc = BoiCanh(
        admin=httpx.Client(base_url=args.base_url, timeout=30),
        khach=httpx.Client(base_url=args.base_url, timeout=30),
        tien_to=f"demo-e2e-{t0.strftime('%y%m%d%H%M%S')}",
        t0=t0,
    )
    print(f"Demo E2E cổng nạp — {args.base_url} — tiền tố {bc.tien_to}")

    kb_dang_nhap_va_tong_quan(bc, args.email, args.password)
    if not all(dat for _, dat, _ in bc.ket_qua):
        print("\nĐăng nhập/tổng quan hỏng — dừng sớm, các bài sau đều cần nó.")
        return 1
    kb_vong_doi_token(bc)
    if not bc.token:
        print("\nKhông có token — dừng sớm.")
        return 1

    # Một kịch bản sập (500 bất ngờ, hình dạng response lệch…) là MỘT bước đỏ,
    # không phải lý do bỏ dở các kịch bản còn lại — nhất là bước dọn dẹp.
    cac_bai = [kb_token_sai, kb_dry_run, kb_lo_day_du]
    cac_bai += [kb_ban_ghi_hong, kb_stale_va_upsert, kb_con_truoc_cha, kb_delete_mem, kb_doi_soat, kb_thong_ke]
    cac_bai += [kb_don_dep] + ([kb_rate_limit] if args.rate_limit else [])
    for bai in cac_bai:
        try:
            bai(bc)
        except Exception as e:  # noqa: BLE001 — client demo phải chạy hết để còn dọn dẹp
            bc.ghi(f"{bai.__name__} sập giữa chừng", False, f"{type(e).__name__}: {e}")

    tong = len(bc.ket_qua)
    dat = sum(1 for _, d, _ in bc.ket_qua if d)
    print(f"\n{'─' * 60}\nKết quả: {dat}/{tong} bước xanh")
    for ten, d, chi_tiet in bc.ket_qua:
        if not d:
            print(f"  {MAU_DO}✗ {ten}{MAU_HET} — {chi_tiet}")
    return 0 if dat == tong else 1


if __name__ == "__main__":
    sys.exit(main())
