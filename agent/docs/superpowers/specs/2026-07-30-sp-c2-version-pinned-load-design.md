# SP-C2 — Version-Pinned Config Load (Read Side) — Design

**Slice:** SP-C, nửa **đọc** (agent nạp phiên bản đã publish ở đầu cuộc, ghim theo cuộc, dò ~20s, kiểm tổng, đệm đĩa).
**Ngày:** 2026-07-30 · **Branch:** `feat/agent` · **Contract:** [C2 trong odyssey-agent-interface-contract](../../api/odyssey-agent-interface-contract.md).
**Phụ thuộc:** **SP-C1** (write side) đã cung cấp trên store: `read_pointer(tenant)→int|None`, `read_version_bundle(tenant,n)→Bundle|None`, `list_versions(tenant)→[int]`, và `read_bundle` resolve về version đang publish. SP-C2 chỉ **đọc** các API đó.

## 1. Mục tiêu (map HT_01)

| YC/BR/E | Ý nghĩa | Cách đáp ứng ở C2 |
|---|---|---|
| YC03 | Agent tự nhận bản mới trong ~20s, không restart | Poller nền refresh con trỏ mỗi `NOBLE_CONFIG_POLL_SEC` (mặc định 20) |
| YC04 / BR05 | Cuộc **đang chạy** giữ nguyên version tới khi kết thúc | Ghim `(session_id → version)` lúc bắt đầu cuộc; runner được **giữ tham chiếu** suốt cuộc, không swap giữa chừng |
| Bậc 3 (§II.2.1) | Thay đổi cấu hình có hiệu lực ở **cuộc MỚI** | Cuộc mới resolve con trỏ hiện tại → version mới; cuộc cũ giữ version cũ |
| E04 | Tải gói nhưng kiểm tổng sai → **giữ bản cũ**, không nạp nửa vời | Sau materialize, tính lại `bundle_hash` so `version.json`; lệch → bỏ version đó, giữ last-good, ghi `last_error` |
| E01 | Backend/store chết → agent phục vụ bằng **đệm đĩa** | Materialize ghi xuống `TENANT_MATERIALIZE_DIR`; store unreachable lúc boot → dùng version cao nhất đã materialize cục bộ |
| E03 | Đã publish nhưng agent chưa nạp | Cuộc cũ dùng bản cũ; version đang chạy phơi ra để SP-D báo `running_version < published` |

## 2. Non-goals (C2)

- **Ghi/publish/rollback** (SP-C1).
- **Phát nhịp tim** (SP-D) — C2 chỉ **phơi ra** `running_version` đang phục vụ mỗi cuộc để SP-D đọc/gửi.
- **`field_policy` / cột agent được đọc** (SP-E).
- **Cắt phiên đang chạy khi publish** — HT_01 cấm (BR05); không làm.

## 3. Bối cảnh hiện tại (điều C2 phải sửa)

- `tenant/loader.py::get_tenant_context()` là **singleton tiến trình**, build `TenantContext` một lần lúc boot từ bundle đã materialize (slice #1). → C2 cần: resolve **theo version** + cho phép nhiều version cùng tồn tại trong một tiến trình.
- `agent/facade.py::NobleAgent` giữ **một** `TurnRunner` singleton (lazy) build từ `get_tenant_context()`. → C2 cần: **registry runner theo version** + **ghim theo phiên**.
- `materialize.py::materialize_tenant(store, tenant, dest_root)` idempotent theo `bundle_hash`. → C2 tái dùng, nhưng materialize theo **version** (đích `…/<tenant>/versions/<n>/`).
- Hai transport khác nhau về vòng đời cuộc:
  - **LiveKit** (`transport/livekit/worker.py::entrypoint`): **mỗi cuộc = một job** (entrypoint chạy lại mỗi room). Ghim tự nhiên = resolve version tại đầu entrypoint.
  - **aiortc/chat** (`server/…`, facade multiplex): **nhiều phiên trong một tiến trình** → cần map `session_id → version` tường minh.

## 4. Kiến trúc

### 4.1 `tenant/version_resolver.py` (mới) — nguồn version + đệm

```python
class VersionResolver:
    # Được inject store + settings; giữ:
    #   _published: int | None        # version con trỏ đang trỏ (cache, refresh ~20s)
    #   _contexts: dict[int, TenantContext]   # đã materialize + validate, theo version
    #   _last_good: int | None        # version tốt gần nhất đã nạp (cho E04/E01)

    def current_published(self) -> int:
        """Trả version con trỏ (từ cache; poller nền cập nhật). Store lỗi → last_good/đệm đĩa (E01)."""

    def context_for(self, version: int) -> TenantContext:
        """Get-or-build TenantContext cho version:
        materialize versions/<n>/ → KIỂM TỔNG (E04) → build TenantContext (như loader.load_tenant).
        Lệch checksum → raise ChecksumError (caller giữ last_good). Cache theo version."""

    async def start_poller(self) -> None:  # refresh _published mỗi NOBLE_CONFIG_POLL_SEC (nền, best-effort, log-and-continue)
    def stop_poller(self) -> None
```

- **Kiểm tổng (E04):** sau materialize, `bundle_hash(manifest, files)` của thư mục cục bộ phải khớp `version.json.bundle_hash`. Lệch → **không** build context version đó; giữ `_last_good`; ghi `last_error` (SP-D dùng).
- **Đệm đĩa (E01):** materialize ghi `TENANT_MATERIALIZE_DIR/<tenant>/versions/<n>/` (+ marker hash). Khi `current_published()` không đọc được store lúc boot → trả version cao nhất đã có cục bộ.
- **Poll (YC03):** poller CHỈ refresh `_published` (một int — rẻ); **không** materialize sẵn. Materialize xảy ra **lười** khi một cuộc mới thực sự cần version chưa có (giữ đường TTFA sạch).

### 4.2 Facade — registry runner theo version + ghim theo phiên

```python
class NobleAgent:
    _runners: dict[int, TurnRunner]     # theo version
    _session_pin: dict[str, int]        # session_id -> version (ghim, BR05)
    _resolver: VersionResolver

    def _runner_for_session(self, session_id) -> TurnRunner:
        # Lượt ĐẦU của phiên: v = resolver.current_published();
        #   ctx = resolver.context_for(v)  (lệch checksum → lùi last_good)
        #   runner = _runners.get(v) or build_runner(ctx); _session_pin[session_id]=v
        # Lượt SAU: dùng _session_pin[session_id] (KHÔNG resolve lại — BR05)
```

- **Ghim (BR05):** version chốt ở lượt đầu của `session_id`, giữ nguyên tới khi phiên kết thúc/hết TTL.
- **Eviction:** khi không còn `session_id` nào ghim vào version `v` (và `v != current_published`), drop `_runners[v]` để giải phóng bộ nhớ (version đổi hiếm → dict nhỏ). Cơ chế: dọn khi phiên kết thúc (`on_done`/reset) hoặc timer nhẹ.
- `stream_response(session_id, …)` dùng `_runner_for_session(session_id)` thay cho runner singleton hiện tại.

### 4.3 LiveKit entrypoint (ghim per-job, tự nhiên)

`entrypoint(ctx)`: resolve `v = resolver.current_published()` → `context_for(v)` → build/lấy runner cho v → `RoomSession` dùng runner đó. Job sống = cuộc sống ⇒ tự ghim (không cần map session). Prewarm chỉ nạp model (không ghim version — version resolve tại entrypoint).

### 4.4 Config

| Env | Default | Ý nghĩa |
|---|---|---|
| `NOBLE_CONFIG_POLL_SEC` | `20` | Chu kỳ poller refresh con trỏ (YC03). `0` = tắt poll (chỉ resolve lúc boot). |
| `TENANT_MATERIALIZE_DIR` | (đã có) | Gốc đệm đĩa; C2 thêm cây con `versions/<n>/`. |

## 5. Suy biến

| Mã | Tình huống | Hành vi C2 |
|---|---|---|
| E01 | store/backend chết lúc boot | dùng version cao nhất đã materialize cục bộ; nếu chưa có gì → fail loud (không có gì để phục vụ) |
| E03 | published > running | cuộc đang chạy giữ version cũ; cuộc mới lấy mới; `running_version` phơi ra cho SP-D |
| E04 | checksum version mới sai | không nạp version đó; giữ last-good; `last_error` set |
| store lỗi giữa chừng khi poll | poller log-and-continue, giữ `_published` cũ (không rớt cuộc nào) |

## 6. Kế hoạch test (TDD — sẽ chi tiết ở plan)

1. Resolver: `current_published` trả pointer; poller refresh khi pointer đổi.
2. `context_for(n)` materialize + build context đúng; cache (gọi 2 lần không materialize lại).
3. **E04:** version.json.bundle_hash lệch file materialize → `context_for` raise; resolver giữ last_good.
4. **E01:** store ném lỗi ở boot → `current_published` trả version cục bộ cao nhất.
5. **BR05 ghim:** facade — publish version mới giữa hai lượt của cùng `session_id` → lượt sau vẫn dùng version cũ đã ghim; một `session_id` MỚI lấy version mới.
6. Eviction: phiên cuối tham chiếu version cũ kết thúc → `_runners` không còn version cũ.
7. LiveKit entrypoint resolve version tại job start (test bằng fake ctx/resolver).
8. Không hồi quy: facade path hiện tại (một tenant, một version) hành xử như cũ khi chỉ có v1.

## 7. Quyết định mở (chốt khi viết plan)

- **Eviction chính xác:** dọn-khi-phiên-hết vs timer LRU. Đề xuất: dọn khi `on_done`/reset thấy version không còn phiên ghim (đơn giản, đủ vì version đổi hiếm).
- **Materialize lười vs pre-warm:** đề xuất **lười** (poll chỉ giữ int) để không đụng TTFA. Ghi lại nếu sau này cần pre-warm version mới ngầm.

> Ghi chú phụ thuộc: nếu SP-C1 chốt tên method store khác plan (vd `read_pointer`), cập nhật §3–§4 cho khớp trước khi viết plan SP-C2.
