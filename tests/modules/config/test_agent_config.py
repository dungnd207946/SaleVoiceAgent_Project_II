"""`tenant_data.agent_config` — bản PHẲNG ghi lúc Lưu và áp dụng (migration 0910).

Bốn thứ được canh ở đây, theo thứ tự "hỏng thì đau tới đâu":

  1. HAI CHIỀU KHỚP NHAU. Từ `0966` bảng này là nguồn duy nhất: `GET /config` dựng payload
     NGƯỢC từ nó (`tu_hang_phang`). Ánh xạ ngược sai = form mở ra khác thứ vừa lưu.
  2. ÁNH XẠ ĐÚNG CỘT. `hang_phang()` kiểm không cần Postgres — ghi đúng dữ liệu vào sai cột
     là kiểu lỗi không làm câu SQL nào đỏ, nên nó phải có test riêng chứ không dựa vào
     test đầu-cuối "có một hàng".
  3. HAI HÀNG MỖI TENANT (một mỗi role) — canh ở `test_cau_hinh_theo_role.py`.
  4. HAI DANH SÁCH ĐÓNG KHỚP NHAU. CHECK `tone`/`reply_length` trong migration là bản nhân
     đôi của `contracts.GIONG_DIEU`/`DO_DAI`; thêm preset mà chỉ sửa một chỗ thì publish của
     preset mới chết ở tầng DB — trên production, không phải ở đây.
"""

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from portal.modules.config.agent_config import hang_phang, tu_hang_phang
from portal.modules.config.contracts import DO_DAI, GIONG_DIEU, ConfigPayload
from tests.modules.config.conftest import PAYLOAD_HOP_LE

GOC = Path(__file__).resolve().parents[3]

PAYLOAD_DAY_DU = {
    "schema_version": 3,
    "danh_tinh": {
        "ten_agent": "Mai",
        "ten_thuong_hieu": "An Phú Land",
        "tu_xung": "em",
        "goi_khach": "anh/chị",
        "loi_chao": "Dạ em Mai bên An Phú Land ạ.",
    },
    "pham_vi": {
        "linh_vuc": "realestate",
        "lam_gi": "Tư vấn dự án và đặt lịch tham quan.",
        "khong_lam_gi": "Hậu mãi và giá riêng — chuyển người thật.",
        "phong_ban": [
            {"ten": "CSKH", "khi_nao": "khách hỏi hợp đồng đã ký"},
            {"ten": "Kinh doanh", "khi_nao": "khách hỏi giá riêng"},
        ],
        "cau_tu_choi": "Việc này em xin phép chuyển anh/chị cho bộ phận phụ trách.",
    },
    "giong": {"giong_dieu": "lich_su", "do_dai": "chi_tiet"},
    # Thứ tự CỐ TÌNH không theo alphabet — dùng để chứng minh `skills` giữ nguyên thứ tự
    # người dùng bật, không sort. `booking` cần `find_project` (tools.PHU_THUOC).
    "tools": {"enabled": ["kb_search", "find_project", "booking"]},
    "tts_normalization": [
        {"term": "NCLB", "read_as": "Noble Crystal Long Biên"},
        {"term": "SSLC", "read_as": "Sunshine Legend City"},
    ],
}


# ─── Ánh xạ payload -> hàng phẳng (không cần Postgres) ───────────────────────


def test_hang_phang_anh_xa_du_moi_input_cua_form():
    """Mỗi ô trên form Agent & Kênh phải xuống đúng một cột — 11 ô, 11 khoá."""
    h = hang_phang(ConfigPayload.model_validate(PAYLOAD_DAY_DU), version=7)

    assert h == {
        "name": "Mai",
        "brand_name": "An Phú Land",
        "self_pronoun": "em",
        "customer_pronoun": "anh/chị",
        "greeting": "Dạ em Mai bên An Phú Land ạ.",
        "scope_does": "Tư vấn dự án và đặt lịch tham quan.",
        "scope_does_not": "Hậu mãi và giá riêng — chuyển người thật.",
        "refusal_line": "Việc này em xin phép chuyển anh/chị cho bộ phận phụ trách.",
        "departments": [
            {"ten": "CSKH", "khi_nao": "khách hỏi hợp đồng đã ký"},
            {"ten": "Kinh doanh", "khi_nao": "khách hỏi giá riêng"},
        ],
        "tone": "lich_su",
        "reply_length": "chi_tiet",
        "skills": ["kb_search", "find_project", "booking"],
        "tts_normalization": {
            "NCLB": "Noble Crystal Long Biên",
            "SSLC": "Sunshine Legend City",
        },
        "version": 7,
    }


def test_hang_phang_giu_nguyen_thu_tu_ky_nang():
    """Không sort: thứ tự trong `tools.enabled` là dữ liệu người dùng nhập.

    Sort ở tầng ghi làm form mở ra thứ tự khác thứ tự người dùng bật.
    """
    cfg = ConfigPayload.model_validate({**PAYLOAD_DAY_DU, "tools": {"enabled": ["escalate", "find_project"]}})

    assert hang_phang(cfg, version=1)["skills"] == ["escalate", "find_project"]


def test_hang_phang_dung_mac_dinh_khi_form_de_trong():
    """Ô để trống ⇒ mặc định của `ConfigPayload`, KHÔNG phải None.

    Cột trong 0910 là `NOT NULL DEFAULT ''`, nên một `None` lọt xuống đây thành lỗi
    ràng buộc ở giữa giao dịch publish — tức người bấm nhận 500 cho một ô để trống.
    """
    h = hang_phang(ConfigPayload.model_validate(PAYLOAD_HOP_LE), version=1)

    assert h["greeting"] == ""
    assert h["self_pronoun"] == "em"
    assert h["customer_pronoun"] == "anh/chị"
    assert h["tone"] == "than_thien"


def test_hang_phang_doi_danh_sach_thanh_object():
    """Payload là DANH SÁCH (để 422 được khi trùng khoá), cột DB là OBJECT — đó đúng hình
    dạng `{reading, abbrev}` mà agent đang parse từ file nền."""
    cfg = ConfigPayload.model_validate(
        {
            **PAYLOAD_DAY_DU,
            "tts_normalization": [{"term": "NPTTL", "read_as": "Noble Palace Tây Thăng Long"}],
        }
    )

    assert hang_phang(cfg, version=1)["tts_normalization"] == {"NPTTL": "Noble Palace Tây Thăng Long"}


def test_hang_phang_tu_dien_rong_thanh_object_rong_khong_phai_mang_rong():
    """`{}` chứ không `[]`. Cột có CHECK `jsonb_typeof = 'object'`, nên một `[]` lọt xuống
    đây là lỗi ràng buộc GIỮA giao dịch publish — người bấm nhận 500."""
    h = hang_phang(ConfigPayload.model_validate(PAYLOAD_HOP_LE), version=1)

    assert h["tts_normalization"] == {}
    assert not isinstance(h["tts_normalization"], list)
    assert h["reply_length"] == "trung_binh"
    assert None not in h.values()


def test_check_tone_va_do_dai_khop_contracts():
    """CỔNG: hai danh sách đóng ở migration 0910 phải trùng `contracts`.

    Nhân đôi là có chủ đích (bảng này được đọc từ ngoài Portal — xem header 0910), nên
    chỗ duy nhất giữ cho bản nhân đôi không lệch là cổng này. Thêm preset thứ 4 vào
    `contracts.GIONG_DIEU` mà quên migration ⇒ đỏ ở đây, không đỏ trên production.
    """
    duong = GOC / "migrations" / "versions" / "0910_bang_agent_config.py"
    spec = importlib.util.spec_from_file_location("mig_0910", duong)
    assert spec and spec.loader
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    assert mig._TONE == GIONG_DIEU
    assert mig._DO_DAI == DO_DAI


# ─── Chiều ngược: hàng phẳng -> payload (`GET /config` từ `0966`) ────────────


def _nhu_asyncpg(h: dict) -> dict:
    """asyncpg trả jsonb dạng CHUỖI — giả đúng hình dạng đó, không đưa list/dict thẳng."""
    return {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in h.items()}


def test_tu_hang_phang_la_nghich_dao_cua_hang_phang():
    """Không còn `config_drafts` giữ bản gốc: form mở ra chính là chiều ngược này. Một cột
    ánh xạ ngược sai là người dùng thấy khác thứ họ vừa lưu, và bấm Lưu lần nữa là ghi đè."""
    cfg = ConfigPayload.model_validate(PAYLOAD_DAY_DU)
    h = _nhu_asyncpg(hang_phang(cfg, version=3))

    assert ConfigPayload.model_validate(tu_hang_phang(h, schema_version=3)) == cfg


def test_tu_hang_phang_cot_jsonb_rong():
    h = _nhu_asyncpg(hang_phang(ConfigPayload.model_validate(PAYLOAD_HOP_LE), version=1))
    h["tts_normalization"] = None

    assert tu_hang_phang(h, schema_version=3)["tts_normalization"] == []


# ─── Đầu-cuối ────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_tim_theo_ky_nang_dang_bat(client_cfg: httpx.AsyncClient, pool, workspace_cfg):
    """`skills` dạng mảng để trả lời được "tenant nào bật kỹ năng X" bằng một câu SQL."""
    assert (await client_cfg.post("/api/v1/config/roles", json={"ten": "Sale"})).status_code == 201
    ban = {"cauHinh": {"sale": PAYLOAD_DAY_DU, "customer": PAYLOAD_HOP_LE}}
    r = await client_cfg.put("/api/v1/config", json=ban)
    assert r.status_code == 200, r.text

    async with pool.acquire() as conn:
        co_booking = await conn.fetch(
            "SELECT role FROM tenant_data.agent_config WHERE tenant_id = $1 AND skills @> '[\"booking\"]'::jsonb",
            workspace_cfg,
        )
    assert [r["role"] for r in co_booking] == ["sale"]
