from portal.modules.kb import prompts
from portal.modules.kb.conflicts.llm import PROFILE, Item, build_user_text, parse_findings

D1 = Item(ref="D1", label="CSBH tháng 7", text="hiệu lực đến 30/11/2026")
C1 = Item(ref="C1", label="CSBH số 617", text="áp dụng đến 31/12/2026")
REFS = {"D1", "D2", "C1", "C2", "field:projects.1.investor"}


def test_profile_ton_tai():
    assert prompts.get(PROFILE).model


def test_khoi_truong_dung_truoc_doan():
    text = build_user_text("[field:projects.1.investor] Chủ đầu tư: Noble", [D1], [C1])
    assert text.index("Chủ đầu tư: Noble") < text.index("[D1]") < text.index("[C1]")
    assert "hiệu lực đến 30/11/2026" in text


def _f(left, right, summary="Thời hạn khác nhau", lv="30/11/2026", rv="31/12/2026", attribute="thời hạn"):
    return {
        "summary": summary,
        "attribute": attribute,
        "left": {"ref": left, "quote": "a", "value": lv},
        "right": {"ref": right, "quote": "b", "value": rv},
    }


def test_giu_muc_hop_le():
    out = parse_findings({"conflicts": [_f("D1", "C1")]}, valid_refs=REFS)
    assert [(f.left_ref, f.right_ref, f.summary) for f in out] == [("D1", "C1", "Thời hạn khác nhau")]
    assert (out[0].attribute, out[0].left_value, out[0].right_value) == ("thời hạn", "30/11/2026", "31/12/2026")


def test_dao_phia_khi_d_nam_ben_phai():
    out = parse_findings({"conflicts": [_f("C2", "D1")]}, valid_refs=REFS)
    assert (out[0].left_ref, out[0].left_quote, out[0].right_ref) == ("D1", "b", "C2")
    assert (out[0].left_value, out[0].right_value) == ("31/12/2026", "30/11/2026")


def test_bo_muc_khong_hop_le():
    raw = {
        "conflicts": [
            _f("D1", "C9"),
            _f("C1", "C2"),
            _f("D1", "D1"),
            {"summary": "x", "left": {"ref": "D1"}},
            "rác",
            _f("D1", "field:projects.1.investor", summary=""),
            _f("D1", "C1", attribute=""),
            _f("D1", "C1", rv=""),
            _f("D1", "C1", lv="2 tỷ", rv=" 2 TỶ "),
        ]
    }
    assert parse_findings(raw, valid_refs=REFS) == []


def test_khong_co_khoa_conflicts_thi_rong():
    assert parse_findings({}, valid_refs=REFS) == []
    assert parse_findings({"conflicts": "x"}, valid_refs=REFS) == []
