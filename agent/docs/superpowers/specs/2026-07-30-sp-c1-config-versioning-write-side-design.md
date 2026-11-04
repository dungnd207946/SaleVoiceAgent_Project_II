# SP-C1 — Config Versioning (Write Side) — Design

**Slice:** SP-C, nửa **ghi** (draft → publish → immutable version + pointer → rollback).
**Ngày:** 2026-07-30 · **Branch:** `feat/agent` · **Contract:** [C2 trong odyssey-agent-interface-contract](../../api/odyssey-agent-interface-contract.md).

Hiện thực hoá luồng A phía Backend/provisioning trên **tenant store** (MinIO/S3). Vì Odyssey
chưa có repo Backend riêng, phần "Xuất bản" tạm sống trong repo này dưới dạng library +
CLI `noble-tenant` (đồng nhất với slice #1/#2). Nửa **đọc** phía agent (nạp-ghim-version-theo-cuộc)
là **SP-C2**, ngoài phạm vi tài liệu này.

## 1. Mục tiêu (map HT_01)

| YC/BR | Ý nghĩa | Cách đáp ứng ở C1 |
|---|---|---|
| YC01 | Sửa cấu hình → lưu **bản nháp**, chưa ai thấy | `save_draft` ghi `<tenant>/draft/` (mutable), KHÔNG đụng version đang phục vụ |
| YC02 / BR06 | **Xuất bản** → phiên bản **bất biến**, số **tăng dần**, không ghi đè | `publish` snapshot draft → `versions/<n>/` (không bao giờ ghi đè); `n` đơn điệu |
| YC06 / BR06 | Quay lui bất kỳ bản cũ nào bằng một thao tác | `rollback(n)` = ghi `pointer.json`→`n`, **KHÔNG** tạo version mới |
| BR04 | Mọi thay đổi qua Xuất bản, không sửa thẳng bản đang chạy | Bản đang phục vụ = version pointer trỏ tới; chỉ `publish`/`rollback` đổi pointer |
| BR07 | Ghi **snapshot trước, con trỏ sau**, cùng giao dịch logic | `publish` ghi `versions/<n>/` hoàn tất → mới ghi `pointer.json` |
| E08 | Cổng kiểm **cấu trúc** trước khi phát | `publish` chạy `validate_bundle` trên draft; fail → không snapshot, không đổi pointer |

## 2. Non-goals (C1)

- **Nạp phía agent / ghim version theo cuộc / dò 20s / đệm đĩa** → SP-C2.
- **`field_policy` (cột nào agent được đọc)** — thuộc data-plane SP-E; `version.json` để sẵn field nhưng C1 để `null`. BR07 "config + field-policy cùng giao dịch" ở C1 chỉ có phần config.
- **Test hành vi (24 kiểm thử)** — KHÔNG gộp vào cổng publish (§II.2.2 HT_01): publish chỉ kiểm **cấu trúc** (rẻ, đồng bộ).
- **UI diff/wireframe** — Dashboard.

## 3. Layout kho (versioned)

```
<tenant_id>/draft/manifest.toml          # bản nháp (mutable) — save_draft ghi vào đây
<tenant_id>/draft/persona/*
<tenant_id>/draft/tools/*
<tenant_id>/versions/<n>/manifest.toml    # snapshot BẤT BIẾN của version n
<tenant_id>/versions/<n>/persona/*
<tenant_id>/versions/<n>/tools/*
<tenant_id>/versions/<n>/version.json     # {version, bundle_hash, created_at, created_by, parent_version, field_policy:null}
<tenant_id>/pointer.json                  # {published_version:int, updated_at, updated_by}
<tenant_id>/_meta.json                    # {tenant_id, status, published_version, latest_version, bundle_hash, created_at, updated_at}
<tenant_id>/_creds.json                   # C5 — không đổi, không thuộc bundle_hash
```

- `bundle_hash` (đã có) tính trên manifest + files (path-sorted), là **checksum của version** (SP-C2/E04 dùng lại).
- `_meta.json.bundle_hash` = hash của **version đang publish** (để `materialize` idempotent + gateway `is_active` chạy nguyên).

## 4. Mô hình dữ liệu

- **`TenantMeta`** (mở rộng, giữ tương thích field cũ): thêm `published_version:int`, `latest_version:int`. Giữ `version:int` như **alias của `published_version`** để code cũ (gateway/loader) không vỡ; `bundle_hash` = hash version đang publish.
- **`VersionInfo`** (mới, frozen): `tenant_id, version:int, bundle_hash, created_at, created_by, parent_version:int|None, field_policy:None`.
- **Pointer** (dict JSON): `{published_version:int, updated_at, updated_by}`.

## 5. Store API (thêm vào `TenantStore` Protocol + Fake + Minio)

```python
read_pointer(tenant_id) -> int | None                 # published_version, None nếu chưa publish/legacy
write_pointer(tenant_id, version, *, updated_at, updated_by) -> None
list_versions(tenant_id) -> list[int]                 # sorted tăng dần
read_version_bundle(tenant_id, version) -> Bundle | None
write_version_bundle(tenant_id, version, bundle, version_info) -> None   # ghi versions/<n>/ + version.json (idempotent-fail nếu đã tồn tại)
read_draft(tenant_id) -> Bundle | None                # <tenant>/draft/
write_draft(tenant_id, bundle) -> None
```

**Tương thích (KHÔNG đổi chữ ký):**
- `read_bundle(tenant)` → nếu có pointer: trả `read_version_bundle(tenant, pointer)`; **không có pointer (legacy in-place)**: trả bundle in-place hiện tại (coi là v1). **Không bao giờ trả draft.**
- `read_meta(tenant)` → `status` + `published_version` (= pointer, hoặc 1 nếu legacy) + `latest_version` + `bundle_hash`(của version publish).
- `list_ids`, `read_creds_raw`/`write_creds_raw` không đổi.

> Ràng buộc immutability ở `write_version_bundle`: nếu `versions/<n>/version.json` đã tồn tại → raise (không ghi đè — BR06). `publish` luôn cấp `n = latest_version + 1`.

## 6. Provisioning API (`tenant/provisioning.py`)

```python
save_draft(store, tenant_id, *, manifest_text=None, files=None, now=None) -> None
    # ghi/replace <tenant>/draft/. KHÔNG validate (nháp được phép hỏng). Tenant phải tồn tại.

publish(store, tenant_id, *, created_by="", now=None) -> VersionInfo
    # 1) đọc draft (không draft → ValueError)
    # 2) validate_bundle(draft)  -- CỔNG KIỂM CẤU TRÚC (E08); fail → ValueError, KHÔNG ghi gì
    # 3) n = latest_version + 1; write_version_bundle(tenant, n, draft_bundle, VersionInfo(...))
    # 4) write_pointer(tenant, n)   -- SAU khi (3) xong (BR07)
    # 5) cập nhật _meta (published_version=n, latest_version=n)

rollback(store, tenant_id, version, *, updated_by="", now=None) -> int
    # version phải ∈ list_versions (else ValueError). write_pointer(tenant, version). KHÔNG tạo version mới (BR06/YC06).
    # cập nhật _meta.published_version. latest_version giữ nguyên.

list_versions(store, tenant_id) -> list[int]
get_version(store, tenant_id, version) -> Bundle
diff_versions(store, tenant_id, a, b) -> {"added":[...],"removed":[...],"changed":[...]}   # path-level
```

**`create_tenant` / `import_from_package` đổi để dùng layout versioned:**
- `create_tenant(..., status="draft")`: ghi **draft**; nếu `status="active"` (import path) thì publish luôn v1 (draft → versions/1 → pointer→1). Giữ validate trước khi publish.
- `import_from_package(tenant, status="active")`: đọc bundle package → `save_draft` → `publish` (v1) → `set_status(active)`. Kết quả: `noble`/`demo_acme` mới import sẽ có `versions/1/` + `pointer.json`.
- `update_tenant`: **deprecate đường ghi-đè cũ** → chuyển thành `save_draft` (không tự bump published version). *Publish là bước riêng.* Giữ hàm cho tương thích test nhưng đổi ngữ nghĩa: ghi draft, không đổi pointer.
- `set_status`/`disable_tenant`: không đổi (chỉ sửa `_meta.status`).

## 7. CLI (`tenant/cli.py`, console `noble-tenant`)

Thêm: `save-draft <tenant> <dir>` (đọc thư mục local → draft) · `publish <tenant> [--by NAME]` · `rollback <tenant> <n> [--by NAME]` · `list-versions <tenant>` · `diff <tenant> [<a> <b>]` (mặc định draft↔published). Giữ nguyên các lệnh cũ.

## 8. Tương thích ngược & migration

- **Read-compat (quyết định #3):** tenant chưa có `pointer.json` (đã provision in-place ở slice #1 — `noble`, `demo_acme`) → `read_bundle`/`read_meta` coi bundle in-place là **v1**; `read_pointer` trả `None`; `list_versions`→`[1]`. Không cần lệnh migrate; các tenant cũ vẫn load + smoke chạy nguyên.
- **Gateway** (`registry.is_active` = `read_meta().status`) và **loader/materialize** (`read_bundle` + `read_meta().bundle_hash`) **không sửa** — chúng thấy version đang publish qua đúng chữ ký cũ.
- **Đề xuất tái-provision** (không bắt buộc): `noble-tenant import-from-package noble` sau khi xoá tenant cũ sẽ nâng `noble` lên layout versioned; hoặc để read-compat gánh. Không nằm trong scope code C1.

## 9. Lỗi & biên

| Tình huống | Hành vi |
|---|---|
| `publish` khi không có draft | `ValueError("no draft to publish")` |
| `publish` với draft hỏng cấu trúc | `ValueError("bundle invalid: …")`, KHÔNG ghi version/pointer (E08) |
| `write_version_bundle` version đã tồn tại | raise (bất biến, BR06) |
| `rollback` tới version không tồn tại | `ValueError("no such version")` |
| MinIO lỗi thật (không phải NoSuchKey) | raise (fail loud, không đọc nhầm thành "not found") — giữ `_is_missing` hiện có |
| `read_bundle` khi có pointer nhưng version bị thiếu | raise (dữ liệu hỏng, không im lặng fallback) |

## 10. Kế hoạch test (TDD, offline với `FakeTenantStore`)

1. `publish`: draft hợp lệ → `versions/1/` tồn tại + `version.json` đúng + pointer=1 + `_meta.published_version=1`; publish lần 2 → version 2, pointer=2, version 1 **vẫn nguyên** (bất biến).
2. `publish` gọi validate: draft thiếu tool/persona → `ValueError`, không tạo version, pointer không đổi.
3. BR07 order: pointer chỉ trỏ version sau khi snapshot ghi xong (giả lập lỗi giữa (3) và (4) → pointer chưa đổi, version thừa nhưng không được phục vụ).
4. `rollback`: pointer về 1, `latest_version` vẫn 2, **không** tạo version 3.
5. `read_bundle` trả version đang publish, **không** trả draft; sau `save_draft` mới, `read_bundle` vẫn trả published cũ.
6. **Read-compat:** store legacy (chỉ in-place, không pointer) → `read_bundle`=in-place, `read_pointer`=None, `list_versions`=[1]; gateway `is_active` + `materialize` vẫn chạy.
7. `write_version_bundle` trùng version → raise.
8. `diff_versions` path-level đúng (added/removed/changed).
9. CLI: `publish`/`rollback`/`list-versions` end-to-end trên FakeStore.
10. **Không hồi quy:** full `tests/unit/tenant` + `tests/unit/gateway` xanh; import path (`import_from_package`) tạo được layout versioned.

## 11. Verify (sau code)

- `make test-unit` phần `tenant`+`gateway`: 0 new failure.
- `ruff` sạch trên file đụng.
- **Live re-smoke:** re-provision `noble` (versioned) → `smoke_gateway_chat.py` vẫn PASS (loader materialize version đang publish); `list-versions noble` = `[1]`; `save-draft`→`publish`→`list-versions`=`[1,2]`→`rollback 1`→pointer=1.
