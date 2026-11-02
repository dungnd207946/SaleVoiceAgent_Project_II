import hashlib

from portal.modules.playbook import nut


def test_bam_nut_khop_hash_agent():
    for j in nut.doc()["nodes"]:
        assert nut.bam_nut(nut.chuan_hoa(j)) == j["hash"], j["id"]


def test_bam_nut_dang_chuan():
    # Cùng chuỗi chuẩn với agent tests/unit/playbook/test_loader.py::test_node_hash_dang_chuan.
    d = {
        "id": "ab",
        "ten": "T",
        "nhom": "chot",
        "bat": True,
        "kenh": [],
        "dau_hieu": ["d"],
        "lam": ["l"],
        "tool": [],
        "cam": [],
        "khi_thieu": "",
        "cau_ket": "",
        "lan_2": "",
        "chi_lan_2": False,
        "nguon": "bỏ qua",
        "buoc": [],
    }
    raw = (
        '{"bat":true,"buoc":[],"cam":[],"cau_ket":"","chi_lan_2":false,"dau_hieu":["d"],"id":"ab","kenh":[],'
        '"khi_thieu":"","lam":["l"],"lan_2":"","nhom":"chot","ten":"T","tool":[]}'
    )
    assert nut.bam_nut(d) == hashlib.sha256(raw.encode()).hexdigest()[:12]


def test_tuong_thich_khop_json_agent():
    for j in nut.template_sale():
        assert nut.tuong_thich(nut.chuan_hoa(j)) == j, j["id"]


def test_tach_lop_va_gioi_han():
    assert {n["lop"] for n in nut.template_sale()} == {"sale"}
    assert any(n["id"] == "khac" for n in nut.he_thong())
    assert nut.gioi_han()["maxNut"] >= len(nut.template_sale())


def test_tuong_thich_bo_tool_agent_da_go():
    # Agent bỏ tool đã gỡ khỏi nút trước khi băm (loader._bo_tool_la) — BE phải băm y hệt, không thì số đo nút về 0.
    j = next(n for n in nut.template_sale() if n["tool"])
    d = {**nut.chuan_hoa(j), "tool": [*j["tool"], "tinh_tra_gop"]}
    out = nut.tuong_thich(d)
    assert out["tool"] == j["tool"] and out["hash"] == j["hash"]
