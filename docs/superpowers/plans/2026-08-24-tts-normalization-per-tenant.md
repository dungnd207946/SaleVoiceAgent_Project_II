# TTS Normalization Dictionary (per-tenant) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho tenant tự thêm/xoá mục của một từ điển cách đọc TTS trên màn `/agent`, đi theo nhịp «Lưu và áp dụng», và cho agent áp từ điển đó lên trên bộ nền của platform.

**Architecture:** Thêm một trường `tts_normalization: list[NormalizationEntry]` vào `ConfigPayload`; lúc publish nó xuống `tenant_data.agent_config.tts_normalization` dạng **object** `{term: read_as}`. Agent đọc cột đó cùng lượt với các cột phẳng khác, rồi áp nó thành **một pass regex riêng** chèn sớm trong `normalize_for_voice()` — trước `_CODE_RE` — nên lớp tenant thắng cả hai map nền. Giao diện là một khu preview 3 dòng trên khối «Rào chắn», mở dialog để xem/sửa đầy đủ.

**Tech Stack:** Python 3.13 · pydantic v2 · asyncpg · alembic · FastAPI · pytest — React 19 · TanStack Router/Query · vitest · MSW · Tailwind

## Global Constraints

- **`SCHEMA_VERSION_HIEN_TAI` giữ nguyên `3`.** Không nâng lên 4. Agent từ chối khởi động khi `SCHEMA_VERSION_AGENT` lệch.
- **Định danh mới viết tiếng Anh.** Tiếng Việt chỉ ở comment, docstring và tên test. Các khoá payload cũ (`danh_tinh`, `pham_vi`, `giong`) giữ nguyên, không đổi.
- **Ít comment.** Chỉ chú thích chỗ mà lý lẽ không đọc ra được từ code.
- **Commit message tiếng Anh, KHÔNG có dòng `Co-Authored-By`.**
- **Trần:** `term` ≤ 60 ký tự · `read_as` ≤ 200 ký tự · tối đa **200 mục**.
- **Cột DB là OBJECT (`jsonb_typeof = 'object'`)**, khác `departments`/`skills` là mảng.
- **Thứ tự deploy một chiều: migration portal TRƯỚC, agent SAU.**
- Ba repo: `odyssey-portal-backend` (chính) · `odyssey-portal-frontend` · `odyssey-agent`. Không job CI nào so hai bên — mọi hợp đồng copy tay.
- Spec: `docs/superpowers/specs/2026-08-24-tts-normalization-per-tenant-design.md`

## File Structure

**`odyssey-portal-backend`**
| File | Trách nhiệm |
|---|---|
`src/portal/modules/config/contracts.py` | thêm `NormalizationEntry` + trường `tts_normalization` + 4 phép validate |
`migrations/versions/0954_agent_config_tts_normalization.py` | cột jsonb object trên `tenant_data.agent_config` |
`src/portal/modules/config/agent_config.py` | list → object ở `hang_phang()`, thêm tham số vào `_SQL_LUU`/`luu()` |
`src/portal/modules/config/config_agent.py` | `voice.tts_normalization` cho hợp đồng agent |
`src/portal/modules/config/bundle.py` | khoá tương ứng trong `persona/config.json` (đường legacy) |
`contracts/agent-config.json` | sinh lại bằng `make contracts` |
`tests/modules/config/test_tts_normalization.py` | **mới** — 8 bài hợp đồng, không cần Docker |
`tests/modules/config/test_agent_config.py` | sửa bài so dict tuyệt đối + 3 bài mới |
`tests/modules/config/test_config_agent.py` · `test_bundle.py` | 1 bài mỗi file |

**`odyssey-portal-frontend`**
| File | Trách nhiệm |
|---|---|
`src/features/agent/api.ts` | kiểu `NormalizationEntry` + trường trong `ConfigPayload` |
`src/features/agent/useBanNhap.ts` | mặc định `[]` trong `chuanHoa()` |
`src/features/agent/components/Normalization.tsx` | **mới** — `NormalizationPreview` |
`src/features/agent/components/NormalizationDialog.tsx` | **mới** — bảng đầy đủ, sửa được |
`src/features/agent/components/CauHinhChung.tsx` · `TomTatCauHinh.tsx` | gắn khu mới trên `<RaoChan />` |
`tests/tts-normalization.test.tsx` | **mới** |

**`odyssey-agent`**
| File | Trách nhiệm |
|---|---|
`src/noble_agent/storage/agent_config_store.py` | đọc cột mới, giải mã object đúng cách |
`src/noble_agent/agent/agent_config.py` | `AgentConfig.tts_normalization` |
`src/noble_agent/voice/tts/_normalize.py` | `set_tenant_overrides()` + pass chèn sớm |
`src/noble_agent/agent/facade.py` | gọi setter sau `parse_config` |
`tests/unit/voice/test_normalize_tenant_overrides.py` | **mới** |

---

### Task 1: Hợp đồng `tts_normalization` (portal)

**Files:**
- Modify: `src/portal/modules/config/contracts.py`
- Test: `tests/modules/config/test_tts_normalization.py` (create)

**Interfaces:**
- Consumes: `_Nghiem` (base `extra="forbid"`), `ConfigPayload` — cả hai đã có trong file.
- Produces: `NormalizationEntry` với thuộc tính `.term: str`, `.read_as: str`; trường `ConfigPayload.tts_normalization: list[NormalizationEntry]` (mặc định `[]`). Task 2, 3 dùng đúng hai tên đó.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/modules/config/test_tts_normalization.py`:

```python
"""`ConfigPayload.tts_normalization` — từ điển cách đọc TTS của tenant.

Bốn phép validate ở đây đều chặn một lỗi HỎNG IM LẶNG, không phải lỗi thẩm mỹ:
khoá trùng thì JSON lấy giá trị cuối mà không ai biết; khoá có khoảng trắng ở mép
thì `\\b` bên agent không bao giờ khớp và mục đó vô hiệu vĩnh viễn.
"""

import pytest
from pydantic import ValidationError

from portal.modules.config.contracts import ConfigPayload
from tests.modules.config.conftest import PAYLOAD_HOP_LE


def _payload(entries: list[dict]) -> dict:
    return {**PAYLOAD_HOP_LE, "tts_normalization": entries}


def test_mac_dinh_la_danh_sach_rong():
    """Trường THÊM, có default — nên mọi payload v3 cũ vẫn validate được."""
    assert ConfigPayload.model_validate(PAYLOAD_HOP_LE).tts_normalization == []


def test_nhan_muc_hop_le():
    cfg = ConfigPayload.model_validate(
        _payload([{"term": "NCLB", "read_as": "Noble Crystal Long Biên"}])
    )

    assert cfg.tts_normalization[0].term == "NCLB"
    assert cfg.tts_normalization[0].read_as == "Noble Crystal Long Biên"


def test_giu_nguyen_thu_tu_nguoi_dung_nhap():
    cfg = ConfigPayload.model_validate(
        _payload(
            [
                {"term": "SSLC", "read_as": "Sunshine Legend City"},
                {"term": "NCLB", "read_as": "Noble Crystal Long Biên"},
            ]
        )
    )

    assert [e.term for e in cfg.tts_normalization] == ["SSLC", "NCLB"]


def test_tu_choi_khoa_trung_khong_phan_biet_hoa_thuong():
    """`NCLB` và `nclb` là một khoá với người dùng. Hai dòng trông giống nhau cho hai
    kết quả khác nhau là bẫy không đáng bán."""
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(
            _payload(
                [
                    {"term": "NCLB", "read_as": "Noble Crystal Long Biên"},
                    {"term": "nclb", "read_as": "Noble Crystal Long Biên 2"},
                ]
            )
        )


def test_tu_choi_khoang_trang_o_mep():
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(_payload([{"term": " NCLB", "read_as": "Noble"}]))


def test_tu_choi_term_trung_read_as():
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(_payload([{"term": "NCLB", "read_as": "NCLB"}]))


def test_tu_choi_ky_tu_dieu_khien():
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(_payload([{"term": "NC\tLB", "read_as": "Noble"}]))


def test_tu_choi_qua_tran_200_muc():
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(
            _payload([{"term": f"MA{i}", "read_as": f"Mã số {i}"} for i in range(201)])
        )


def test_tu_choi_truong_la_trong_muc():
    """`_Nghiem` chặn trường lạ ở MỌI tầng — một `kind` bị nuốt im lặng là chỗ FE gõ
    sai tên trường mà không ai biết."""
    with pytest.raises(ValidationError):
        ConfigPayload.model_validate(
            _payload([{"term": "NCLB", "read_as": "Noble", "kind": "abbrev"}])
        )
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `cd /home/thanhhai/Desktop/odyssey-portal-backend && uv run pytest tests/modules/config/test_tts_normalization.py -q`
Expected: FAIL — `test_mac_dinh_la_danh_sach_rong` báo `AttributeError: 'ConfigPayload' object has no attribute 'tts_normalization'`, các bài còn lại `ValidationError: extra fields not permitted` (chưa có trường nên `extra="forbid"` từ chối).

- [ ] **Step 3: Thêm hợp đồng**

Trong `src/portal/modules/config/contracts.py`, sửa dòng import pydantic thành:

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
```

Thêm hằng và model NGAY TRƯỚC `class ConfigPayload`:

```python
_KY_TU_DIEU_KHIEN = frozenset(chr(c) for c in range(32)) | {chr(127)}


class NormalizationEntry(_Nghiem):
    """Một mục của từ điển cách đọc TTS. `term` là khoá cần khớp, `read_as` là văn bản thay ra."""

    term: str = Field(min_length=1, max_length=60)
    read_as: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _kiem_muc(self) -> "NormalizationEntry":
        # Khoảng trắng ở mép làm `\b` bên agent không bao giờ khớp — mục vô hiệu, không lỗi.
        if self.term != self.term.strip():
            raise ValueError("term không được có khoảng trắng ở đầu hoặc cuối")
        if self.term == self.read_as:
            raise ValueError("term trùng read_as — mục này không làm gì")
        for ten, gia_tri in (("term", self.term), ("read_as", self.read_as)):
            if any(ch in _KY_TU_DIEU_KHIEN for ch in gia_tri):
                raise ValueError(f"{ten} chứa ký tự điều khiển")
        return self
```

Trong `class ConfigPayload`, thêm trường sau `tools` và một field validator:

```python
    tts_normalization: list[NormalizationEntry] = Field(default_factory=list, max_length=200)
    """Từ điển cách đọc TTS của tenant — lớp CHỒNG LÊN bộ nền trong repo agent, không thay nó.

    Danh sách chứ không phải dict: khoá trùng thành 422 tường minh thay vì bị JSON âm thầm
    lấy giá trị cuối, và thứ tự này là thứ tự người dùng thấy trên bảng.
    """

    @field_validator("tts_normalization")
    @classmethod
    def _khong_trung_term(cls, v: list[NormalizationEntry]) -> list[NormalizationEntry]:
        da_thay: set[str] = set()
        for muc in v:
            khoa = muc.term.casefold()
            if khoa in da_thay:
                raise ValueError(f"term trùng (không phân biệt hoa/thường): {muc.term}")
            da_thay.add(khoa)
        return v
```

- [ ] **Step 4: Chạy để xác nhận xanh**

Run: `uv run pytest tests/modules/config/test_tts_normalization.py -q`
Expected: PASS — 9 passed.

- [ ] **Step 5: Chạy toàn bộ test hợp đồng để chắc không phá gì**

Run: `uv run pytest tests/modules/config -q -m "not integration"`
Expected: PASS. Nếu `test_agent_config.py::test_hang_phang_anh_xa_du_moi_input_cua_form` đỏ thì SAI — Task 1 không đụng `hang_phang()`, bài đó phải còn xanh.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check src tests && uv run ruff format --check src tests
git add src/portal/modules/config/contracts.py tests/modules/config/test_tts_normalization.py
git commit -m "feat(config): add tts_normalization dictionary to ConfigPayload"
```

---

### Task 2: Cột DB + ánh xạ list → object (portal)

**Files:**
- Create: `migrations/versions/0954_agent_config_tts_normalization.py`
- Modify: `src/portal/modules/config/agent_config.py`
- Test: `tests/modules/config/test_agent_config.py`

**Interfaces:**
- Consumes: `NormalizationEntry.term` / `.read_as` và `ConfigPayload.tts_normalization` từ Task 1.
- Produces: khoá `"tts_normalization"` trong dict trả về của `hang_phang()`, giá trị là `dict[str, str]`; cột `tenant_data.agent_config.tts_normalization`.

- [ ] **Step 1: Viết test đỏ (ánh xạ, không cần Docker)**

Trong `tests/modules/config/test_agent_config.py`, thêm khoá vào `PAYLOAD_DAY_DU` — chèn ngay sau dòng `"tools": {...}`:

```python
    "tts_normalization": [
        {"term": "NCLB", "read_as": "Noble Crystal Long Biên"},
        {"term": "SSLC", "read_as": "Sunshine Legend City"},
    ],
```

Sửa `test_hang_phang_anh_xa_du_moi_input_cua_form`: thêm khoá vào dict kỳ vọng, ngay sau `"skills": [...]`:

```python
        "tts_normalization": {
            "NCLB": "Noble Crystal Long Biên",
            "SSLC": "Sunshine Legend City",
        },
```

Thêm hai bài mới sau `test_hang_phang_dung_mac_dinh_khi_form_de_trong`:

```python
def test_hang_phang_doi_danh_sach_thanh_object():
    """Payload là DANH SÁCH (để 422 được khi trùng khoá), cột DB là OBJECT — đó đúng
    hình dạng `{reading, abbrev}` mà agent đang parse từ file nền."""
    cfg = ConfigPayload.model_validate(
        {**PAYLOAD_DAY_DU, "tts_normalization": [{"term": "NPTTL", "read_as": "Noble Palace Tây Thăng Long"}]}
    )

    assert hang_phang(cfg, version=1)["tts_normalization"] == {
        "NPTTL": "Noble Palace Tây Thăng Long"
    }


def test_hang_phang_tu_dien_rong_thanh_object_rong_khong_phai_mang_rong():
    """`{}` chứ không `[]`. Cột có CHECK `jsonb_typeof = 'object'`, nên một `[]` lọt xuống
    đây là lỗi ràng buộc GIỮA giao dịch publish — người bấm nhận 500."""
    h = hang_phang(ConfigPayload.model_validate(PAYLOAD_HOP_LE), version=1)

    assert h["tts_normalization"] == {}
    assert not isinstance(h["tts_normalization"], list)
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/config/test_agent_config.py -q -m "not integration"`
Expected: FAIL — `KeyError: 'tts_normalization'` ở hai bài mới, và bài so dict tuyệt đối đỏ vì dict thật thiếu khoá đó.

- [ ] **Step 3: Viết migration**

Tạo `migrations/versions/0954_agent_config_tts_normalization.py`:

```python
"""tenant_data.agent_config — cột `tts_normalization` (từ điển cách đọc TTS của tenant)

VÌ SAO OBJECT CHỨ KHÔNG PHẢI MẢNG, khác `departments`/`skills`: đó đúng hình dạng
`{term: read_as}` mà `_normalize.py` bên agent đang parse từ file nền, nên phép trộn bên
đó là một dòng thay vì thêm một tầng dịch.

⚠️ HỆ QUẢ Ở REPO AGENT: `agent_config_store._read_from_db` giải mã mọi cột jsonb bằng
`_decode(...) or []`, và `{}` là FALSY trong Python — một từ điển rỗng sẽ thành `[]` rồi
`parse_config` nhận list ở chỗ nó chờ dict. Hai cột jsonb hiện có đều là mảng nên dòng đó
chưa từng sai. Bên agent phải có một tập cột riêng với `or {}`.

KHÔNG REWRITE BẢNG: `DEFAULT` là hằng không volatile, nên Postgres 11+ làm `ADD COLUMN
NOT NULL DEFAULT` ở mức metadata.

KHÔNG CẦN GRANT LẠI: quyền trên `tenant_data.agent_config` cấp ở mức BẢNG, cột mới thừa
hưởng sẵn.

Revision ID: 0954_tts_normalization
Revises: 0953_bu_invites_role_id
"""

from alembic import op

revision = "0954_tts_normalization"
down_revision = "0953_bu_invites_role_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenant_data.agent_config
            ADD COLUMN tts_normalization jsonb NOT NULL DEFAULT '{}'::jsonb
            CONSTRAINT agent_config_tts_normalization_object_check
            CHECK (jsonb_typeof(tts_normalization) = 'object')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_data.agent_config DROP COLUMN tts_normalization")
```

- [ ] **Step 4: Kiểm chỉ có một head**

Run: `uv run pytest tests/unit/test_alembic_mot_head.py -q`
Expected: PASS — 2 passed. Nếu đỏ với `Multiple head revisions` thì `down_revision` sai; head đúng lúc viết plan là `0953_bu_invites_role_id`, kiểm lại bằng `uv run alembic heads`.

- [ ] **Step 5: Sửa `agent_config.py`**

Trong `src/portal/modules/config/agent_config.py`:

Đổi `_SQL_LUU` — thêm cột vào danh sách, thêm `$15::jsonb`, thêm dòng SET:

```python
_SQL_LUU = """
INSERT INTO tenant_data.agent_config (
    tenant_id, name, brand_name, self_pronoun, customer_pronoun, greeting,
    scope_does, scope_does_not, refusal_line, departments,
    tone, reply_length, skills, version, tts_normalization
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11, $12, $13::jsonb, $14, $15::jsonb)
ON CONFLICT (tenant_id) DO UPDATE SET
    name              = excluded.name,
    brand_name        = excluded.brand_name,
    self_pronoun      = excluded.self_pronoun,
    customer_pronoun  = excluded.customer_pronoun,
    greeting          = excluded.greeting,
    scope_does        = excluded.scope_does,
    scope_does_not    = excluded.scope_does_not,
    refusal_line      = excluded.refusal_line,
    departments       = excluded.departments,
    tone              = excluded.tone,
    reply_length      = excluded.reply_length,
    skills            = excluded.skills,
    version           = excluded.version,
    tts_normalization = excluded.tts_normalization,
    updated_at        = now()
"""
```

Trong `hang_phang()`, thêm khoá ngay trước `"version"`:

```python
        # DANH SÁCH -> OBJECT. Trùng khoá đã bị `ConfigPayload` chặn ở 422, nên ở đây
        # không có mục nào bị đè im lặng.
        "tts_normalization": {e.term: e.read_as for e in cfg.tts_normalization},
```

Trong `luu()`, thêm tham số cuối sau `h["version"]`:

```python
        json.dumps(h["tts_normalization"], ensure_ascii=False),
```

- [ ] **Step 6: Chạy test ánh xạ để xác nhận xanh**

Run: `uv run pytest tests/modules/config/test_agent_config.py -q -m "not integration"`
Expected: PASS.

- [ ] **Step 7: Áp migration lên DB dev rồi thêm test đầu-cuối**

```bash
make migrate
```
Expected: `Running upgrade 0953_bu_invites_role_id -> 0954_tts_normalization`.

Thêm assert vào `test_ap_dung_ghi_mot_hang_phang`, ngay sau dòng assert `skills`:

```python
    assert json.loads(h["tts_normalization"]) == {
        "NCLB": "Noble Crystal Long Biên",
        "SSLC": "Sunshine Legend City",
    }
```

- [ ] **Step 8: Chạy test integration**

Run: `uv run pytest tests/modules/config/test_agent_config.py -q`
Expected: PASS toàn bộ. Nếu báo `column "tts_normalization" does not exist` thì `make migrate` chưa chạy trên container test.

- [ ] **Step 9: Kiểm round-trip migration**

```bash
uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: cả hai lệnh thành công, không lỗi.

- [ ] **Step 10: Lint + commit**

```bash
uv run ruff check src tests migrations && uv run ruff format --check src tests migrations
git add migrations/versions/0954_agent_config_tts_normalization.py src/portal/modules/config/agent_config.py tests/modules/config/test_agent_config.py
git commit -m "feat(config): persist tts_normalization on the flat agent_config row"
```

---

### Task 3: Hợp đồng agent + bundle legacy (portal)

**Files:**
- Modify: `src/portal/modules/config/config_agent.py`
- Modify: `src/portal/modules/config/bundle.py:215-221` (hàm `_config_json`)
- Modify: `contracts/agent-config.json` (sinh lại, không sửa tay)
- Test: `tests/modules/config/test_config_agent.py`, `tests/modules/config/test_bundle.py`

**Interfaces:**
- Consumes: `ConfigPayload.tts_normalization` (Task 1).
- Produces: khoá `voice.tts_normalization` trong dict của `sang_config_agent()`; khoá `tts_normalization` trong `persona/config.json` của bundle. Task 6 bên repo agent đọc **cột DB**, không đọc hai thứ này — chúng dành cho hợp đồng và đường legacy.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/modules/config/test_config_agent.py`:

```python
def test_tts_normalization_vao_khoi_voice():
    """Nằm dưới `voice` vì nó là chuyện của tầng đọc thành tiếng, cùng chỗ với tone/length."""
    from portal.modules.config.config_agent import sang_config_agent
    from portal.modules.config.contracts import ConfigPayload
    from tests.modules.config.conftest import PAYLOAD_HOP_LE

    cfg = ConfigPayload.model_validate(
        {**PAYLOAD_HOP_LE, "tts_normalization": [{"term": "NCLB", "read_as": "Noble Crystal Long Biên"}]}
    )

    assert sang_config_agent(cfg)["voice"]["tts_normalization"] == {
        "NCLB": "Noble Crystal Long Biên"
    }


def test_tts_normalization_rong_la_object_rong():
    from portal.modules.config.config_agent import sang_config_agent
    from portal.modules.config.contracts import ConfigPayload
    from tests.modules.config.conftest import PAYLOAD_HOP_LE

    cfg = ConfigPayload.model_validate(PAYLOAD_HOP_LE)

    assert sang_config_agent(cfg)["voice"]["tts_normalization"] == {}
```

Thêm vào `tests/modules/config/test_bundle.py`:

```python
def test_config_json_mang_tts_normalization():
    """Đường bundle (legacy) và đường bảng phẳng phải nói cùng một từ điển — hai đường
    lệch nhau là một tenant đọc đúng ở chế độ này và sai ở chế độ kia."""
    import json

    from portal.modules.config.bundle import render
    from portal.modules.config.contracts import ConfigPayload
    from tests.modules.config.conftest import PAYLOAD_HOP_LE

    cfg = ConfigPayload.model_validate(
        {**PAYLOAD_HOP_LE, "tts_normalization": [{"term": "SSLC", "read_as": "Sunshine Legend City"}]}
    )
    noi_dung = json.loads(render(cfg, "cf_anphu")["persona/config.json"])

    assert noi_dung["tts_normalization"] == {"SSLC": "Sunshine Legend City"}
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/modules/config/test_config_agent.py tests/modules/config/test_bundle.py -q -m "not integration"`
Expected: FAIL — `KeyError: 'tts_normalization'` ở cả ba bài mới.

- [ ] **Step 3: Sửa `config_agent.py`**

Trong `sang_config_agent()`, đổi dòng `voice`:

```python
        "voice": {
            "tone": cfg.giong.giong_dieu,
            "length": cfg.giong.do_dai,
            "tts_normalization": {e.term: e.read_as for e in cfg.tts_normalization},
        },
```

- [ ] **Step 4: Sửa `bundle._config_json()`**

```python
def _config_json(cfg: ConfigPayload) -> bytes:
    noi_dung = {
        "agent_name": cfg.danh_tinh.ten_agent,
        "brand": cfg.danh_tinh.ten_thuong_hieu,
        "tone": cfg.giong.giong_dieu,
        "length": cfg.giong.do_dai,
        "tts_normalization": {e.term: e.read_as for e in cfg.tts_normalization},
    }
    return json.dumps(noi_dung, ensure_ascii=False, sort_keys=True, indent=2).encode()
```

`sort_keys=True` đã có nên tính tất định của sha bundle giữ nguyên.

- [ ] **Step 5: Chạy để xác nhận xanh**

Run: `uv run pytest tests/modules/config/test_config_agent.py tests/modules/config/test_bundle.py -q -m "not integration"`
Expected: PASS.

- [ ] **Step 6: Sinh lại hợp đồng**

```bash
make contracts
git diff --stat contracts/
```
Expected: `contracts/agent-config.json` đổi, có khoá `voice.tts_normalization`.

⚠️ `agent-config.json` là **mẫu vàng**: mọi giá trị phải KHÁC mặc định phía agent. Mặc định bên agent là map rỗng, nên nếu mẫu vàng sinh ra `{}` thì cổng «không trường nào rơi về mặc định» ở repo agent **không thể đỏ** cho trường này. Kiểm:

```bash
python3 -c "import json;print(json.load(open('contracts/agent-config.json'))['voice'])"
```

Nếu `tts_normalization` là `{}` thì mở `scripts/gen_contracts.py`, tìm payload mẫu nó dùng để gọi `noi_dung_agent_config()`, và thêm một mục vào `tts_normalization` của payload đó (ví dụ `{"term": "NCLB", "read_as": "Noble Crystal Long Biên"}`), rồi chạy lại `make contracts`.

- [ ] **Step 7: Chạy cổng hợp đồng**

Run: `uv run pytest tests/api/test_contracts.py -q`
Expected: PASS.

- [ ] **Step 8: Lint + commit**

```bash
uv run ruff check src tests scripts && uv run ruff format --check src tests scripts
git add src/portal/modules/config/config_agent.py src/portal/modules/config/bundle.py contracts/ tests/modules/config/ scripts/gen_contracts.py
git commit -m "feat(config): expose tts_normalization in agent contract and bundle"
```

- [ ] **Step 9: Chạy toàn bộ suite portal**

Run: `uv run pytest -q -m "not integration"`
Expected: PASS. Ghi lại con số passed/failed để so với baseline; danh sách đỏ phải TRÙNG baseline (`tests/modules/test_heartbeat.py` đã đỏ từ trước — RLS thiếu trên `control.agent_heartbeats`).

---

### Task 4: Kiểu và mặc định phía frontend

**Files:**
- Modify: `/home/thanhhai/Desktop/odyssey-portal-frontend/src/features/agent/api.ts`
- Modify: `/home/thanhhai/Desktop/odyssey-portal-frontend/src/features/agent/useBanNhap.ts`
- Test: `/home/thanhhai/Desktop/odyssey-portal-frontend/tests/tts-normalization.test.tsx` (create)

**Interfaces:**
- Consumes: hợp đồng của Task 1 (bản chép tay — không có cổng CI nào so hai bên, cổng thật là 422 của backend).
- Produces: `export interface NormalizationEntry { term: string; read_as: string }` và trường `ConfigPayload['tts_normalization']: NormalizationEntry[]`. Task 5 dùng đúng hai tên đó.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/tts-normalization.test.tsx`:

```tsx
/**
 * Từ điển cách đọc TTS — `chuanHoa()` phải sinh mặc định `[]`.
 *
 * Backend cũ (chưa deploy) trả payload KHÔNG có trường này. Không có mặc định thì
 * `undefined` chảy vào `.map()` của bảng và màn trắng — không phải một lỗi đọc được.
 */
import { describe, expect, it } from 'vitest'
import { chuanHoaChoTest } from '../src/features/agent/useBanNhap'

const PAYLOAD_KHONG_CO_TRUONG = {
  schema_version: 3,
  danh_tinh: {
    ten_agent: 'Mai',
    ten_thuong_hieu: 'An Phú Land',
    tu_xung: 'em',
    goi_khach: 'anh/chị',
    loi_chao: '',
  },
  pham_vi: {
    linh_vuc: 'realestate',
    lam_gi: '',
    khong_lam_gi: '',
    phong_ban: [{ ten: 'CSKH', khi_nao: '' }],
    cau_tu_choi: '',
  },
  giong: { giong_dieu: 'than_thien', do_dai: 'trung_binh' },
  tools: { enabled: ['find_project', 'kb_search'] },
}

describe('chuanHoa · tts_normalization', () => {
  it('payload thiếu trường thì thành danh sách rỗng', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ra = chuanHoaChoTest(PAYLOAD_KHONG_CO_TRUONG as any)

    expect(ra.tts_normalization).toEqual([])
  })

  it('giữ nguyên danh sách khi payload đã có', () => {
    const vao = {
      ...PAYLOAD_KHONG_CO_TRUONG,
      tts_normalization: [{ term: 'NCLB', read_as: 'Noble Crystal Long Biên' }],
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ra = chuanHoaChoTest(vao as any)

    expect(ra.tts_normalization).toEqual([{ term: 'NCLB', read_as: 'Noble Crystal Long Biên' }])
  })

  it('giá trị không phải mảng cũng thành mảng rỗng', () => {
    const vao = { ...PAYLOAD_KHONG_CO_TRUONG, tts_normalization: null }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ra = chuanHoaChoTest(vao as any)

    expect(ra.tts_normalization).toEqual([])
  })
})
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `cd /home/thanhhai/Desktop/odyssey-portal-frontend && npm test -- tts-normalization`
Expected: FAIL — `chuanHoaChoTest` không được export từ `useBanNhap`.

- [ ] **Step 3: Thêm kiểu vào `api.ts`**

Ngay trước `export interface ConfigPayload`:

```ts
/** Một mục của từ điển cách đọc TTS. Bản chép tay của `NormalizationEntry` phía Python. */
export interface NormalizationEntry {
  term: string
  read_as: string
}

/** Khớp `Field(max_length=…)` phía backend — quá thì 422. */
export const NORMALIZATION_TERM_TOI_DA = 60
export const NORMALIZATION_READ_AS_TOI_DA = 200
export const NORMALIZATION_SO_MUC_TOI_DA = 200
```

Trong `ConfigPayload`, thêm sau `tools`:

```ts
  tts_normalization: NormalizationEntry[]
```

- [ ] **Step 4: Thêm mặc định vào `chuanHoa` và export cho test**

Trong `src/features/agent/useBanNhap.ts`, trong `return {` của `chuanHoa`, thêm sau `schema_version`:

```ts
    tts_normalization: Array.isArray(p.tts_normalization) ? p.tts_normalization : [],
```

Ngay sau hàm `chuanHoa`, thêm:

```ts
/** Lối vào cho test — `chuanHoa` là chi tiết nội bộ của hook, nhưng phép sinh mặc định
 * của nó là thứ giữ màn không trắng khi backend chưa deploy, nên nó cần một bài canh. */
export const chuanHoaChoTest = chuanHoa
```

- [ ] **Step 5: Chạy để xác nhận xanh**

Run: `npm test -- tts-normalization`
Expected: PASS — 3 passed.

- [ ] **Step 6: Typecheck**

Run: `npm run build`
Expected: thành công. `tsc --noEmit` bỏ sót lỗi kiểu nên phải dùng `build` (CI dùng `tsc -b`). Nếu đỏ vì các nơi khác dựng `ConfigPayload` literal mà thiếu trường mới, thêm `tts_normalization: []` vào từng chỗ đó (kể cả trong `tests/` và `src/lib/msw/handlers.ts`).

- [ ] **Step 7: Lint + commit**

```bash
npm run lint && npm run format:check
git add src/features/agent/api.ts src/features/agent/useBanNhap.ts tests/tts-normalization.test.tsx
git commit -m "feat(agent): add tts_normalization to the config payload type"
```

---

### Task 5: Giao diện — preview 3 dòng + dialog

**Files:**
- Create: `/home/thanhhai/Desktop/odyssey-portal-frontend/src/features/agent/components/Normalization.tsx`
- Create: `/home/thanhhai/Desktop/odyssey-portal-frontend/src/features/agent/components/NormalizationDialog.tsx`
- Modify: `src/features/agent/components/CauHinhChung.tsx:144` (trước `<RaoChan />`)
- Modify: `src/features/agent/components/TomTatCauHinh.tsx:103` (trước `<RaoChan />`)
- Test: `tests/tts-normalization.test.tsx`

**Interfaces:**
- Consumes: `NormalizationEntry`, `NORMALIZATION_TERM_TOI_DA`, `NORMALIZATION_READ_AS_TOI_DA`, `NORMALIZATION_SO_MUC_TOI_DA` từ Task 4; `The` từ `./form`; `NUT_PHU` từ `./lop`.
- Produces:
  - `NormalizationPreview({ muc, doi }: { muc: NormalizationEntry[]; doi?: (m: NormalizationEntry[]) => void })` — `doi` vắng mặt = chỉ-đọc.
  - `NormalizationDialog({ muc, doi, onDong })` — `doi` vắng mặt = chỉ-đọc.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/tts-normalization.test.tsx`:

```tsx
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { NormalizationPreview } from '../src/features/agent/components/Normalization'

const NAM_MUC = [
  { term: 'NCLB', read_as: 'Noble Crystal Long Biên' },
  { term: 'SSLC', read_as: 'Sunshine Legend City' },
  { term: 'NPTH', read_as: 'Noble Palace Tây Hồ' },
  { term: 'NCRS', read_as: 'Noble Crystal Riverside' },
  { term: 'NPTTL', read_as: 'Noble Palace Tây Thăng Long' },
]

describe('NormalizationPreview', () => {
  it('rỗng thì nói agent đang dùng bộ mặc định của nền tảng', () => {
    render(<NormalizationPreview muc={[]} />)

    expect(screen.getByText(/bộ mặc định của nền tảng/i)).toBeInTheDocument()
  })

  it('hiện đúng 3 dòng đầu và nói còn bao nhiêu mục nữa', () => {
    render(<NormalizationPreview muc={NAM_MUC} />)

    expect(screen.getByText('NCLB')).toBeInTheDocument()
    expect(screen.getByText('NPTH')).toBeInTheDocument()
    expect(screen.queryByText('NCRS')).not.toBeInTheDocument()
    expect(screen.getByText(/còn 2 mục nữa/i)).toBeInTheDocument()
  })

  it('nút mở dialog mang số mục và mở ra bảng đầy đủ', async () => {
    const nd = userEvent.setup()
    render(<NormalizationPreview muc={NAM_MUC} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(5\)/i }))

    const hop = screen.getByRole('dialog')
    expect(within(hop).getByText('NCRS')).toBeInTheDocument()
    expect(within(hop).getByText(/viết HOA toàn bộ chỉ khớp/i)).toBeInTheDocument()
  })

  it('chỉ-đọc thì dialog không có nút xoá và không có ô thêm', async () => {
    const nd = userEvent.setup()
    render(<NormalizationPreview muc={NAM_MUC} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(5\)/i }))

    const hop = screen.getByRole('dialog')
    expect(within(hop).queryByRole('button', { name: /^xoá/i })).not.toBeInTheDocument()
    expect(within(hop).queryByLabelText(/từ hoặc mã/i)).not.toBeInTheDocument()
  })

  it('sửa được thì thêm một mục gọi doi với mục mới ở cuối', async () => {
    const nd = userEvent.setup()
    const daGoi: unknown[] = []
    render(<NormalizationPreview muc={[]} doi={(m) => daGoi.push(m)} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(0\)/i }))
    const hop = screen.getByRole('dialog')
    await nd.type(within(hop).getByLabelText(/từ hoặc mã/i), 'NCLB')
    await nd.type(within(hop).getByLabelText(/đọc thành/i), 'Noble Crystal Long Biên')
    await nd.click(within(hop).getByRole('button', { name: /^thêm$/i }))

    expect(daGoi).toEqual([[{ term: 'NCLB', read_as: 'Noble Crystal Long Biên' }]])
  })

  it('chặn khoá trùng ngay tại chỗ, không đợi 422 của backend', async () => {
    const nd = userEvent.setup()
    const daGoi: unknown[] = []
    render(
      <NormalizationPreview
        muc={[{ term: 'NCLB', read_as: 'Noble Crystal Long Biên' }]}
        doi={(m) => daGoi.push(m)}
      />,
    )

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(1\)/i }))
    const hop = screen.getByRole('dialog')
    await nd.type(within(hop).getByLabelText(/từ hoặc mã/i), 'nclb')
    await nd.type(within(hop).getByLabelText(/đọc thành/i), 'Khác')
    await nd.click(within(hop).getByRole('button', { name: /^thêm$/i }))

    expect(daGoi).toEqual([])
    expect(within(hop).getByText(/đã có mục này/i)).toBeInTheDocument()
  })

  it('nút đóng ghi Xong và nói rõ phải bấm Lưu và áp dụng', async () => {
    const nd = userEvent.setup()
    render(<NormalizationPreview muc={[]} doi={() => {}} />)

    await nd.click(screen.getByRole('button', { name: /xem tất cả \(0\)/i }))

    const hop = screen.getByRole('dialog')
    expect(within(hop).getByRole('button', { name: /^xong$/i })).toBeInTheDocument()
    expect(within(hop).getByText(/sau khi bấm Lưu và áp dụng/i)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `npm test -- tts-normalization`
Expected: FAIL — không resolve được `../src/features/agent/components/Normalization`.

- [ ] **Step 3: Viết `NormalizationDialog.tsx`**

```tsx
/**
 * Bảng đầy đủ của từ điển cách đọc TTS.
 *
 * DIALOG NÀY KHÔNG LƯU. Nó sửa bản nháp trong bộ nhớ qua `doi`, và bản nháp chỉ ra khách
 * khi bấm «Lưu và áp dụng» ở ngoài. Nút đóng vì thế ghi «Xong», không phải «Lưu» — một
 * dialog có bảng và có nút được đọc là biểu mẫu tự lưu, và người dùng sẽ rời màn mà không
 * publish.
 *
 * `doi` vắng mặt = chỉ-đọc (dùng ở bản tóm tắt).
 *
 * Số đo và class chép từ `features/platform/components/TaoKhoaDialog.tsx` — các dialog của
 * portal phải trông như nhau.
 */
import { useEffect, useId, useState } from 'react'
import {
  NORMALIZATION_READ_AS_TOI_DA,
  NORMALIZATION_SO_MUC_TOI_DA,
  NORMALIZATION_TERM_TOI_DA,
  type NormalizationEntry,
} from '../api'
import { NUT_CHINH, NUT_PHU, O_LOP } from './lop'

export function NormalizationDialog({
  muc,
  doi,
  onDong,
}: {
  muc: NormalizationEntry[]
  doi?: ((m: NormalizationEntry[]) => void) | undefined
  onDong: () => void
}) {
  const id = useId()
  const [term, setTerm] = useState('')
  const [readAs, setReadAs] = useState('')
  const [loi, setLoi] = useState('')

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onDong()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onDong])

  function them(e: React.FormEvent) {
    e.preventDefault()
    if (!doi) return
    const t = term.trim()
    const r = readAs.trim()
    if (t === '' || r === '') return setLoi('Điền cả hai ô.')
    if (t === r) return setLoi('Hai ô giống nhau — mục này không làm gì.')
    if (muc.length >= NORMALIZATION_SO_MUC_TOI_DA)
      return setLoi(`Tối đa ${NORMALIZATION_SO_MUC_TOI_DA} mục.`)
    // So không phân biệt hoa/thường, khớp đúng phép validate của backend.
    if (muc.some((m) => m.term.toLowerCase() === t.toLowerCase()))
      return setLoi('Đã có mục này trong bảng.')
    doi([...muc, { term: t, read_as: r }])
    setTerm('')
    setReadAs('')
    setLoi('')
  }

  return (
    <div className="fixed inset-0 z-70 grid place-items-center px-4">
      <button
        type="button"
        aria-label="Đóng"
        onClick={onDong}
        className="absolute inset-0 cursor-default bg-panel/45"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-tieu-de`}
        className="relative flex max-h-[80dvh] w-full max-w-[620px] flex-col rounded-2xl border border-border-field bg-surface p-5 shadow-[0_18px_50px_rgba(20,22,26,.22)]"
      >
        <h2 id={`${id}-tieu-de`} className="text-[16.5px] font-semibold leading-tight text-fg">
          Cách đọc cho giọng nói
        </h2>
        <p className="mt-1.5 text-[13px] leading-[1.55] text-muted">
          Từ viết HOA toàn bộ chỉ khớp khi khách cũng viết HOA.
        </p>

        <div className="mt-4 min-h-0 flex-1 overflow-y-auto rounded-lg border border-border">
          <table className="w-full text-[13.5px]">
            <thead className="sticky top-0 bg-fill text-left text-[12.5px] text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Từ hoặc mã</th>
                <th className="px-3 py-2 font-medium">Đọc thành</th>
                {doi && <th className="w-16 px-3 py-2" />}
              </tr>
            </thead>
            <tbody>
              {muc.length === 0 && (
                <tr>
                  <td colSpan={doi ? 3 : 2} className="px-3 py-4 text-muted">
                    Chưa có mục nào.
                  </td>
                </tr>
              )}
              {muc.map((m, i) => (
                <tr key={m.term} className="border-t border-rule">
                  <td className="px-3 py-2 font-mono">{m.term}</td>
                  <td className="px-3 py-2">{m.read_as}</td>
                  {doi && (
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        aria-label={`Xoá ${m.term}`}
                        onClick={() => doi(muc.filter((_, j) => j !== i))}
                        className="text-[13px] text-muted underline hover:text-fg"
                      >
                        Xoá
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {doi && (
          <form onSubmit={them} className="mt-3 flex flex-wrap items-end gap-2">
            <label className="flex-1 text-[12.5px] text-muted">
              Từ hoặc mã
              <input
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                maxLength={NORMALIZATION_TERM_TOI_DA}
                placeholder="VD: NCLB"
                className={`${O_LOP} mt-1`}
              />
            </label>
            <label className="flex-[2] text-[12.5px] text-muted">
              Đọc thành
              <input
                value={readAs}
                onChange={(e) => setReadAs(e.target.value)}
                maxLength={NORMALIZATION_READ_AS_TOI_DA}
                placeholder="VD: Noble Crystal Long Biên"
                className={`${O_LOP} mt-1`}
              />
            </label>
            <button type="submit" className={NUT_PHU}>
              Thêm
            </button>
          </form>
        )}
        {loi !== '' && <p className="mt-2 text-[12.5px] text-alert">{loi}</p>}

        <div className="mt-4 flex items-center justify-between gap-3">
          <p className="text-[12px] text-muted-2">
            {doi
              ? 'Thay đổi có hiệu lực sau khi bấm Lưu và áp dụng.'
              : 'Đây là bản đang phục vụ khách.'}
          </p>
          <button type="button" onClick={onDong} className={NUT_CHINH}>
            Xong
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Viết `Normalization.tsx`**

```tsx
/**
 * Khu «Cách đọc cho giọng nói» — preview 3 dòng, mở dialog để xem/sửa đầy đủ.
 *
 * Đặt NGAY TRÊN khối Rào chắn ở CẢ HAI phía (form sửa và bản tóm tắt): hai bên bắt buộc
 * khai cùng các khu theo cùng thứ tự, nếu không thì bấm «Sửa cấu hình» là ô nhảy chỗ.
 *
 * Trạng thái rỗng phải nói về BỘ NỀN mà không bày nó ra. «Chưa có mục nào» một mình làm
 * người dùng kết luận agent đang đọc `Vietcombank` theo mặt chữ — sai, và họ sẽ đi nhập
 * lại 44 mục đã có sẵn.
 */
import { useState } from 'react'
import type { NormalizationEntry } from '../api'
import { The } from './form'
import { NUT_PHU } from './lop'
import { NormalizationDialog } from './NormalizationDialog'

const SO_DONG_PREVIEW = 3

export function NormalizationPreview({
  muc,
  doi,
}: {
  muc: NormalizationEntry[]
  doi?: ((m: NormalizationEntry[]) => void) | undefined
}) {
  const [mo, setMo] = useState(false)
  const dau = muc.slice(0, SO_DONG_PREVIEW)
  const con = muc.length - dau.length

  return (
    <The
      tieuDe="Cách đọc cho giọng nói"
      phu="Dạy agent đọc đúng mã dự án, tên thương hiệu và từ địa phương của workspace này."
    >
      {muc.length === 0 ? (
        <p className="text-[13.5px] text-muted">
          Chưa có mục nào. Agent đang dùng bộ mặc định của nền tảng.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {dau.map((m) => (
            <li key={m.term} className="flex flex-wrap items-baseline gap-2 text-[13.5px]">
              <span className="font-mono">{m.term}</span>
              <span className="text-muted-2">→</span>
              <span className="text-muted">{m.read_as}</span>
            </li>
          ))}
        </ul>
      )}
      {con > 0 && <p className="mt-2 text-[12.5px] text-muted-2">còn {con} mục nữa</p>}

      <button type="button" onClick={() => setMo(true)} className={`${NUT_PHU} mt-4`}>
        Xem tất cả ({muc.length})
      </button>

      {mo && <NormalizationDialog muc={muc} doi={doi} onDong={() => setMo(false)} />}
    </The>
  )
}
```

- [ ] **Step 5: Chạy để xác nhận xanh**

Run: `npm test -- tts-normalization`
Expected: PASS — 10 passed (3 của Task 4 + 7 mới).

- [ ] **Step 6: Gắn vào hai màn**

Trong `src/features/agent/components/CauHinhChung.tsx`, thêm import:

```tsx
import { NormalizationPreview } from './Normalization'
```

và chèn NGAY TRƯỚC `<RaoChan />`:

```tsx
      <NormalizationPreview
        muc={form.tts_normalization}
        doi={(m) => sua((c) => ({ ...c, tts_normalization: m }))}
      />
```

Trong `src/features/agent/components/TomTatCauHinh.tsx`, thêm cùng import và chèn NGAY TRƯỚC `<RaoChan />`:

```tsx
      <NormalizationPreview muc={props.payload.tts_normalization} />
```

⚠️ Tên prop mang payload ở `TomTatCauHinh` phải đọc từ chính chữ ký hàm của file đó — mở file ra xem nó nhận `payload`, `cau_hinh`, hay tên khác, rồi dùng đúng tên đó thay cho `props.payload`.

- [ ] **Step 7: Kiểm hai màn còn chạy**

Run: `npm test -- agent-studio`
Expected: PASS. Nếu đỏ vì `PAYLOAD` trong test đó thiếu trường mới, thêm `tts_normalization: []` vào nó.

- [ ] **Step 8: Typecheck + lint**

Run: `npm run build && npm run lint && npm run format:check`
Expected: cả ba thành công.

- [ ] **Step 9: Commit**

```bash
git add src/features/agent/components tests/tts-normalization.test.tsx
git commit -m "feat(agent): add TTS reading dictionary section above the guardrails block"
```

---

### Task 6: Agent đọc cột mới

**Files:**
- Modify: `/home/thanhhai/Desktop/odyssey-agent/src/noble_agent/storage/agent_config_store.py:20-27`
- Modify: `/home/thanhhai/Desktop/odyssey-agent/src/noble_agent/agent/agent_config.py`
- Test: `/home/thanhhai/Desktop/odyssey-agent/tests/unit/unified/test_agent_config_store.py`

**Interfaces:**
- Consumes: cột `tenant_data.agent_config.tts_normalization` (Task 2), luôn là JSON object.
- Produces: `AgentConfig.tts_normalization: dict[str, str]`. Task 7 đọc đúng thuộc tính đó.

- [ ] **Step 1: Viết test đỏ**

Thêm vào `tests/unit/unified/test_agent_config_store.py`:

```python
def test_parse_config_doc_tts_normalization():
    from noble_agent.agent.agent_config import parse_config

    cfg = parse_config({"name": "Mai", "tts_normalization": {"NCLB": "Noble Crystal Long Biên"}})

    assert cfg.tts_normalization == {"NCLB": "Noble Crystal Long Biên"}


def test_parse_config_tu_dien_thieu_thanh_dict_rong():
    from noble_agent.agent.agent_config import parse_config

    assert parse_config({"name": "Mai"}).tts_normalization == {}


def test_parse_config_tu_dien_sai_kieu_thanh_dict_rong():
    """⚠️ Cột này là OBJECT, khác `departments`/`skills` là MẢNG. `_decode(...) or []` biến
    `{}` thành `[]` vì `{}` là falsy — nếu ai đó xếp cột này vào `_JSON_COLUMNS` thì
    `parse_config` nhận list ở chỗ nó chờ dict, và bài này đỏ."""
    from noble_agent.agent.agent_config import parse_config

    assert parse_config({"name": "Mai", "tts_normalization": []}).tts_normalization == {}


def test_parse_config_bo_muc_khong_phai_chuoi():
    from noble_agent.agent.agent_config import parse_config

    cfg = parse_config({"name": "Mai", "tts_normalization": {"NCLB": 12, "SSLC": "Sunshine"}})

    assert cfg.tts_normalization == {"SSLC": "Sunshine"}
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `cd /home/thanhhai/Desktop/odyssey-agent && uv run pytest tests/unit/unified/test_agent_config_store.py -q`
Expected: FAIL — `AttributeError: 'AgentConfig' object has no attribute 'tts_normalization'`.

- [ ] **Step 3: Thêm trường vào `AgentConfig` và `parse_config`**

Trong `src/noble_agent/agent/agent_config.py`, thêm vào `@dataclass(frozen=True) class AgentConfig` sau `data_source`:

```python
    tts_normalization: dict[str, str] = field(default_factory=dict)
```

Thêm `field` vào import dataclasses ở đầu file:

```python
from dataclasses import dataclass, field
```

Thêm helper ngay trước `def parse_config`:

```python
def _tts_normalization(value) -> dict[str, str]:
    """Object -> {term: read_as}. Mọi hình dạng khác thành rỗng.

    Cột DB là OBJECT (CHECK `jsonb_typeof = 'object'`), khác `departments`/`skills`. Một
    list tới đây nghĩa là đường giải mã đã hỏng, và im lặng bỏ nó tốt hơn là để một
    `AttributeError` nổ giữa lượt nói.
    """
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str) and k and v}
```

Trong `parse_config`, trước `return AgentConfig(...)`:

```python
    tts_normalization = _tts_normalization(raw.get("tts_normalization"))
```

và thêm vào lời gọi `AgentConfig(...)`:

```python
        tts_normalization=tts_normalization,
```

- [ ] **Step 4: Đọc cột từ DB**

Trong `src/noble_agent/storage/agent_config_store.py`, sửa khối hằng:

```python
_COLUMNS = (
    "name", "brand_name", "self_pronoun", "customer_pronoun", "greeting",
    "scope_does", "scope_does_not", "refusal_line", "departments",
    "tone", "reply_length", "skills", "tts_normalization", "version",
)
_SQL = f"SELECT {', '.join(_COLUMNS)} FROM tenant_data.agent_config WHERE tenant_id = $1"
_JSON_COLUMNS = ("departments", "skills")
# ⚠️ TẬP RIÊNG, không gộp vào `_JSON_COLUMNS`: hai cột kia là MẢNG và dùng `or []`, còn
# `{}` là FALSY trong Python — một từ điển rỗng đi qua `or []` sẽ thành `[]`.
_JSON_OBJECT_COLUMNS = ("tts_normalization",)
```

và trong `_read_from_db`, sau vòng lặp `_JSON_COLUMNS`:

```python
    for col in _JSON_OBJECT_COLUMNS:
        config[col] = _decode(config.get(col)) or {}
```

- [ ] **Step 5: Chạy để xác nhận xanh**

Run: `uv run pytest tests/unit/unified/test_agent_config_store.py -q`
Expected: PASS.

- [ ] **Step 6: Chạy suite unit của agent**

Run: `uv run pytest tests/unit -q`
Expected: danh sách đỏ TRÙNG baseline. Chạy `git stash && uv run pytest tests/unit -q && git stash pop` trước đó nếu chưa biết baseline. Lưu ý `tests/unit/test_tool_ack.py` flaky theo thời gian — chạy riêng để xác nhận.

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/storage/agent_config_store.py src/noble_agent/agent/agent_config.py tests/unit/unified/test_agent_config_store.py
git commit -m "feat(config): read the tenant tts_normalization column"
```

---

### Task 7: Áp từ điển tenant trong `normalize_for_voice`

**Files:**
- Modify: `/home/thanhhai/Desktop/odyssey-agent/src/noble_agent/voice/tts/_normalize.py:565-605`
- Modify: `/home/thanhhai/Desktop/odyssey-agent/src/noble_agent/agent/facade.py:227-244` (`_agent_def_from_db`)
- Test: `/home/thanhhai/Desktop/odyssey-agent/tests/unit/voice/test_normalize_tenant_overrides.py` (create)

**Interfaces:**
- Consumes: `AgentConfig.tts_normalization` (Task 6); `_apply_map(text, nmap, strict_upper)` và `normalize_for_voice(text)` đã có.
- Produces: `set_tenant_overrides(nmap: dict[str, str]) -> None` và `reset_tenant_overrides() -> None` trong `noble_agent.voice.tts._normalize`.

- [ ] **Step 1: Viết test đỏ**

Tạo `tests/unit/voice/test_normalize_tenant_overrides.py`:

```python
"""Lớp từ điển của tenant chồng lên bộ nền.

Pass của tenant chèn SỚM — sau bước strip URL/markdown, TRƯỚC `_ROMAN_RE`/`_CODE_RE`. Hai
lẽ: `_CODE_RE` đọc mọi thứ trông giống mã theo từng chữ, nên đặt muộn thì tenant không thể
dạy agent đọc `NPTTL-A12`; và văn bản THAY RA vẫn chảy qua mọi pass sau nên số/ngày/tiền
trong đó vẫn được đọc đúng.
"""

import pytest

from noble_agent.voice.tts._normalize import (
    normalize_for_voice,
    reset_tenant_overrides,
    set_tenant_overrides,
)


@pytest.fixture(autouse=True)
def _sach():
    reset_tenant_overrides()
    yield
    reset_tenant_overrides()


def test_khong_co_lop_tenant_thi_khong_doi_gi():
    truoc = normalize_for_voice("Dự án NCLB")
    reset_tenant_overrides()

    assert normalize_for_voice("Dự án NCLB") == truoc


def test_muc_tenant_duoc_ap():
    set_tenant_overrides({"XYZW": "Khu Đô Thị Mẫu"})

    assert "Khu Đô Thị Mẫu" in normalize_for_voice("Dự án XYZW đang mở bán")


def test_tenant_thang_muc_reading_cua_nen():
    """Nền có `Vietcombank → việt com bank`. Tenant đặt lại thì bản của tenant ra."""
    set_tenant_overrides({"Vietcombank": "vietcombank đọc kiểu khác"})

    ra = normalize_for_voice("Thanh toán qua Vietcombank")

    assert "vietcombank đọc kiểu khác" in ra
    assert "việt com bank" not in ra


def test_tenant_thang_muc_abbrev_cua_nen():
    """Nền có `NCLB → Noble Crystal Long Biên`. Pass tenant chạy trước nên nó ĂN TOKEN,
    và pass abbrev sau đó không còn `NCLB` nào để tìm."""
    set_tenant_overrides({"NCLB": "Noble Crystal Long Biên giai đoạn hai"})

    ra = normalize_for_voice("Căn ở NCLB")

    assert "Noble Crystal Long Biên giai đoạn hai" in ra


def test_khoa_viet_hoa_phan_biet_hoa_thuong():
    """`strict_upper`: khoá viết HOA toàn bộ chỉ khớp văn bản viết HOA. Không có luật này
    thì `HD → hợp đồng` viết lại cả chữ `hd` viết thường."""
    set_tenant_overrides({"HD": "hợp đồng"})

    assert "hợp đồng" in normalize_for_voice("Xem HD nhé")
    assert "hợp đồng" not in normalize_for_voice("mã hd nhé")


def test_khoa_viet_thuong_khong_phan_biet_hoa_thuong():
    set_tenant_overrides({"Sunshine": "săn sai"})

    assert "săn sai" in normalize_for_voice("khu sunshine")


def test_khoa_trong_giong_ma_van_khop():
    """Bài này chứng minh VỊ TRÍ pass. Đặt muộn thì `_CODE_RE` đã đánh vần `NPTTL-A12`
    thành từng chữ trước khi map của tenant được xem tới, và bài này đỏ."""
    set_tenant_overrides({"NPTTL-A12": "căn A mười hai toà Tây Thăng Long"})

    assert "căn A mười hai toà Tây Thăng Long" in normalize_for_voice("Căn NPTTL-A12 còn hàng")


def test_van_ban_thay_ra_van_duoc_doc_so():
    """Đặt sớm không mất gì: output vẫn chảy qua các pass số phía sau."""
    set_tenant_overrides({"XYZW": "toà 12"})

    assert "mười hai" in normalize_for_voice("Dự án XYZW")
```

- [ ] **Step 2: Chạy để xác nhận đỏ**

Run: `uv run pytest tests/unit/voice/test_normalize_tenant_overrides.py -q`
Expected: FAIL — `ImportError: cannot import name 'set_tenant_overrides'`.

- [ ] **Step 3: Thêm setter vào `_normalize.py`**

Ngay sau khối `_READING_MAP`/`_ABBREV_MAP`/`_ensure_maps` (khoảng dòng 565-575), thêm:

```python
_TENANT_MAP: dict[str, str] = {}


def set_tenant_overrides(nmap: dict[str, str]) -> None:
    """Set the tenant's reading dictionary, layered over the platform baseline.

    A module-level holder is correct here: an agent pod is single-tenant (TenantContext is
    resolved once at boot from TENANT_ID), so threading the map through every
    normalize_for_voice() call site would add four parameters for no isolation gain.
    """
    global _TENANT_MAP
    _TENANT_MAP = {k: v for k, v in (nmap or {}).items() if k and v}


def reset_tenant_overrides() -> None:
    global _TENANT_MAP
    _TENANT_MAP = {}
```

- [ ] **Step 4: Chèn pass vào `normalize_for_voice`**

Trong `normalize_for_voice`, chèn giữa dòng `_EMAIL_AT_RE` (601) và dòng `_ROMAN_RE` (603):

```python
    # Lớp tenant chạy SỚM NHẤT trong các pass thay chữ: `_CODE_RE` bên dưới đọc mọi thứ
    # trông giống mã theo từng chữ, nên đặt sau nó là tenant không dạy được cách đọc một
    # mã căn. Văn bản thay ra vẫn chảy qua mọi pass phía sau.
    if _TENANT_MAP:
        text = _apply_map(text, _TENANT_MAP, strict_upper=True)
```

- [ ] **Step 5: Chạy để xác nhận xanh**

Run: `uv run pytest tests/unit/voice/test_normalize_tenant_overrides.py -q`
Expected: PASS — 8 passed.

Nếu `test_khoa_trong_giong_ma_van_khop` đỏ, pass đang nằm sai chỗ (sau `_CODE_RE`). Nếu `test_van_ban_thay_ra_van_duoc_doc_so` đỏ, nó nằm quá muộn để các pass số chạy trên output.

- [ ] **Step 6: Nối dây ở `facade._agent_def_from_db`**

Trong `src/noble_agent/agent/facade.py`, hàm `_agent_def_from_db`, sau dòng `cfg = parse_config(pc.config)`:

```python
    from noble_agent.voice.tts._normalize import set_tenant_overrides

    set_tenant_overrides(cfg.tts_normalization)
```

Đây là chỗ DUY NHẤT parse config cho runner (`_build_runner_for_version` cũng parse để dựng `TenantContext` nhưng rồi vẫn gọi `_build_runner_from_ctx` → `_agent_def_from_db`), nên một lời gọi ở đây là đủ. `parse_config` giữ nguyên là hàm THUẦN — đừng nhét setter vào trong nó.

- [ ] **Step 7: Viết test cho phép nối dây**

Thêm vào `tests/unit/voice/test_normalize_tenant_overrides.py`:

```python
async def test_facade_nap_tu_dien_cua_tenant(monkeypatch):
    """Nối dây phải có bài canh: quên lời gọi này thì `_normalize` dùng nền trần và không
    có triệu chứng nào ngoài việc agent đọc sai."""
    from noble_agent.agent import facade
    from noble_agent.storage.agent_config_store import PublishedConfig
    from noble_agent.voice.tts import _normalize

    async def _pc(_tenant_id, **_kw):
        return PublishedConfig(
            version=1,
            config={"name": "Mai", "tts_normalization": {"XYZW": "Khu Đô Thị Mẫu"}},
        )

    monkeypatch.setattr(facade, "read_published_config", _pc)
    monkeypatch.setattr(facade, "build_agent_def_from_config", lambda *a, **k: object(), raising=False)

    await facade._agent_def_from_db("t_demo", "chat")

    assert _normalize._TENANT_MAP == {"XYZW": "Khu Đô Thị Mẫu"}
```

⚠️ `build_agent_def_from_config` được import BÊN TRONG `_agent_def_from_db`, nên `monkeypatch.setattr(facade, ...)` có thể không chặn được. Chạy bài này; nếu nó nổ ở `build_agent_def_from_config`, patch tại nguồn thay vì tại facade:

```python
    import noble_agent.agent.base as base

    monkeypatch.setattr(base, "build_agent_def_from_config", lambda *a, **k: object())
```

- [ ] **Step 8: Chạy để xác nhận xanh**

Run: `uv run pytest tests/unit/voice/test_normalize_tenant_overrides.py -q`
Expected: PASS — 9 passed.

- [ ] **Step 9: Chạy suite unit của agent**

Run: `uv run pytest tests/unit -q`
Expected: danh sách đỏ TRÙNG baseline đã ghi ở Task 6 Step 6.

- [ ] **Step 10: Commit**

```bash
git add src/noble_agent/voice/tts/_normalize.py src/noble_agent/agent/facade.py tests/unit/voice/test_normalize_tenant_overrides.py
git commit -m "feat(tts): layer the tenant reading dictionary over the platform baseline"
```

---

### Task 8: Copy hợp đồng và ghi lại thứ tự deploy

**Files:**
- Modify: `/home/thanhhai/Desktop/odyssey-agent/contracts/agent-config.json` (hoặc đường dẫn mà repo đó giữ bản chép — tìm bằng `grep -rl "schema_version" --include='*.json' contracts/ docs/`)
- Modify: `/home/thanhhai/Desktop/odyssey-portal-backend/docs/contracts/dau-noi-agent.md`

**Interfaces:**
- Consumes: `contracts/agent-config.json` sinh ở Task 3.
- Produces: không có ký hiệu code nào; đây là bước hợp đồng và tài liệu.

- [ ] **Step 1: Tìm bản chép ở repo agent**

```bash
cd /home/thanhhai/Desktop/odyssey-agent && grep -rl "schema_version" --include='*.json' . | grep -v node_modules | grep -v '\.venv'
```
Expected: in ra đường dẫn bản chép của `agent-config.json`.

- [ ] **Step 2: Copy và chạy test hợp đồng bên agent**

```bash
cp /home/thanhhai/Desktop/odyssey-portal-backend/contracts/agent-config.json <đường dẫn tìm được ở Step 1>
uv run pytest tests -q -k "agent_config or contract"
```
Expected: PASS.

- [ ] **Step 3: Ghi thứ tự deploy vào tài liệu đấu nối**

Thêm vào `/home/thanhhai/Desktop/odyssey-portal-backend/docs/contracts/dau-noi-agent.md` một mục:

```markdown
## Từ điển cách đọc TTS theo tenant (2026-08-24)

`tenant_data.agent_config` có cột mới `tts_normalization jsonb` — object `{term: read_as}`,
là lớp CHỒNG LÊN `data/tts_normalize_vi.json` của repo agent, không thay nó. Trùng khoá thì
tenant thắng.

⚠️ **THỨ TỰ DEPLOY MỘT CHIỀU: migration portal (`0954_tts_normalization`) TRƯỚC, agent SAU.**

Đảo lại thì agent KHÔNG chết — `read_published_config` bắt `except Exception`, log một
`warning`, rồi phục vụ cache last-good trên đĩa. Hệ quả nặng hơn một lần crash: agent đóng
băng ở bản cache cũ và **mọi lần publish sau đó của portal bị bỏ qua**, không dấu hiệu nào
ở phía người dùng. Pod mới chưa có cache thì `_read_last_good` trả `None` — không có cấu
hình nào.

⚠️ Cột này là **OBJECT**, khác `departments`/`skills` là mảng. Bên agent nó nằm trong
`_JSON_OBJECT_COLUMNS` (giải mã bằng `or {}`), KHÔNG nằm trong `_JSON_COLUMNS` — `{}` là
falsy nên `or []` sẽ biến một từ điển rỗng thành `[]`.
```

- [ ] **Step 4: Commit ở cả hai repo**

```bash
cd /home/thanhhai/Desktop/odyssey-agent
git add <đường dẫn bản chép>
git commit -m "chore(contract): sync agent-config.json with tts_normalization"

cd /home/thanhhai/Desktop/odyssey-portal-backend
git add docs/contracts/dau-noi-agent.md
git commit -m "docs(contract): document the tts_normalization column and deploy order"
```

- [ ] **Step 5: Báo lại cho người dùng hai việc họ phải tự làm**

Không tự sửa `CLAUDE.md` (nhiều người cùng sửa, dễ conflict). Báo:

1. CLAUDE.md nói đường duy nhất agent nhận config đã publish là poll object `LIVE` — sai; agent đọc thẳng `tenant_data.agent_config`.
2. Cần một dòng Change Log cho đợt này: cột `tts_normalization`, thứ tự deploy một chiều, và bẫy `{}` falsy.

---

## Self-Review

**Spec coverage**

| Mục spec | Task |
|---|---|
§4 hợp đồng + 4 phép validate + trần | 1 |
§4.1 giữ `schema_version = 3` | 1 (Global Constraints) |
§4.2 list ở payload / object ở bảng phẳng | 1, 2 |
§5.1 migration | 2 |
§5.2 `config_agent` + copy tay | 3, 8 |
§6 giao diện, 3 dòng preview, dialog không lưu, trạng thái rỗng, chú thích ALL-CAPS | 4, 5 |
§7.1 `_JSON_OBJECT_COLUMNS` | 6 |
§7.2 thứ tự deploy | 8 |
§7.3 `AgentConfig` + `parse_config` | 6 |
§7.4 pass riêng, `strict_upper`, chèn sớm, chỗ gọi setter | 7 |
§7.5 `bundle._config_json` | 3 |
§8 test | phủ trong từng task |
§9 hạn chế `truong_da_doi` | nhận trước, không có task |

**Không có mục spec nào thiếu task.**

**Placeholder scan:** không có TBD/TODO. Hai chỗ dặn "mở file ra xem tên thật" (Task 5 Step 6 với prop của `TomTatCauHinh`, Task 8 Step 1 với đường dẫn bản chép) là **lệnh kiểm cụ thể kèm cách kiểm**, không phải chỗ trống — cả hai đều có lệnh chạy để lấy giá trị.

**Type consistency:** `NormalizationEntry.term`/`.read_as` dùng nhất quán ở Task 1→3 (Python) và Task 4→5 (TS). `hang_phang()["tts_normalization"]` là `dict[str, str]` ở Task 2, khớp `AgentConfig.tts_normalization: dict[str, str]` ở Task 6 và `_TENANT_MAP: dict[str, str]` ở Task 7. `set_tenant_overrides`/`reset_tenant_overrides` cùng tên ở Task 7 Step 3, 4, 7.
