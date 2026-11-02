# Config shape v3 — Portal + Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portal ghi `config` jsonb theo hình dạng §4 v3 mà agent đọc được, và phát ra một mẫu vàng để repo agent kiểm hợp đồng bằng CI.

**Architecture:** `ConfigPayload` (tên tiếng Việt) vẫn là hợp đồng form. Thêm một hàm thuần `sang_config_agent()` dịch sang §4 v3 lúc publish, kết quả đóng băng vào cột mới `control.config_versions.config_agent` trong cùng transaction với version + con trỏ. View `agent_api.agent_published_config` lộ cột đó thay cho `payload`.

**Tech Stack:** Python 3.13 · uv · FastAPI · Pydantic v2 · asyncpg thô · Alembic · pytest + testcontainers · React 18 + Vite + TypeScript strict

**Spec:** [`../specs/2026-08-05-config-shape-v3-agent-render-design.md`](../specs/2026-08-05-config-shape-v3-agent-render-design.md)

## Global Constraints

- **Không commit lên `develop`.** Tạo nhánh trước bước 1: `git checkout -b feat/config-shape-v3`.
- `SCHEMA_VERSION_HIEN_TAI = 3` — đúng số này, không 2.1, không "3.0".
- Sổ kỹ năng sau hợp nhất, đúng 12 tên: lõi `update_customer` · `kb_search` · `find_project` · `escalate`; tùy chọn `discover_projects` · `get_project_overview` · `get_document` · `search_units` · `check_inventory` · `recommend_units` · `booking` · `send_media`.
- Tên trường form khoá cứng: `tu_xung`, `goi_khach`. Khoá §4 khoá cứng: `identity` · `scope` · `voice` · `tools` · `data_source` · `schema_version`.
- `config_agent` **không chứa 4 tool lõi** trong `tools.enabled` (agent tự union).
- Mọi endpoint khai `require(action)` (Luật 4). Module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts` (Luật 3).
- Sau mọi lần sửa `tools.py`: chạy `make contracts` rồi commit cả `contracts/`.
- Migration mới: revision `0908_config_agent`, `down_revision = "0907_view_control_plane"`.
- ruff line-length 120. Chạy `make lint` trước mỗi commit.
- Hai repo: `P/` = `odyssey-portal-backend`, `F/` = `odyssey-portal-frontend`.

---

### Task 1: Hợp nhất sổ kỹ năng

**Files:**
- Modify: `P/src/portal/modules/config/tools.py:38` (xoá `get_project_financial`), `:59` (xoá dòng `PHU_THUOC` của nó), thêm `get_document`
- Modify: `P/contracts/tools.json` (sinh lại, không sửa tay)
- Test: `P/tests/modules/config/test_tools_catalogue.py` (mới)

**Interfaces:**
- Consumes: —
- Produces: `MUOI_HAI_KY_NANG: tuple[KyNang, ...]` với đúng 12 tên ở Global Constraints; `PHU_THUOC["get_document"] == ("find_project",)`

- [ ] **Step 1: Tạo nhánh**

```bash
cd odyssey-portal-backend && git checkout -b feat/config-shape-v3
```

- [ ] **Step 2: Viết test đỏ**

```python
# P/tests/modules/config/test_tools_catalogue.py
"""Sổ kỹ năng phải khớp tập tool agent THỰC SỰ có schema.

`get_project_financial` từng nằm ở đây nhưng agent không có schema nào cho nó —
bật nó là dạy LLM gọi một tool không tồn tại. `get_document` thì ngược lại.
"""

from portal.modules.config.tools import MUOI_HAI_KY_NANG, PHU_THUOC, TEN_KY_NANG

LOI = frozenset({"update_customer", "kb_search", "find_project", "escalate"})
TUY_CHON = frozenset({
    "discover_projects", "get_project_overview", "get_document", "search_units",
    "check_inventory", "recommend_units", "booking", "send_media",
})


def test_dung_12_ten_va_khop_agent():
    assert TEN_KY_NANG == LOI | TUY_CHON
    assert len(MUOI_HAI_KY_NANG) == 12


def test_get_project_financial_da_bi_bo():
    assert "get_project_financial" not in TEN_KY_NANG
    assert "get_project_financial" not in PHU_THUOC


def test_get_document_phu_thuoc_find_project():
    # schema của nó nhận `project_code` — luật ở docstring PHU_THUOC.
    assert PHU_THUOC["get_document"] == ("find_project",)
```

- [ ] **Step 3: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/config/test_tools_catalogue.py -v`
Expected: FAIL — `test_dung_12_ten_va_khop_agent` (có `get_project_financial`, thiếu `get_document`)

- [ ] **Step 4: Sửa `tools.py`**

Xoá `KyNang("get_project_financial", …)` ở dòng 38 và dòng `"get_project_financial": ("find_project",),` trong `PHU_THUOC`. Thêm vào `MUOI_HAI_KY_NANG` (giữ thứ tự khai báo — `gen_contracts.py:32` dựa vào nó):

```python
    KyNang(
        "get_document",
        "Gửi tài liệu của dự án",
        "Lấy file CSBH, pháp lý, brochure của một dự án khi khách xin file.",
    ),
```

và vào `PHU_THUOC`:

```python
    "get_document": ("find_project",),
```

- [ ] **Step 5: Chạy test — phải xanh**

Run: `uv run pytest tests/modules/config/test_tools_catalogue.py -v`
Expected: PASS (3 test)

- [ ] **Step 6: Sinh lại mẫu vàng của FE và chạy cổng cũ**

Run: `make contracts && uv run pytest tests/api/test_contracts.py tests/modules/config -v`
Expected: PASS. Nếu `test_contracts_m5.py` đỏ vì đếm số kỹ năng thì sửa con số ở đó, không sửa `tools.py`.

- [ ] **Step 7: Commit**

```bash
git add tests/modules/config/test_tools_catalogue.py src/portal/modules/config/tools.py contracts/tools.json
git commit -m "fix(config): sổ kỹ năng khớp schema agent — bỏ get_project_financial, thêm get_document"
```

---

### Task 2: Tách ô xưng hô + `SCHEMA_VERSION = 3`

**Files:**
- Modify: `P/src/portal/modules/config/contracts.py:31` (`= 3`), `:73` (thay `xung_ho`)
- Modify: `P/src/portal/modules/config/bundle.py:159`
- Modify: `P/src/portal/modules/config/service.py:91,115`
- Modify: `P/src/portal/modules/config/router.py:52,160`
- Modify: `P/tests/modules/config/test_contracts_m5.py:34`, `P/tests/modules/config/test_publish.py:54`
- Modify: `P/tests/modules/config/conftest.py` — `PAYLOAD_HOP_LE["schema_version"]` từ `2` → `3`. **Bắt buộc:** payload này là fixture dùng chung của cả `tests/modules/config/` lẫn `tests/modules/agent_seam/`; để `2` thì Task 4 không thể xanh

**Interfaces:**
- Consumes: Task 1 (`MUOI_HAI_KY_NANG`)
- Produces: `DanhTinh.tu_xung: str = "em"`, `DanhTinh.goi_khach: str = "anh/chị"`; `SCHEMA_VERSION_HIEN_TAI = 3`; `BanXemTruoc.tu_xung` + `.goi_khach`; `XemTruocOut.tuXung` + `.goiKhach`

- [ ] **Step 1: Viết test đỏ**

```python
# thêm vào P/tests/modules/config/test_contracts_m5.py
def test_xung_ho_la_hai_o_rieng():
    cfg = payload_mac_dinh("An Phú Land")
    assert cfg.danh_tinh.tu_xung == "em"
    assert cfg.danh_tinh.goi_khach == "anh/chị"
    assert not hasattr(cfg.danh_tinh, "xung_ho")


def test_schema_version_la_3():
    assert payload_mac_dinh("X").schema_version == 3
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/config/test_contracts_m5.py -v`
Expected: FAIL — `AttributeError: 'DanhTinh' object has no attribute 'tu_xung'`

- [ ] **Step 3: Sửa `contracts.py`**

`:31` → `SCHEMA_VERSION_HIEN_TAI = 3`, và cập nhật docstring ngay dưới nó thêm một dòng: `v3 tách ô xưng hô thành hai và mở rộng §4 cho agent tự render.`

Thay dòng `:73`:

```python
    tu_xung: str = Field(default="em", max_length=20)
    """Agent tự xưng là gì. Ô riêng, KHÔNG gộp với `goi_khach` thành "em ↔ anh/chị":
    một ô có dấu ↔ là bắt người dùng học cú pháp của ta, và nó buộc tầng dưới phải
    tách chuỗi — một phép tách có thể sai âm thầm."""
    goi_khach: str = Field(default="anh/chị", max_length=20)
    """Agent gọi khách là gì."""
```

- [ ] **Step 4: Sửa bốn chỗ dùng nó**

`bundle.py:159` — trong `_soul()`, thay `dt.xung_ho,` bằng:

```python
        f"Bạn tự xưng “{dt.tu_xung}”, gọi khách là “{dt.goi_khach}”.",
```

`service.py:91` — trong `BanXemTruoc`, thay `xung_ho: str` bằng hai dòng `tu_xung: str` và `goi_khach: str`.
`service.py:115` — thay `xung_ho=moi.danh_tinh.xung_ho,` bằng `tu_xung=moi.danh_tinh.tu_xung,` và `goi_khach=moi.danh_tinh.goi_khach,`.
`router.py:52` — thay `xungHo: str` bằng `tuXung: str` và `goiKhach: str`.
`router.py:160` — thay `xungHo=b.xung_ho,` bằng `tuXung=b.tu_xung,` và `goiKhach=b.goi_khach,`.

- [ ] **Step 5: Sửa hai test cũ**

`test_contracts_m5.py:34` — xoá dòng `assert cfg.danh_tinh.xung_ho == "em ↔ anh/chị"` (đã được hai test mới ở Step 1 thay thế).
`test_publish.py:54` — thay bằng:

```python
    assert payload["danh_tinh"]["tu_xung"] == "em"
    assert payload["danh_tinh"]["goi_khach"] == "anh/chị"
```

- [ ] **Step 6: Chạy toàn bộ test của module**

Run: `uv run pytest tests/modules/config -v`
Expected: PASS. Ruff không bắt được chỗ sót tên trường cũ, nên kiểm bằng grep — nhưng **chỉ trên `src/`**:

```bash
grep -rn 'xung_ho' src --include='*.py'      # phải 0 kết quả
```

Không grep `tests/`: Step 1 cố ý viết `assert not hasattr(cfg.danh_tinh, "xung_ho")` — một assertion **phủ định** chứng minh trường đã bị xoá, nên nó buộc phải chứa chuỗi đó. Đòi 0 kết quả trên `tests/` là đòi hai điều loại trừ nhau.

- [ ] **Step 7: Commit**

```bash
make lint
git add src/portal/modules/config tests/modules/config
git commit -m "feat(config)!: tách xưng hô thành tu_xung + goi_khach, schema_version=3"
```

---

### Task 3: Hàm thuần `sang_config_agent` + cổng chống rơi trường

**Files:**
- Create: `P/src/portal/modules/config/config_agent.py`
- Test: `P/tests/modules/config/test_config_agent.py` (mới)

**Interfaces:**
- Consumes: Task 2 (`ConfigPayload`, `DanhTinh.tu_xung/goi_khach`), `bundle.cau_tu_choi(cfg) -> str`
- Produces: `sang_config_agent(cfg: ConfigPayload) -> dict` · `SCHEMA_VERSION_AGENT: int = 3` · `TOOL_LOI: frozenset[str]`

- [ ] **Step 1: Viết test đỏ — hai cổng trong một file**

```python
# P/tests/modules/config/test_config_agent.py
"""Cổng chống rơi trường ở biên publish.

ÁNH_XA là danh sách đóng: mọi lá của `ConfigPayload` phải khai ở đây, kèm đường
đích trong §4 (hoặc `None` nếu cố ý không sang). Thêm một ô vào form mà quên map
⇒ `test_moi_la_deu_khai_trong_anh_xa` đỏ. Đó là toàn bộ điểm của file này: con
bug 9/9-trường-mất sống được vì không có cổng nào ở đúng chỗ này.
"""

import pytest

from portal.modules.config.config_agent import SCHEMA_VERSION_AGENT, sang_config_agent
from portal.modules.config.contracts import ConfigPayload, DanhTinh, Giong, PhamVi, PhongBan, Tools

ANH_XA: dict[str, str | None] = {
    "schema_version": None,  # §4 mang schema_version riêng, không map từ payload
    "danh_tinh.ten_agent": "identity.agent_name",
    "danh_tinh.ten_thuong_hieu": "identity.brand",
    "danh_tinh.tu_xung": "identity.honorific_self",
    "danh_tinh.goi_khach": "identity.honorific_customer",
    "danh_tinh.loi_chao": "identity.greeting",
    "pham_vi.linh_vuc": None,  # agent không tiêu thụ vertical ở db-mode
    "pham_vi.lam_gi": "scope.does",
    "pham_vi.khong_lam_gi": "scope.does_not",
    "pham_vi.cau_tu_choi": "scope.refusal",
    "pham_vi.phong_ban": "scope.handoff_departments",
    "giong.giong_dieu": "voice.tone",
    "giong.do_dai": "voice.length",
    "tools.enabled": "tools.enabled",
}


def _la_cua_model(model, tien_to: str = "") -> set[str]:
    ra: set[str] = set()
    for ten, f in model.model_fields.items():
        con = getattr(f.annotation, "model_fields", None)
        if con is not None:
            ra |= _la_cua_model(f.annotation, f"{tien_to}{ten}.")
        else:
            ra.add(f"{tien_to}{ten}")
    return ra


def _lay(d: dict, duong: str):
    for phan in duong.split("."):
        d = d[phan]
    return d


def _cfg_day_du() -> ConfigPayload:
    return ConfigPayload(
        schema_version=3,
        danh_tinh=DanhTinh(
            ten_agent="Mai", ten_thuong_hieu="An Phú Land",
            tu_xung="em", goi_khach="anh/chị", loi_chao="Dạ em Mai ạ.",
        ),
        pham_vi=PhamVi(
            lam_gi="Tư vấn dự án.", khong_lam_gi="Hậu mãi.",
            cau_tu_choi="Em xin phép chuyển bộ phận phụ trách ạ.",
            phong_ban=[PhongBan(ten="Phòng kinh doanh", khi_nao="Khách hỏi giá riêng")],
        ),
        giong=Giong(giong_dieu="lich_su", do_dai="chi_tiet"),
        tools=Tools(enabled=["find_project", "discover_projects", "booking", "kb_search", "escalate"]),
    )


def test_moi_la_deu_khai_trong_anh_xa():
    assert _la_cua_model(ConfigPayload) == set(ANH_XA)


@pytest.mark.parametrize("nguon,dich", [(k, v) for k, v in ANH_XA.items() if v])
def test_khong_truong_nao_roi(nguon, dich):
    out = sang_config_agent(_cfg_day_du())
    assert _lay(out, dich) not in ("", None, [], {}), f"{nguon} → {dich} rơi mất"


def test_schema_version_va_data_source():
    out = sang_config_agent(_cfg_day_du())
    assert out["schema_version"] == SCHEMA_VERSION_AGENT == 3
    assert out["data_source"] == "pg_kb"


def test_phong_ban_giu_ca_khi_nao():
    out = sang_config_agent(_cfg_day_du())
    assert out["scope"]["handoff_departments"] == [
        {"name": "Phòng kinh doanh", "when": "Khách hỏi giá riêng"}
    ]


def test_tools_enabled_khong_chua_tool_loi():
    out = sang_config_agent(_cfg_day_du())
    assert set(out["tools"]["enabled"]).isdisjoint({"find_project", "kb_search", "escalate", "update_customer"})
    assert "discover_projects" in out["tools"]["enabled"]
    assert "booking" in out["tools"]["enabled"]


def test_cau_tu_choi_rong_thi_sinh_tu_thuong_hieu():
    cfg = _cfg_day_du()
    cfg = cfg.model_copy(update={"pham_vi": cfg.pham_vi.model_copy(update={"cau_tu_choi": ""})})
    out = sang_config_agent(cfg)
    assert "An Phú Land" in out["scope"]["refusal"]
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/config/test_config_agent.py -v`
Expected: FAIL — `ModuleNotFoundError: portal.modules.config.config_agent`

- [ ] **Step 3: Viết `config_agent.py`**

```python
"""Dịch `ConfigPayload` → hình dạng `config` §4 v3 mà agent đọc.

HÀM THUẦN, KHÔNG I/O — cùng lý lẽ `bundle.render()`: đây là phần dễ sai nhất ở
biên hai repo, và nó phải test được không cần Postgres/MinIO/worker.

VÌ SAO KẾT QUẢ ĐƯỢC ĐÓNG BĂNG VÀO DB (`config_versions.config_agent`) chứ không
suy lại lúc đọc: các hàng `config_versions` là BẤT BIẾN. Suy lại nghĩa là sửa hàm
này sẽ làm một hàng cũ ĐỔI NGHĨA — đúng thứ mà `REVOKE UPDATE, DELETE` của 0200
tồn tại để chặn.

Hợp đồng: `odyssey-agent/docs/handoff/spec.md §4` + spec v3 (docs/superpowers/specs/
2026-08-05-config-shape-v3-agent-render-design.md §3).
"""

from portal.modules.config.bundle import cau_tu_choi
from portal.modules.config.contracts import ConfigPayload

SCHEMA_VERSION_AGENT = 3
"""Phải khớp `schema_version` mà agent chấp nhận. Agent TỪ CHỐI khởi động nếu lệch."""

TOOL_LOI = frozenset({"update_customer", "kb_search", "find_project", "escalate"})
"""4 tool lõi. KHÔNG liệt kê trong `tools.enabled` — agent luôn tự union chúng vào
(`spec.md §4.3`), nên gửi kèm là dư và làm hai bên có hai nguồn cho cùng một sự thật."""


def sang_config_agent(cfg: ConfigPayload) -> dict:
    """`ConfigPayload` → dict §4 v3. Tất định, không I/O."""
    dt, pv = cfg.danh_tinh, cfg.pham_vi
    return {
        "schema_version": SCHEMA_VERSION_AGENT,
        "identity": {
            "agent_name": dt.ten_agent,
            "brand": dt.ten_thuong_hieu,
            "honorific_self": dt.tu_xung,
            "honorific_customer": dt.goi_khach,
            "greeting": dt.loi_chao,
        },
        "scope": {
            "does": pv.lam_gi,
            "does_not": pv.khong_lam_gi,
            # Gọi lại helper của bundle: đường bundle và đường db phải nói CÙNG một
            # câu từ chối, kể cả khi tenant để ô rỗng.
            "refusal": cau_tu_choi(cfg),
            "handoff_departments": [{"name": pb.ten, "when": pb.khi_nao} for pb in pv.phong_ban],
        },
        "voice": {"tone": cfg.giong.giong_dieu, "length": cfg.giong.do_dai},
        "tools": {
            "enabled": sorted(set(cfg.tools.enabled) - TOOL_LOI),
            # Hai trường dưới chưa có ô trên form — phát mặc định, không phải hồi quy
            # vì Portal chưa từng có chúng. Thêm ô là việc của M5.
            "feng_shui": False,
            "media_channel": "noblex_app",
        },
        "data_source": "pg_kb",
    }
```

- [ ] **Step 4: Chạy test — phải xanh**

Run: `uv run pytest tests/modules/config/test_config_agent.py -v`
Expected: PASS (mọi test, gồm 12 case parametrize)

- [ ] **Step 5: Commit**

```bash
make lint
git add src/portal/modules/config/config_agent.py tests/modules/config/test_config_agent.py
git commit -m "feat(config): sang_config_agent() — dịch payload sang shape §4 v3 + cổng chống rơi trường"
```

---

### Task 4: Migration `0908` + lưu `config_agent` lúc publish

**Files:**
- Create: `P/migrations/versions/0908_config_agent.py`
- Modify: `P/src/portal/modules/config/repo.py` (`them_version`)
- Modify: `P/src/portal/modules/config/service.py` (`publish`)
- Modify: `P/src/portal/modules/config/router.py` (409 `DRAFT_SCHEMA_CU`, `TrangThaiOut.schemaVersionLive`)
- Test: `P/tests/modules/agent_seam/test_config_agent_qua_view.py` (mới)

**Interfaces:**
- Consumes: Task 3 (`sang_config_agent`, `SCHEMA_VERSION_AGENT`)
- Produces: cột `control.config_versions.config_agent jsonb` · cột `control.agent_heartbeats.skeleton_sha text` · view `agent_api.agent_published_config(tenant_id, version, schema_version, config)` · `repo.them_version(..., config_agent: dict)`

- [ ] **Step 1: Viết test đỏ**

```python
# P/tests/modules/agent_seam/test_config_agent_qua_view.py
"""Agent đọc được ĐÚNG hình dạng §4 qua view, không phải payload nội bộ.

Test này là bản đối xứng của `test_bam_ap_dung_agent_doc_duoc.py` — cái đó khẳng
định "ống dẫn đúng thứ Portal ghi", cái này khẳng định "thứ trong ống đúng hình
dạng agent đọc". Thiếu cái thứ hai là chỗ con bug 9/9-trường-mất đã sống.

Đọc bằng `odyssey_agent`, KHÔNG bằng fixture `pool` (là `portal_migrator`, superuser
trong container test nên đọc được view kể cả khi GRANT bị gỡ) — cùng lý lẽ đã ghi ở
`test_bam_ap_dung_agent_doc_duoc.py:41-46`.
"""

import asyncpg
import pytest

from portal.core.db.pool import create_pool
from portal.core.db.session import tenant_conn
from tests.conftest import ODYSSEY_AGENT_PASSWORD, dsn_as
from tests.modules.config.conftest import PAYLOAD_HOP_LE

pytestmark = pytest.mark.integration


@pytest.fixture
async def agent_pool(pg_dsn: str):
    p = await create_pool(dsn_as(pg_dsn, "odyssey_agent", ODYSSEY_AGENT_PASSWORD), min_size=1, max_size=2)
    yield p
    await p.close()


async def test_view_lo_shape_4_khong_lo_payload(client_cfg, workspace_cfg, agent_pool: asyncpg.Pool):
    payload = {
        **PAYLOAD_HOP_LE,
        "danh_tinh": {
            "ten_agent": "Mai", "ten_thuong_hieu": "An Phú Land",
            "tu_xung": "em", "goi_khach": "anh/chị", "loi_chao": "",
        },
        "pham_vi": {"phong_ban": [{"ten": "Phòng kinh doanh", "khi_nao": "Khách hỏi giá riêng"}]},
        "giong": {"giong_dieu": "lich_su", "do_dai": "chi_tiet"},
    }
    assert (await client_cfg.put("/api/v1/config/draft", json=payload)).status_code == 200
    assert (await client_cfg.post("/api/v1/config/publish", json={})).status_code == 200

    async with tenant_conn(agent_pool, workspace_cfg) as conn:
        row = await conn.fetchrow("SELECT version, schema_version, config FROM agent_api.agent_published_config")

    cfg = row["config"]
    assert row["schema_version"] == 3
    assert set(cfg) == {"schema_version", "identity", "scope", "voice", "tools", "data_source"}
    assert "danh_tinh" not in cfg, "view còn lộ payload nội bộ"
    assert cfg["identity"]["agent_name"] == "Mai"
    assert cfg["identity"]["brand"] == "An Phú Land"
    assert cfg["identity"]["honorific_self"] == "em"
    assert cfg["scope"]["handoff_departments"][0]["when"] == "Khách hỏi giá riêng"
    assert cfg["voice"]["tone"] == "lich_su"


async def test_ban_nhap_schema_cu_bi_tu_choi_409(client_cfg, workspace_cfg, pool: asyncpg.Pool):
    await client_cfg.put("/api/v1/config/draft", json=PAYLOAD_HOP_LE)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE control.config_drafts SET payload = payload || '{\"schema_version\": 2}'::jsonb "
            "WHERE tenant_id = $1",
            workspace_cfg,
        )
    r = await client_cfg.post("/api/v1/config/publish", json={})
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "DRAFT_SCHEMA_CU"
```

> ⚠️ Fixture đúng là `client_cfg` · `workspace_cfg` · `pg_dsn` · `pool` (khai ở `tests/conftest.py` và `tests/modules/config/conftest.py`, re-export qua `tests/modules/agent_seam/conftest.py`). **Không** có `client_owner`/`conn_agent`/`conn_migrator` — đừng gọi chúng. `workspace_cfg` trả tenant id `cf_anphu`, không phải `anphu`.

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/agent_seam/test_config_agent_qua_view.py -v`
Expected: FAIL — `UndefinedColumnError: column "schema_version" does not exist`

- [ ] **Step 3: Viết migration**

```python
# P/migrations/versions/0908_config_agent.py
"""config_versions.config_agent + view lộ shape §4 — agent tự render prompt

`config_agent` NULLABLE có chủ đích: các hàng `config_versions` là BẤT BIẾN (0200
`REVOKE UPDATE, DELETE`), nên KHÔNG backfill. Hàng v2 cũ giữ NULL, và view lộ
`schema_version` để agent báo được lỗi chính xác ("đang live ở v2, publish lại")
thay vì một `no published config` chung chung.

`schema_version` đọc từ `payload` chứ KHÔNG thêm cột: nó đã là trường bắt buộc
trong payload từ hàng đầu tiên (contracts.py), thêm cột là bản sao thứ hai của
một sự thật.
"""

from alembic import op

revision = "0908_config_agent"
down_revision = "0907_view_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE control.config_versions ADD COLUMN config_agent jsonb")
    op.execute("ALTER TABLE control.agent_heartbeats ADD COLUMN skeleton_sha text")
    # Bất biến ở TẦNG DB, không ở signature: một hàng schema_version >= 3 mà thiếu
    # `config_agent` là một hàng mà agent đọc ra cấu hình RỖNG — đúng lớp bug fail-silent
    # mà cả plan này tồn tại để diệt. Đặt ở CHECK thì không caller nào quên được.
    # Hàng cũ (schema_version <= 2, hoặc payload không khai) cho NULL ⇒ CHECK ra NULL
    # ⇒ Postgres nhận, nên không phá seed raw-INSERT nào.
    op.execute(
        """
        ALTER TABLE control.config_versions
          ADD CONSTRAINT config_versions_config_agent_tu_v3
          CHECK (config_agent IS NOT NULL OR (payload->>'schema_version')::int < 3)
        """
    )
    # ⚠️ `schema_version` PHẢI ở CUỐI. Chèn vào giữa làm Postgres coi là ĐỔI TÊN cột thứ 3
    # và từ chối: `cannot change name of view column "config" to "schema_version"`.
    # `CREATE OR REPLACE VIEW` chỉ cho thêm cột ở cuối.
    op.execute(
        """
        CREATE OR REPLACE VIEW agent_api.agent_published_config AS
        SELECT v.tenant_id,
               v.version,
               v.config_agent                      AS config,
               (v.payload->>'schema_version')::int AS schema_version
          FROM control.config_versions v
          JOIN control.config_live    l ON l.tenant_id = v.tenant_id AND l.version = v.version
         WHERE v.tenant_id = portal.current_tenant()
        """
    )


def downgrade() -> None:
    # DROP + CREATE, KHÔNG `CREATE OR REPLACE`: rút 4 cột về 3 ném
    # `cannot drop columns from view`. Và `DROP` xoá ACL nên phải GRANT lại tường minh
    # (nguyên văn grant của 0904 — grant duy nhất trên view này).
    #
    # ⚠️ ĐÂY LÀ CỬA MỘT CHIỀU: 0200 `REVOKE UPDATE` trên `config_versions` nên sau khi
    # drop cột, upgrade lại KHÔNG điền lại `config_agent` cho version cũ được — mọi tenant
    # phải publish một version mới. Chấp nhận được vì sau downgrade agent fail LOUD
    # (`SELECT ... schema_version` nổ `UndefinedColumn`), không fail silent.
    op.execute("DROP VIEW agent_api.agent_published_config")
    op.execute(
        """
        CREATE VIEW agent_api.agent_published_config AS
        SELECT v.tenant_id, v.version, v.payload AS config
          FROM control.config_versions v
          JOIN control.config_live    l ON l.tenant_id = v.tenant_id AND l.version = v.version
         WHERE v.tenant_id = portal.current_tenant()
        """
    )
    op.execute("GRANT SELECT ON agent_api.agent_published_config TO agent_all")
    op.execute("ALTER TABLE control.config_versions DROP CONSTRAINT config_versions_config_agent_tu_v3")
    op.execute("ALTER TABLE control.agent_heartbeats DROP COLUMN skeleton_sha")
    op.execute("ALTER TABLE control.config_versions DROP COLUMN config_agent")
```

- [ ] **Step 4: Áp migration**

Run: `make migrate && docker exec odyssey-portal-backend-postgres-1 psql -U portal_migrator -d portal -c "\d+ agent_api.agent_published_config"`
Expected: view có 4 cột `tenant_id, version, schema_version, config`

- [ ] **Step 5: Nối `config_agent` vào publish**

Trong `repo.py::them_version`, thêm tham số `config_agent: dict` và đưa vào câu `INSERT` (cột `config_agent`, giá trị `json.dumps(config_agent)`).

Trong `service.py::publish`, ngay sau dòng `cfg = ConfigPayload.model_validate(payload)` thêm:

```python
    from portal.modules.config.config_agent import sang_config_agent

    config_agent = sang_config_agent(cfg)   # hàm thuần — tính TRƯỚC transaction
```

và truyền `config_agent=config_agent` vào `repo.them_version(...)` bên trong `async with conn.transaction():`.

⚠️ **Hai cái bẫy phải xử lý cùng lúc ở bước này** — cả hai đã được xác minh trên code hiện tại, đừng bỏ:

**(a) `schema_version` KHÔNG có validator nào buộc nó bằng 3.** `ConfigPayload.schema_version: int` là int trần, nên một bản nháp `{"schema_version": 2}` mang trường v3 vẫn validate **thành công** — 409 không thể là hệ quả phụ của validation, phải kiểm tường minh:

```python
class BanNhapSchemaCu(Exception):
    """Bản nháp thuộc schema cũ hơn hiện tại. Router dịch thành 409 DRAFT_SCHEMA_CU."""


# trong xuat_ban_ban_nhap(), NGAY SAU khi đọc bản nháp và TRƯỚC publish():
if nhap.payload.get("schema_version") != SCHEMA_VERSION_HIEN_TAI:
    raise BanNhapSchemaCu
```

**(b) `publish()` sẽ NỔ trên version cũ.** Dòng `truong_da_doi(cfg, ConfigPayload.model_validate(truoc.payload) if truoc else None)` validate payload của **version trước**. Với một hàng v2 (có `xung_ho`, không có `tu_xung`) thì `extra="forbid"` ném `ValidationError` ⇒ mọi publish tiếp theo của tenant đó trả 500. Đây là hồi quy chắc chắn xảy ra, không phải giả thiết: tenant `anphu` trên máy dev đang có 3 hàng như vậy. Sửa cho dung thứ:

```python
    truoc = await repo.version_moi_nhat(conn, tenant_id)
    cu = None
    if truoc is not None:
        try:
            cu = ConfigPayload.model_validate(truoc.payload)
        except ValidationError:
            # Version trước thuộc schema cũ — không diff theo trường được, và đó là
            # đúng: "trường nào đã đổi" chỉ có nghĩa giữa hai bản CÙNG hình dạng.
            # Coi như không có bản trước (BR15 nhận danh sách rỗng), KHÔNG nổ 500.
            cu = None
    da_doi = truong_da_doi(cfg, cu)
```

kèm `from pydantic import ValidationError` ở đầu file.

- [ ] **Step 6: Nối 409 + `schemaVersionLive` vào router**

```python
def _ban_nhap_schema_cu() -> loi.LoiPortal:
    return loi.LoiPortal(
        "DRAFT_SCHEMA_CU",
        409,
        "Bản nháp thuộc schema cũ — mở màn Agent & Kênh, kiểm hai ô xưng hô rồi Lưu lại",
    )
```

Bắt `service.BanNhapSchemaCu` trong `xuat_ban()` và `raise _ban_nhap_schema_cu()`. Thêm `schemaVersionLive: int | None` vào `TrangThaiOut`, đọc từ `payload->>'schema_version'` của version đang live.

- [ ] **Step 7: Chạy test — phải xanh**

Run: `uv run pytest tests/modules/agent_seam tests/modules/config -v`
Expected: PASS

- [ ] **Step 8: Sửa hai docstring đã thành sai**

Hai câu này mô tả một kiến trúc không còn đúng. Để lại là lặp đúng lỗi mà spec §1 ghi nhận:
`contracts.py:10-15` vẫn khẳng định "không phải hợp đồng với agent" suốt từ khi `0904` phá tiền đề đó,
và không ai quay lại sửa.

`src/portal/modules/config/contracts.py:10-15` — câu *"đây KHÔNG phải hợp đồng với agent. Hợp đồng với
agent là `manifest.toml` và các tệp persona"*. Thay bằng:

```
VÌ SAO TÊN TRƯỜNG TIẾNG VIỆT: đây là hợp đồng giữa portal và MÀN HÌNH của nó, và
toàn bộ nghiệp vụ ở đây là tiếng Việt. Nó KHÔNG phải hợp đồng với agent — nhưng
lưu ý: từ `0908`, agent đọc `config_versions.config_agent`, tức đầu ra của
`config_agent.sang_config_agent()` chứ không phải payload này. Đổi payload này mà
quên cập nhật hàm dịch thì `tests/modules/config/test_config_agent.py` đỏ.
```

`src/portal/modules/config/service.py::tro_lai()` — câu *"quay lui trỏ vào ĐÚNG NHỮNG BYTE đã phục vụ"*.
Thêm ngay sau nó:

```
⚠️ Câu trên chỉ còn đúng cho ĐƯỜNG BUNDLE. Ở db-mode (agent tự render từ
`config_agent` + skeleton trên disk của nó), quay lui trả đúng CONFIG đã phục vụ;
prompt thực tế phụ thuộc skeleton của bản agent đang deploy. Cặp
`(version, agent_heartbeats.skeleton_sha)` là thứ truy được prompt nào đã chạy.
```

- [ ] **Step 9: Commit**

```bash
make lint
git add migrations/versions/0908_config_agent.py src/portal/modules/config tests/modules/agent_seam
git commit -m "feat(config): migration 0908 — lưu config_agent, view lộ shape §4 + schema_version"
```

---

### Task 5: Mẫu vàng `contracts/agent-config.json`

**Files:**
- Modify: `P/scripts/gen_contracts.py` (thêm `noi_dung_agent_config()`)
- Create: `P/contracts/agent-config.json` (sinh, không viết tay)
- Modify: `P/contracts/README.md` (thêm một dòng về file mới)
- Modify: `P/tests/api/test_contracts.py`

**Interfaces:**
- Consumes: Task 3 (`sang_config_agent`), Task 2 (`payload_mac_dinh`)
- Produces: `contracts/agent-config.json` — file mà repo agent copy sang và assert trong CI của nó (Plan B Task 4)

- [ ] **Step 1: Viết test đỏ**

```python
# thêm vào P/tests/api/test_contracts.py
def test_agent_config_json_khop_nguon():
    """Quên `make contracts` sau khi sửa sang_config_agent() ⇒ đỏ.

    Đây là nửa Portal của cổng hợp đồng hai repo. Nửa kia ở repo agent nạp đúng
    file này vào `parse_config()` và assert không trường nào rơi về mặc định.
    """
    from scripts.gen_contracts import noi_dung_agent_config

    tren_dia = (CONTRACTS / "agent-config.json").read_text(encoding="utf-8")
    assert tren_dia == noi_dung_agent_config()
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/api/test_contracts.py::test_agent_config_json_khop_nguon -v`
Expected: FAIL — `ImportError: cannot import name 'noi_dung_agent_config'`

- [ ] **Step 3: Thêm hàm sinh**

```python
# thêm vào P/scripts/gen_contracts.py
def noi_dung_agent_config() -> str:
    """Mẫu vàng của hợp đồng Portal→Agent.

    Sinh từ `payload_mac_dinh()` đi qua `sang_config_agent()` — tức nó luôn là đầu
    ra THẬT của đường publish, không phải một ví dụ viết tay có thể lệch.

    Repo agent copy file này và assert `parse_config()` đọc được mọi trường mà
    không rơi về mặc định. Đó là cổng duy nhất chạm cả hai đầu của seam.

    ⚠️ MỌI GIÁ TRỊ Ở ĐÂY PHẢI KHÁC MẶC ĐỊNH PHÍA AGENT. Nếu một giá trị trùng mặc
    định của `parse_config()` thì với trường đó cổng KHÔNG THỂ ĐỎ: đọc đúng và rơi
    về mặc định cho ra cùng kết quả. Đừng dùng `payload_mac_dinh()` trần — mặc định
    của Portal và mặc định của agent trùng nhau ở `tu_xung`/`goi_khach`/`giong`
    (đo được 2026-08-05: cả bốn trùng byte-for-byte).

    BA TRƯỜNG HÔM NAY KHÔNG THỂ ĐO ĐƯỢC, và đó là hạn chế đã biết chứ không phải
    sơ suất: `data_source` (hằng `"pg_kb"` trong `sang_config_agent`), `media_channel`
    và `feng_shui` (Portal chưa có ô trên form — việc của M5). Cả ba trùng mặc định
    phía agent vì cấu trúc, không sửa được bằng fixture.
    """
    from portal.modules.config.config_agent import sang_config_agent
    from portal.modules.config.contracts import Giong, payload_mac_dinh

    cfg = payload_mac_dinh("An Phú Land")
    cfg = cfg.model_copy(
        update={
            "danh_tinh": cfg.danh_tinh.model_copy(
                update={
                    "ten_agent": "Mai",
                    "loi_chao": "Dạ em Mai bên An Phú Land ạ.",
                    # KHÁC mặc định ("em" / "anh/chị") — xem cảnh báo ở docstring
                    "tu_xung": "con",
                    "goi_khach": "quý khách",
                }
            ),
            # KHÁC mặc định ("than_thien" / "trung_binh")
            "giong": Giong(giong_dieu="ngan_gon", do_dai="chi_tiet"),
        }
    )
    return json.dumps(sang_config_agent(cfg), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
```

và trong `main()`, sau khối `tools.json`:

```python
    dich_agent = CONTRACTS / "agent-config.json"
    dich_agent.write_text(noi_dung_agent_config(), encoding="utf-8")
    print(f"đã sinh {dich_agent.relative_to(GOC)}")
```

- [ ] **Step 4: Sinh và chạy test**

Run: `make contracts && uv run pytest tests/api/test_contracts.py -v`
Expected: PASS. Mở `contracts/agent-config.json` và kiểm bằng mắt: có `identity.agent_name = "Mai"`, `scope.handoff_departments` là list, `voice.tone`, và **không** có khoá tiếng Việt nào.

- [ ] **Step 5: Ghi một dòng vào `contracts/README.md`**

Thêm `agent-config.json` vào bảng liệt kê, cột "ai đọc" ghi: `repo odyssey-agent (test hợp đồng)`. Nói rõ nó được **copy tay** sang repo kia, cùng khoảng hở mà README đã thừa nhận với `actions.json`.

- [ ] **Step 6: Commit**

```bash
make lint
git add scripts/gen_contracts.py contracts/ tests/api/test_contracts.py
git commit -m "feat(contracts): mẫu vàng agent-config.json — cổng hợp đồng Portal→Agent"
```

---

### Task 6: Frontend — hai ô xưng hô

**Files:**
- Modify: `F/src/features/agent/api.ts:44` (type payload), `:75` (type xem trước)
- Modify: `F/src/features/agent/components/AgentStudio.tsx:218-220`
- Modify: `F/src/lib/msw/handlers.ts:47,788`
- Modify: `F/contracts/tools.json` — **copy lại từ `P/contracts/tools.json`** sau Task 1
- Modify: `F/src/lib/tools.ts` — bỏ `get_project_financial` (2 chỗ: `MUOI_HAI_KY_NANG` và `PHU_THUOC`), thêm `get_document` với `nhan` + `PHU_THUOC: ['find_project']` khớp `tools.json`
- Test: `F/tests/agent-studio.test.tsx` (thêm case; tạo file nếu chưa có)
- Test: `F/tests/tools-parity.test.ts` — **đã tồn tại**, sẽ đỏ tới khi hai file trên khớp. Đó là cổng làm đúng việc, không phải test hỏng

**Interfaces:**
- Consumes: Task 2 (tên trường `tu_xung`/`goi_khach`, `tuXung`/`goiKhach`)
- Produces: —

- [ ] **Step 1: Tạo nhánh**

```bash
cd ../odyssey-portal-frontend && git checkout -b feat/config-shape-v3
```

- [ ] **Step 2: Viết test đỏ**

```tsx
// F/tests/agent-studio.test.tsx
it('có hai ô xưng hô riêng, và câu mẫu đổi theo giá trị đang gõ', async () => {
  render(<AgentStudio />)
  const tuXung = await screen.findByLabelText('Agent tự xưng là gì?')
  const goiKhach = screen.getByLabelText('Agent gọi khách là gì?')

  expect(tuXung).toHaveValue('em')
  expect(goiKhach).toHaveValue('anh/chị')

  await userEvent.clear(tuXung)
  await userEvent.type(tuXung, 'mình')
  expect(screen.getByTestId('cau-mau')).toHaveTextContent(
    'Dạ mình xin phép tư vấn cho anh/chị ạ.',
  )
})
```

- [ ] **Step 3: Chạy để thấy đỏ**

Run: `npx vitest run tests/agent-studio.test.tsx`
Expected: FAIL — không tìm thấy label `Agent tự xưng là gì?`

- [ ] **Step 4: Sửa type ở `api.ts`**

`:44` → `danh_tinh: { ten_agent: string; ten_thuong_hieu: string; tu_xung: string; goi_khach: string; loi_chao: string }`
`:75` → thay `xungHo: string` bằng `tuXung: string` và `goiKhach: string`

- [ ] **Step 5: Sửa `AgentStudio.tsx`**

Thay khối `<Input>` một ô ở `:218-220` bằng hai ô + câu mẫu:

```tsx
<Input
  nhan="Agent tự xưng là gì?"
  giaTri={form.danh_tinh.tu_xung}
  doi={(v) => sua((c) => ({ ...c, danh_tinh: { ...c.danh_tinh, tu_xung: v } }))}
/>
<Input
  nhan="Agent gọi khách là gì?"
  giaTri={form.danh_tinh.goi_khach}
  doi={(v) => sua((c) => ({ ...c, danh_tinh: { ...c.danh_tinh, goi_khach: v } }))}
/>
<p data-testid="cau-mau" className="mt-1.5 text-[12.5px] text-muted">
  {`Dạ ${form.danh_tinh.tu_xung} xin phép tư vấn cho ${form.danh_tinh.goi_khach} ạ.`}
</p>
```

Câu mẫu là **hằng số FE**, không vào payload — nó chỉ để tenant thấy hệ quả của hai ô.

- [ ] **Step 6: Sửa MSW**

`handlers.ts:47` → `tu_xung: 'em', goi_khach: 'anh/chị',`
`handlers.ts:788` → `tuXung: 'em', goiKhach: 'anh/chị',`

- [ ] **Step 7: Chạy test + lint**

Run: `npx vitest run && make lint`
Expected: PASS. `grep -rn 'xung_ho\|xungHo' src tests` phải ra 0 kết quả.

- [ ] **Step 8: Commit**

```bash
git add src/features/agent src/lib/msw/handlers.ts tests/agent-studio.test.tsx
git commit -m "feat(m5-fe)!: tách xưng hô thành hai ô có nhãn hỏi thẳng + câu mẫu"
```

---

### Task 7: Câu từ chối mặc định phải theo xưng hô của tenant

> **Task này mở phạm vi ra ngoài 6 task đầu, có chủ đích, người dùng chốt 2026-08-05.**
> Nó phát hiện ra khi mẫu vàng ở Task 5 đổi xưng hô: `bundle.cau_tu_choi()` hardcode
> "em"/"anh/chị", nên một tenant đặt `tu_xung="con"` nhận được một agent tự mâu thuẫn
> **trước khách hàng thật** — SOUL.md nói tự xưng "con", RULES.md nói "Em xin phép
> chuyển anh/chị". Sửa ngay vì mẫu vàng chưa được copy sang repo agent, nên đây là
> điểm rẻ nhất; sửa sau là phải copy lại artefact và chạy lại cổng bên đó.

**Files:**
- Modify: `P/src/portal/modules/config/bundle.py` — `cau_tu_choi()`
- Modify: `P/tests/modules/config/test_bundle.py` — thêm test đơn vị
- Modify: `P/tests/modules/config/test_config_agent.py:98-102` — mạnh hoá test có sẵn
- Modify: `P/scripts/gen_contracts.py` — sửa caveat "ba trường" thành "năm trường"
- Modify: `P/contracts/README.md` — cùng sửa caveat
- Modify: `P/contracts/agent-config.json` — sinh lại bằng `make contracts`

**Interfaces:**
- Consumes: Task 2 (`danh_tinh.tu_xung`/`goi_khach`), Task 5 (`noi_dung_agent_config`)
- Produces: `cau_tu_choi(cfg)` nội suy xưng hô; mẫu vàng có `scope.refusal` nhất quán với `identity.honorific_*`

- [ ] **Step 1: Viết test đỏ**

```python
# thêm vào P/tests/modules/config/test_bundle.py
def test_cau_tu_choi_sinh_theo_xung_ho_cua_tenant():
    """Câu sinh tự động phải dùng ĐÚNG xưng hô tenant đặt.

    Hardcode "em"/"anh/chị" ở đây nghĩa là một tenant đặt `tu_xung="con"` sẽ có
    SOUL.md nói tự xưng "con" và RULES.md nói "Em xin phép chuyển anh/chị" — agent
    tự mâu thuẫn trong một câu nói với khách hàng thật.
    """
    cfg = payload_mac_dinh("An Phú Land")
    cfg = cfg.model_copy(
        update={"danh_tinh": cfg.danh_tinh.model_copy(update={"tu_xung": "con", "goi_khach": "quý khách"})}
    )
    cau = cau_tu_choi(cfg)
    assert "con" in cau
    assert "quý khách" in cau
    assert "anh/chị" not in cau
    assert "Em " not in cau and "của em" not in cau


def test_cau_tu_choi_tenant_dien_thi_tra_nguyen_van():
    """Tenant tự điền thì KHÔNG can thiệp — kể cả khi họ dùng xưng hô khác."""
    cfg = payload_mac_dinh("An Phú Land")
    cfg = cfg.model_copy(update={"pham_vi": cfg.pham_vi.model_copy(update={"cau_tu_choi": "Dạ mời anh gọi 1900."})})
    assert cau_tu_choi(cfg) == "Dạ mời anh gọi 1900."
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/config/test_bundle.py -v -k cau_tu_choi`
Expected: FAIL — `assert "anh/chị" not in cau` (câu hiện tại hardcode "anh/chị")

- [ ] **Step 3: Sửa `cau_tu_choi()`**

```python
    dt = cfg.danh_tinh
    return (
        f"Việc này nằm ngoài phạm vi tư vấn của {dt.tu_xung} tại {dt.ten_thuong_hieu}. "
        f"{dt.tu_xung.capitalize()} xin phép chuyển {dt.goi_khach} tới bộ phận phụ trách."
    )
```

`.capitalize()` chỉ cho từ đầu câu: `"con"` → `"Con"`, `"em"` → `"Em"`, `"chúng em"` → `"Chúng em"`. Cập nhật docstring của hàm: nói rõ câu sinh ra **theo xưng hô tenant đặt**, và vì sao (một câu hardcode xưng hô là một agent tự mâu thuẫn).

- [ ] **Step 4: Mạnh hoá test có sẵn**

`tests/modules/config/test_config_agent.py:98-102` hiện chỉ assert `"An Phú Land" in out["scope"]["refusal"]`. Thêm hai assert nữa vào đúng test đó: `refusal` phải chứa `tu_xung` và `goi_khach` của cfg, để cổng ở tầng `sang_config_agent` cũng bắt được hồi quy này.

- [ ] **Step 5: Sửa caveat cho đủ**

Trong docstring `noi_dung_agent_config()` (`scripts/gen_contracts.py`) và trong `contracts/README.md`: đổi "ba trường không đo được" thành **năm**, và phân biệt hai nguyên nhân khác nhau:
- `data_source` · `media_channel` · `feng_shui` — Portal hardcode hoặc chưa có ô form (việc của M5).
- `voice.tone` · `voice.length` — phía **agent** chưa có field `voice` nào cho tới Plan B Task 1; chọn giá trị gì cũng chưa đo được cho tới lúc đó.

- [ ] **Step 6: Sinh lại mẫu vàng, chạy test**

Run: `make contracts && uv run pytest tests/modules/config tests/api -q && make lint`
Expected: PASS. Kiểm bằng mắt `contracts/agent-config.json`: `scope.refusal` giờ phải nói "con"/"quý khách", nhất quán với `identity.honorific_self`/`honorific_customer`.

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/config/bundle.py tests/modules/config scripts/gen_contracts.py contracts/
git commit -m "fix(config): câu từ chối mặc định theo xưng hô tenant, không hardcode em/anh chị"
```

---

## Nghiệm thu Plan A

- [ ] `cd P && make check` xanh (lint + toàn bộ test)
- [ ] `cd F && make check` xanh
- [ ] `contracts/agent-config.json` tồn tại, không chứa khoá tiếng Việt nào
- [ ] Publish tay một lần rồi đọc view, thấy `schema_version = 3` và `config` đúng 6 khoá §4:

```bash
docker exec odyssey-portal-backend-postgres-1 psql -U portal_migrator -d portal \
  -c "SELECT version, config_agent->'identity'->>'brand' FROM control.config_versions ORDER BY version DESC LIMIT 1;"
```

- [ ] Mở `http://localhost:5273/agent`, thấy hai ô có nhãn hỏi thẳng và câu mẫu đổi theo giá trị gõ vào

**Chưa xong sau Plan A:** agent vẫn chưa đọc được — `parse_config` còn kỳ vọng `schema_version` không tồn tại ở nó và chưa có `voice`/`handoff_departments`. Đó là Plan B.
