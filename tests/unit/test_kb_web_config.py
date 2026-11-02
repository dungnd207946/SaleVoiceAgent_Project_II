"""Bộ mặc định + env của gói kb/web: nguồn, chủ đề, prompt; bản code và bản migration phải khớp."""

import importlib.util
import re
from importlib.resources import files
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.modules.kb.web import mac_dinh

from portal.modules.kb import prompts
from portal.modules.kb.settings import KbEnv
from portal.modules.kb.web import defaults
from portal.modules.kb.web.contracts import (
    PROFILE_CARD,
    PROFILE_DIGEST,
    PROFILE_DOSSIER,
    PROFILE_GROUNDING,
    PROFILE_TAG,
)

ROOT = Path(__file__).resolve().parents[2]

MA_CHU_DE = {
    "road",
    "bridge",
    "transit",
    "travel_time",
    "education",
    "healthcare",
    "retail",
    "leisure",
    "employment",
    "zoning",
    "area_development",
    "nearby_projects",
    "price_trend",
    "project_news",
    "onsite_amenities",
    "offsite_amenities",
    "legal",
    "investor",
    "price_potential",
    "liquidity",
}


def test_nap_duoc_va_domain_khong_trung():
    cfg = mac_dinh.defaults()
    domains = [s.domain for s in cfg.sources]
    assert len(domains) == len(set(domains))
    assert "cafef.vn" in domains


def test_du_20_chu_de_moi_chu_de_toi_da_4_truy_van():
    cfg = mac_dinh.defaults()
    assert {t.code for t in cfg.topics} == MA_CHU_DE
    for t in cfg.topics:
        assert 1 <= len(t.queries) <= 4
        assert t.keywords
        for q in t.queries:
            q.format(project="X", location="Y")


def test_prompt_web_dung_qwen37_va_grounding_dung_gemini():
    for name in (PROFILE_TAG, PROFILE_DOSSIER, PROFILE_CARD, PROFILE_DIGEST):
        assert prompts.get(name).model == "qwen3.7-flash"
    assert prompts.get(PROFILE_GROUNDING).model == "gemini-2.5-flash"


def test_mac_dinh_env(monkeypatch):
    for k in ("KB_WEB_GROUNDING_DAILY_CAP",):
        monkeypatch.delenv(k, raising=False)
    env = KbEnv(_env_file=None)
    assert env.web_grounding_daily_cap == 1200
    assert not hasattr(env, "web_llm_api_key") and not hasattr(env, "web_gemini_api_key")
    assert env.web_llm_concurrency == 4
    assert env.web_fetch_per_domain == 2
    assert env.web_fetch_delay_sec == 1.0
    assert env.web_deep_slices == 2


def test_web_deep_slices_duoi_1_thi_nem():
    with pytest.raises(ValidationError):
        KbEnv(_env_file=None, web_deep_slices=0)


# ─── Edge case bổ sung ngoài brief ──────────────────────────────────────────


def test_load_duoc_cache_tra_cung_instance():
    assert mac_dinh.defaults() is mac_dinh.defaults()


def test_moi_topic_co_queries_sinh_chuoi_khong_placeholder_thua():
    """Mọi query chỉ dùng hai placeholder `{project}`/`{location}` — placeholder lạ (vd
    `{locality}` cũ) thì .format() nổ KeyError ngay ở test này, không đợi tới lúc chạy job thật."""
    cfg = mac_dinh.defaults()
    for t in cfg.topics:
        for q in t.queries:
            rendered = q.format(project="Dự án X", location="Phường Y, Hà Nội")
            assert "{" not in rendered


def test_topics_khong_con_placeholder_dia_danh_cu():
    queries = [q for t in mac_dinh.defaults().topics for q in t.queries]
    assert not any("{locality}" in q or "{province}" in q for q in queries)
    assert any("{location}" in q for q in queries)


def test_moi_chu_de_khong_phu_thuoc_dia_danh_hoac_co_cau_chi_can_ten_du_an():
    """Dự án không có địa danh vẫn còn ít nhất một câu `{project}` ở các chủ đề về dự án."""
    cfg = mac_dinh.defaults()
    project_only = [q for t in cfg.topics for q in t.queries if "{location}" not in q]
    assert project_only and all("{project}" in q for q in project_only)


def test_khong_con_yaml_trong_goi():
    cfg = mac_dinh.defaults()
    assert not hasattr(cfg, "regions") and not hasattr(cfg, "units")
    assert not (files("portal.modules.kb.web") / "data").is_dir()


def _migration_module(name: str = "0971_kbweb_theo_tenant"):
    path = ROOT / "migrations" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"mig_{name[:4]}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ban_dong_bang_trong_migration_khop_ban_code():
    """`0971` rồi `0974` (không import `portal.*`) cộng lại phải ra đúng bộ mặc định trong code, từng ô."""
    mig = _migration_module()
    v2 = _migration_module("0974_kbweb_chu_de_moi")
    assert [tuple(s) for s in mig._SOURCES] == [tuple(s) for s in mac_dinh.SOURCES]
    updates = {c: (ok, oq, nk, nq) for c, ok, oq, nk, nq in v2._UPDATES}
    topics = []
    for c, lb, h, ds, kw, qs in mig._TOPICS:
        ok, oq, nk, nq = updates[c]
        assert (ok, oq) == (kw, qs), f"{c}: bản cũ trong 0974 phải khớp 0971"
        topics.append((c, lb, h, ds, nk, nq))
    topics += [t[:6] for t in v2._NEW]
    assert topics == [tuple(t) for t in mac_dinh.TOPICS]
    assert {**mig._TOPIC_DESCRIPTIONS, **v2._DESCRIPTIONS} == mac_dinh.TOPIC_DESCRIPTIONS
    assert set(mac_dinh.TOPIC_DESCRIPTIONS) == {t[0] for t in mac_dinh.TOPICS}, "chủ đề mặc định nào cũng có mô tả"
    assert (
        tuple(t[2] or t[1] for t in mac_dinh.TOPICS if t[0] in defaults.HIDDEN_TOPIC_CODES) == defaults.HIDDEN_HEADINGS
    )


def test_source_of_khong_ton_tai_tra_none():
    cfg = mac_dinh.defaults()
    assert cfg.source_of("khong-ton-tai.vn") is None


def test_target_per_topic_va_bds_keywords_hop_le():
    cfg = mac_dinh.defaults()
    assert cfg.target_per_topic > 0
    assert cfg.bds_keywords


def test_prompt_web_grounding_khong_co_prompt_tinh(monkeypatch=None):
    """Grounding gọi Gemini với câu hỏi động (không phải prompt tĩnh cố định)."""
    spec = prompts.get(PROFILE_GROUNDING)
    assert spec.temperature == 0


def test_tat_ca_profile_web_deu_load_duoc_qua_get():
    for name in (PROFILE_TAG, PROFILE_DOSSIER, PROFILE_CARD, PROFILE_DIGEST, PROFILE_GROUNDING):
        spec = prompts.get(name)
        assert spec.max_tokens > 0
        assert 0 <= spec.temperature <= 1


def test_prompt_tag_va_dossier_yeu_cau_tra_json():
    # Ràng buộc hợp đồng: các profile phân tích văn bản phải nói rõ định dạng JSON,
    # nếu không parser phía sau (`Task 4/5`) sẽ nhận được prose lẫn JSON.
    for name in (PROFILE_TAG, PROFILE_DOSSIER, PROFILE_CARD, PROFILE_DIGEST):
        assert re.search(r"JSON", prompts.get(name).prompt)


def test_prompt_ho_so_neu_tran_so_muc():
    from portal.modules.kb import prompts
    from portal.modules.kb.web.contracts import MAX_DOSSIER_ITEMS

    assert MAX_DOSSIER_ITEMS == 25
    assert f"tối đa {MAX_DOSSIER_ITEMS} mục" in prompts.get("web_dossier").prompt.lower()


def test_prompt_ho_so_moi_muc_mot_chu_de_co_nhan():
    from portal.modules.kb import prompts

    spec = prompts.get("web_dossier")
    assert "80–300 từ" in spec.prompt and "CHỦ ĐỀ" in spec.prompt and "Gộp MỌI công trình" in spec.prompt
    assert spec.max_tokens == 16000


def test_nhan_chu_de_lay_tu_bo_mac_dinh():
    heads = mac_dinh.defaults().headings()
    assert heads[0] == "Tổng quan"
    assert {"Tiện ích – Y tế", "Tiện ích nội khu", "Mặt bằng giá", "Pháp lý"} <= set(heads)
    assert "Dự án lân cận" not in heads and mac_dinh.defaults().excluded_headings() == ("Dự án lân cận",)
    assert len(heads) == len(set(heads))


def test_prompt_gan_nhan_lay_dia_danh_moi_cap_viet_nhu_trong_bai():
    text = prompts.get(PROFILE_TAG).prompt
    for part in ("tên đường/phố", "khu đô thị", "xã/phường", "quận/huyện", "tỉnh/thành", "viết như trong bài"):
        assert part in text


def test_prompt_ho_so_va_the_deu_bo_tin_tieu_cuc():
    dossier = prompts.get(PROFILE_DOSSIER).prompt
    assert "Mặt bằng giá" in dossier and "Bỏ tin tiêu cực" in dossier and "[2][3]" in dossier
    card = prompts.get(PROFILE_CARD).prompt
    assert "không được nói xấu dự án" in card and "Bỏ tin" in card
    assert "chậm cấp sổ" in card and "giữ cả tin tích cực lẫn tiêu cực" not in card


def test_prompt_the_khong_lan_du_an_trung_ten_va_khong_tu_nhan_dinh():
    from portal.modules.kb import prompts

    spec = prompts.get("web_card").prompt
    assert "trùng hoặc gần trùng tên ở tỉnh/thành khác" in spec
    assert "Không viết lời khuyên, cảnh báo hay nhận định" in spec
