import json
import logging

import httpx
import pytest

from portal.modules.kb.contracts import TemporaryError
from portal.modules.kb.web.llm import MAX_TAG_CHARS, TruncatedLlmError, WebLlm, parse_json, tags_from


def _llm(handler, **kwargs) -> WebLlm:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WebLlm(base_url="https://llm.test/v1", api_key="k", http=http, **kwargs)


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_parse_json_bo_fence_va_chu_thua():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Đây: {"a": 2} xong') == {"a": 2}
    with pytest.raises(ValueError):
        parse_json("không có json")


async def test_tag_lam_sach_nhan_va_gui_dung_model():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return _reply(
            '{"relevant": true, "projects": ["Wonder City", "Wonder City", null],'
            ' "location": ["Hà Nội", "", "Đan Phượng"]}'
        )

    tags = await _llm(handler).tag("tiêu đề", "nội dung")
    assert tags.relevant
    assert tags.projects == ("Wonder City",)
    assert tags.location == ("Hà Nội", "Đan Phượng")
    assert seen["model"] == "qwen3.7-flash"
    assert seen["enable_thinking"] is False
    assert seen["response_format"] == {"type": "json_object"}


async def test_429_la_loi_tam_thoi():
    with pytest.raises(TemporaryError):
        await _llm(lambda r: httpx.Response(429)).tag("t", "x")


def test_thieu_key_thi_khong_dung():
    with pytest.raises(ValueError):
        WebLlm(base_url="https://x", api_key="")


# ─── edge case bổ sung ──────────────────────────────────────────────────────


async def test_500_la_loi_tam_thoi():
    with pytest.raises(TemporaryError):
        await _llm(lambda r: httpx.Response(503)).tag("t", "x")


async def test_400_khong_phai_loi_tam_thoi():
    with pytest.raises(httpx.HTTPStatusError):
        await _llm(lambda r: httpx.Response(400, json={"error": "bad"})).tag("t", "x")


async def test_timeout_la_loi_tam_thoi():
    def handler(req):
        raise httpx.TimeoutException("timeout")

    with pytest.raises(TemporaryError):
        await _llm(handler).tag("t", "x")


async def test_gui_dung_headers_va_dung_url():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        return _reply('{"relevant": false, "projects": [], "location": []}')

    await _llm(handler).tag("t", "x")
    assert seen["url"] == "https://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer k"


async def test_ask_gui_system_va_user_message_dung_profile():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return _reply('{"a": 1}')

    out = await _llm(handler).ask("web_tag", "nội dung người dùng")
    assert out == {"a": 1}
    assert seen["messages"] == [
        {"role": "system", "content": seen["messages"][0]["content"]},
        {"role": "user", "content": "nội dung người dùng"},
    ]
    assert seen["messages"][1]["content"] == "nội dung người dùng"
    assert seen["temperature"] == 0
    assert seen["max_tokens"] == 800


async def test_tag_cat_bot_text_qua_dai():
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return _reply('{"relevant": true, "projects": [], "location": []}')

    long_text = "x" * (MAX_TAG_CHARS + 500)
    await _llm(handler).tag("t", long_text)
    user_msg = seen["messages"][1]["content"]
    # tiêu đề + phần văn bản đã bị cắt còn tối đa MAX_TAG_CHARS ký tự
    assert len(user_msg) <= MAX_TAG_CHARS + len("TIÊU ĐỀ: t\n\n")


def test_tags_from_bo_qua_gia_tri_khong_phai_list():
    tags = tags_from({"relevant": "true", "projects": "not-a-list", "location": None})
    assert tags.relevant is True
    assert tags.projects == ()
    assert tags.location == ()


async def test_concurrency_gioi_han_song_song():
    import asyncio

    in_flight = 0
    max_seen = 0

    async def slow_handler(req):
        nonlocal in_flight, max_seen
        in_flight += 1
        max_seen = max(max_seen, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return _reply('{"relevant": false, "projects": [], "location": []}')

    llm = WebLlm(
        base_url="https://llm.test/v1",
        api_key="k",
        concurrency=2,
        http=httpx.AsyncClient(transport=httpx.MockTransport(slow_handler)),
    )
    await asyncio.gather(*(llm.tag("t", "x") for _ in range(5)))
    assert max_seen <= 2


async def test_aclose_dong_http_client():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: _reply("{}")))
    llm = WebLlm(base_url="https://x", api_key="k", http=http)
    await llm.aclose()
    assert http.is_closed


async def test_bi_cat_vi_max_tokens_thi_nem_loi_rieng_mang_ten_profile():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "length"}]})

    with pytest.raises(TruncatedLlmError, match="web_dossier") as exc:
        await _llm(handler).ask("web_dossier", "x")
    assert isinstance(exc.value, ValueError), "bên gọi đang bắt ValueError cho JSON hỏng — bị cắt cùng nhánh"


async def test_ghi_log_so_token_moi_luot_goi(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("portal.modules.kb.web.llm"), "disabled", False)

    def handler(req):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1234, "completion_tokens": 56},
            },
        )

    with caplog.at_level("INFO", logger="portal.modules.kb.web.llm"):
        await _llm(handler).ask("web_dossier", "x")
    (rec,) = [r for r in caplog.records if "tokens" in r.getMessage()]
    assert rec.levelname == "INFO"
    assert "web_dossier" in rec.getMessage() and "1234" in rec.getMessage() and "56" in rec.getMessage()


async def test_khong_co_usage_van_tra_ket_qua(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("portal.modules.kb.web.llm"), "disabled", False)
    with caplog.at_level("INFO", logger="portal.modules.kb.web.llm"):
        assert await _llm(lambda r: _reply('{"a": 1}')).ask("web_tag", "x") == {"a": 1}
    assert any("prompt_tokens=None" in r.getMessage() for r in caplog.records)


async def test_ket_thuc_binh_thuong_khong_canh_bao(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("portal.modules.kb.web.llm"), "disabled", False)

    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": 1}'}, "finish_reason": "stop"}]})

    with caplog.at_level("WARNING"):
        await _llm(handler).ask("web_dossier", "x")
    assert caplog.text == ""


def test_web_dossier_du_cho_de_viet_ho_so_dai():
    from portal.modules.kb import prompts

    assert prompts.get("web_dossier").max_tokens == 16000


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        ("true", True),
        ("TRUE", True),
        (" True ", True),
        (False, False),
        ("false", False),
        ("0", False),
        ("", False),
        (None, False),
        (1, False),
        ("yes", False),
        ([1], False),
    ],
)
def test_tags_from_relevant_chi_true_khi_la_true_that(value, expected):
    assert tags_from({"relevant": value}).relevant is expected


def test_tags_from_cat_toi_da_10_du_an_va_10_dia_danh():
    raw = {"relevant": True, "projects": [f"Dự án {i}" for i in range(15)], "location": [f"Xã {i}" for i in range(12)]}
    tags = tags_from(raw)
    assert tags.projects == tuple(f"Dự án {i}" for i in range(10))
    assert tags.location == tuple(f"Xã {i}" for i in range(10))


def test_tags_from_cat_sau_khi_bo_trung():
    raw = {"relevant": True, "projects": ["A", "A", None, *[f"P{i}" for i in range(12)]], "location": []}
    assert tags_from(raw).projects == ("A", *(f"P{i}" for i in range(9)))


def test_prompt_web_tag_gioi_han_10_va_giu_max_tokens():
    from portal.modules.kb import prompts

    spec = prompts.get("web_tag")
    assert spec.max_tokens == 800
    assert "tối đa 10 dự án" in spec.prompt and "tối đa 10 địa danh" in spec.prompt


def test_prompt_web_card_chi_viet_dung_du_an_va_cho_phep_rong():
    from portal.modules.kb import prompts

    text = prompts.get("web_card").prompt
    assert '"DỰ ÁN:"' in text
    assert '{"items": []}' in text


def test_tags_from_bo_ha_tang_tien_ich_khoi_projects():
    raw = {
        "relevant": True,
        "projects": [
            "Tuyến metro số 1",
            "Vinhomes Royal Island",
            "Vinmec Royal Island",
            "Khu công nghiệp Thủy Nguyên",
            "Vinpearl Golf Hải Phòng",
            "Wonder City",
        ],
        "location": ["Vũ Yên"],
    }
    assert tags_from(raw).projects == ("Vinhomes Royal Island", "Wonder City")


def test_tags_from_bo_ha_tang_truoc_khi_cat_10():
    junk = [f"Tuyến metro số {i}" for i in range(10)]
    raw = {"relevant": True, "projects": [*junk, *[f"Dự án {i}" for i in range(10)]], "location": []}
    assert tags_from(raw).projects == tuple(f"Dự án {i}" for i in range(10))


def test_prompt_web_tag_liet_ke_nhan_khong_dua_vao_projects():
    from portal.modules.kb import prompts

    text = prompts.get("web_tag").prompt.casefold()
    for word in ("metro", "đường sắt", "khu công nghiệp", "bệnh viện", "sân golf", "trung tâm thương mại", "sân bay"):
        assert word in text


async def test_ghi_token_vao_bo_dem_theo_bac_gia():
    from portal.modules.kb.web.usage import metering

    def handler(req):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"relevant": false}'}}],
                "usage": {"prompt_tokens": 40_000, "completion_tokens": 120},
            },
        )

    with metering() as m:
        await _llm(handler).tag("t", "x")
    t = m.tallies[("llm", "dashscope", "qwen3.7-flash>32k")]
    assert (t.input_tokens, t.output_tokens) == (40_000, 120)
