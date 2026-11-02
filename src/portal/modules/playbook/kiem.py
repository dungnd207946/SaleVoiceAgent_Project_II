"""Kiểm lớp sale workspace gửi lên — luật lấy từ `gioiHan` agent xuất trong playbook.json (spec 2026-10-06 đợt 2 §3).

Agent kiểm lại lúc nạp (`loader.from_db`); BE phải chặt ít nhất bằng agent, nếu không agent từ chối cả bộ đã lưu và
workspace lặng lẽ chạy template. Trả danh sách `(loc dưới body.nut, lý do)` — router đổi thành 422 `fields`."""

from __future__ import annotations

import re

from portal.modules.playbook import nut

Loi = tuple[tuple, str]


def _mot_nut(i: int, d: dict, g: dict, id_mau: set[str], id_he_thong: set[str]) -> list[Loi]:
    loi: list[Loi] = []

    def sai(truong: str, ly_do: str) -> None:
        loi.append(((i, truong), ly_do))

    if not re.match(g["khuonId"], d["id"]):
        sai("id", f"id phải khớp {g['khuonId']}")
    elif d["id"] not in id_mau and not re.match(g["khuonIdRieng"], d["id"]):
        sai("id", f"nút tự thêm phải có id dạng {g['khuonIdRieng']}")
    if d["id"] in id_he_thong:
        sai("id", "trùng id nút hệ thống")
    if not d["ten"]:
        sai("ten", "không được rỗng")
    elif len(d["ten"]) > g["maxTen"]:
        sai("ten", f"tối đa {g['maxTen']} ký tự")
    if d["nhom"] not in g["nhom"]:
        sai("nhom", f"chỉ nhận {', '.join(g['nhom'])}")
    if set(d["kenh"]) - set(g["kenh"]):
        sai("kenh", f"chỉ nhận {', '.join(g['kenh'])}")
    la = sorted(set(d["tool"]) - set(g["tool"]))
    if la:
        sai("tool", f"tool không tồn tại: {', '.join(la)}")
    if len(set(d["tool"])) != len(d["tool"]):
        sai("tool", "có tool trùng")
    if len(d["tool"]) > g["maxTool"]:
        sai("tool", f"tối đa {g['maxTool']} tool")
    for k in ("dau_hieu", "lam", "cam"):
        ds = d[k]
        if k != "cam" and not ds:
            sai(k, "không được rỗng")
        if any(not x for x in ds):
            sai(k, "có dòng rỗng")
        if len(ds) > g["maxDong"][k]:
            sai(k, f"tối đa {g['maxDong'][k]} dòng")
        if k != "cam" and any(len(x) > g["maxKyTu"] for x in ds):
            sai(k, f"mỗi dòng tối đa {g['maxKyTu']} ký tự")
    if len(" | ".join(d["dau_hieu"])) > g["maxDauHieuTong"]:
        sai("dau_hieu", f"tổng tối đa {g['maxDauHieuTong']} ký tự")
    if sum(len(x) for x in d["cam"]) > g["maxCamTong"]:
        sai("cam", f"tổng tối đa {g['maxCamTong']} ký tự")
    for k in ("khi_thieu", "cau_ket"):
        if len(d[k]) > g["maxCau"]:
            sai(k, f"tối đa {g['maxCau']} ký tự")
    if len(d["nguon"]) > g["maxKyTu"]:
        sai("nguon", f"tối đa {g['maxKyTu']} ký tự")
    if len(d["buoc"]) > g["maxBuoc"]:
        sai("buoc", f"tối đa {g['maxBuoc']} bước")
    for j, b in enumerate(d["buoc"]):
        if not re.match(g["khuonId"], b["id"]):
            loi.append(((i, "buoc", j, "id"), f"id bước phải khớp {g['khuonId']}"))
        if not b["lam"]:
            loi.append(((i, "buoc", j, "lam"), "không được rỗng"))
        elif len(b["lam"]) > g["maxKyTu"]:
            loi.append(((i, "buoc", j, "lam"), f"tối đa {g['maxKyTu']} ký tự"))
    return loi


def kiem_bo(bo: list[dict]) -> list[Loi]:
    g = nut.gioi_han()
    he_thong = nut.he_thong()
    id_he_thong = {n["id"] for n in he_thong}
    id_mau = {n["id"] for n in nut.template_sale()}
    loi: list[Loi] = []
    if len(bo) > g["maxNut"]:
        loi.append(((), f"tối đa {g['maxNut']} nút"))
    thay: set[str] = set()
    for i, d in enumerate(bo):
        loi += _mot_nut(i, d, g, id_mau, id_he_thong)
        if d["id"] in thay:
            loi.append(((i, "id"), "trùng id trong bộ"))
        thay.add(d["id"])
    tat_ca = thay | id_he_thong
    for i, d in enumerate(bo):
        if d["lan_2"] == d["id"]:
            loi.append(((i, "lan_2"), "không được trỏ chính nó"))
        elif d["lan_2"] and d["lan_2"] not in tat_ca:
            loi.append(((i, "lan_2"), f"nút {d['lan_2']} không có"))
    dich = {d["lan_2"] for d in bo if d["lan_2"]} | {n["lan_2"] for n in he_thong if n["lan_2"]}
    for i, d in enumerate(bo):
        if d["chi_lan_2"] and d["id"] not in dich:
            loi.append(((i, "chi_lan_2"), "không nút nào trỏ lan_2 tới nút này"))
    thieu = sorted(set(g["khoaXoa"]) - thay)
    if thieu:
        loi.append(((), f"không được xoá nút {', '.join(thieu)}"))
    return loi
