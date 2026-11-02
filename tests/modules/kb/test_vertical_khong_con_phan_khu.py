"""`zones` thôi làm nguồn embed riêng — nó là khối con của doc dự án."""

import pytest

from portal.modules.kb.directive import resolve
from portal.modules.kb.directive.verticals.real_estate import REAL_ESTATE


def test_chi_con_hai_nguon_embed():
    assert [s.table for s in REAL_ESTATE.embed_sources] == ["projects", "documents"]
    assert "phan_khu" not in {s.doc_type for s in REAL_ESTATE.embed_sources}


def test_zones_khong_con_tra_duoc_spec():
    with pytest.raises(ValueError, match="không phải nguồn embed"):
        resolve.source_for(REAL_ESTATE, "zones")


def test_projects_khai_khoi_con_zones():
    block = REAL_ESTATE.embed_sources[0].child_block
    assert block is not None
    assert block.table == "zones"
    assert block.section == "Cơ cấu sản phẩm"
    assert block.subsection == "Phân khu"


def test_nhan_loai_hinh_lay_tu_so_realestate_khong_chep_tay():
    from portal.modules.realestate.contracts import PROJECT_TYPE_LABELS

    block = REAL_ESTATE.embed_sources[0].child_block
    assert block.value_labels["category"] is PROJECT_TYPE_LABELS
