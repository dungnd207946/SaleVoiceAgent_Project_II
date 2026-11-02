import pytest
from pydantic import ValidationError

from portal.modules.playbook import kiem, nut
from portal.modules.playbook.contracts import NutVao

RIENG = {
    "id": "rieng_mau_son",
    "ten": "Chê màu sơn",
    "nhom": "phan_doi",
    "dau_hieu": ["khách chê màu sơn"],
    "lam": ["gửi ảnh mẫu màu thật"],
}


def _mau():
    return [NutVao.model_validate(nut.chuan_hoa(j)).model_dump() for j in nut.template_sale()]


def _r(**over):
    return NutVao.model_validate({**RIENG, **over}).model_dump()


def test_template_qua_kiem():
    assert kiem.kiem_bo(_mau()) == []


def test_ban_chep_template_giu_hash():
    # Áp dụng không sửa → hash bản chép = hash template → số đo các nút giữ nguyên.
    assert [nut.bam_nut(d) for d in _mau()] == [j["hash"] for j in nut.template_sale()]


def test_them_nut_rieng_va_xoa_nut_thuong():
    mau = _mau()
    dich = {d["lan_2"] for d in mau + nut.he_thong() if d["lan_2"]}
    xoa = next(
        d["id"] for d in mau if d["id"] not in nut.gioi_han()["khoaXoa"] and d["id"] not in dich and not d["lan_2"]
    )
    assert kiem.kiem_bo([d for d in mau if d["id"] != xoa] + [_r()]) == []


CA = [
    ("id sai khuôn", lambda b: b + [_r(id="Rieng_X")], "id", "khớp"),
    ("id tự thêm thiếu tiền tố", lambda b: b + [_r(id="mau_son")], "id", "rieng_"),
    ("trùng id hệ thống", lambda b: b + [_r(id="khac")], "id", "hệ thống"),
    ("trùng id trong bộ", lambda b: b + [_r(), _r()], "id", "trùng"),
    ("tên quá dài", lambda b: b + [_r(ten="t" * 61)], "ten", "60"),
    ("nhóm khac", lambda b: b + [_r(nhom="khac")], "nhom", "chỉ nhận"),
    ("kênh lạ", lambda b: b + [_r(kenh=["zalo"])], "kenh", "chỉ nhận"),
    ("tool lạ", lambda b: b + [_r(tool=["tinh_tra_gop"])], "tool", "không tồn tại"),
    ("quá 4 tool", lambda b: b + [_r(tool=sorted(nut.gioi_han()["tool"])[:5])], "tool", "tối đa 4"),
    ("tool trùng", lambda b: b + [_r(tool=["kb_search", "kb_search"])], "tool", "trùng"),
    ("dòng chỉ có ký tự điều khiển", lambda b: b + [_r(lam=["\x1f"])], "lam", "dòng rỗng"),
    ("dấu hiệu rỗng", lambda b: b + [_r(dau_hieu=[])], "dau_hieu", "rỗng"),
    ("dòng rỗng", lambda b: b + [_r(lam=["x", " "])], "lam", "dòng rỗng"),
    ("quá 6 dòng", lambda b: b + [_r(lam=["x"] * 7)], "lam", "tối đa 6 dòng"),
    ("dòng quá 200", lambda b: b + [_r(lam=["x" * 201])], "lam", "200"),
    ("dấu hiệu tổng quá 360", lambda b: b + [_r(dau_hieu=["x" * 190, "y" * 190])], "dau_hieu", "360"),
    ("cấm tổng quá 320", lambda b: b + [_r(cam=["x" * 170, "y" * 170])], "cam", "320"),
    ("câu kết quá 160", lambda b: b + [_r(cau_ket="x" * 161)], "cau_ket", "160"),
    ("nguồn quá 200", lambda b: b + [_r(nguon="x" * 201)], "nguon", "200"),
    ("quá 6 bước", lambda b: b + [_r(buoc=[{"id": f"b{i}", "lam": "x"} for i in range(7)])], "buoc", "6"),
    ("lan_2 tự trỏ", lambda b: b + [_r(lan_2="rieng_mau_son")], "lan_2", "chính nó"),
    ("lan_2 treo", lambda b: b + [_r(lan_2="khong_co")], "lan_2", "không có"),
    ("chi_lan_2 mồ côi", lambda b: b + [_r(chi_lan_2=True)], "chi_lan_2", "lan_2"),
]


@pytest.mark.parametrize("mo_ta, doi, truong, tu", CA, ids=[c[0] for c in CA])
def test_moi_luat_mot_ca(mo_ta, doi, truong, tu):
    loi = kiem.kiem_bo(doi(_mau()))
    assert any(loc and loc[-1] == truong and tu in msg for loc, msg in loi), loi


def test_id_buoc_sai_khuon():
    bo = _mau() + [_r(buoc=[{"id": "B 1", "lam": "x"}])]
    assert ((len(bo) - 1, "buoc", 0, "id"), f"id bước phải khớp {nut.gioi_han()['khuonId']}") in kiem.kiem_bo(bo)


def test_xoa_nut_khoa():
    bo = [d for d in _mau() if d["id"] != "doi_gia_rieng"]
    assert any(loc == () and "doi_gia_rieng" in msg for loc, msg in kiem.kiem_bo(bo))


def test_qua_40_nut():
    mau = _mau()
    bo = mau + [_r(id=f"rieng_n{i}") for i in range(41 - len(mau))]
    assert any(loc == () and "40" in msg for loc, msg in kiem.kiem_bo(bo))


def test_nutvao_strip_va_mac_dinh():
    d = NutVao.model_validate(
        {"id": " rieng_a ", "ten": " T ", "nhom": "chot", "dau_hieu": [" d "], "lam": ["l"]}
    ).model_dump()
    assert (d["id"], d["ten"], d["dau_hieu"], d["bat"], d["buoc"], d["nguon"]) == ("rieng_a", "T", ["d"], True, [], "")


def test_nutvao_tu_choi_truong_la():
    with pytest.raises(ValidationError):
        NutVao.model_validate({**RIENG, "hien": "x"})


def test_nutvao_strip_giong_python():
    # Agent dùng str.strip() (bỏ cả \x1c–\x1f); strip của pydantic thì không → lệch hash / agent từ chối cả bộ.
    d = NutVao.model_validate({**RIENG, "ten": "\x1cT\x1f", "lam": [" l\x1d"]}).model_dump()
    assert (d["ten"], d["lam"]) == ("T", ["l"])
