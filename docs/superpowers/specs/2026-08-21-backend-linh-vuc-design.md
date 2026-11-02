# Backend màn «Quản lý lĩnh vực» — `/api/v1/linh-vuc`

**Ngày:** 2026-08-21 · **Nhánh:** `feat/linh-vuc-backend` (từ `develop` @ `a97f055`)

## 1. Bối cảnh

Màn `/domains` («Quản lý lĩnh vực», repo frontend) gọi `GET/PATCH
/api/v1/linh-vuc` — hợp đồng do FE ĐỊNH TRƯỚC từ 2026-08-08
(`features/agent/linhVuc.ts`), backend chưa bao giờ có, màn chỉ chạy dưới
`VITE_MSW=1`. Đây là màn 404 cuối cùng trong hai màn được báo hỏng 2026-08-20
(`/kb` đã dựng lại, merge `a97f055`).

Phát hiện quyết định thiết kế: backend ĐÃ CÓ bảng đúng nghĩa —
`control.tenant_verticals` (migration `0002`, PK `(tenant_id, vertical)`,
CHECK `vertical IN ('realestate','finance')`), docstring của
`workspace/repo.them_vertical` tự mô tả là *«lĩnh vực đang bật của
workspace»*. Đường ghi duy nhất hiện nay: `workspace/service.tao()` chèn
`realestate` lúc tạo workspace. Không cần bảng mới.

## 2. Hợp đồng HTTP (đóng băng theo FE — FE không sửa dòng nào)

| | |
|---|---|
| `GET /api/v1/linh-vuc` | 200, **mảng JSON trần** (không envelope): `[{ma, ten, bat, soKyNang, coDuLieu}]`, thứ tự cố định `bds` rồi `taichinh` |
| `PATCH /api/v1/linh-vuc/{ma}` | body `{"bat": bool}` (`extra="forbid"`) → 200 MỘT object cùng hình dạng; idempotent |
| `ma` lạ | 404 `LINH_VUC_KHONG_TON_TAI` |
| body sai | 422 (pydantic) |
| Quyền | GET require(AGENT_CONFIG_READ); PATCH require(AGENT_CONFIG_WRITE) — bật/tắt lĩnh vực là sửa hành vi agent. ⚠️ Nav FE thật gate /domains bằng CATALOG_WRITE (features/realestate/nav.ts), nên vai «Biên tập» thấy màn nhưng PATCH sẽ 403 (thiếu agent_config.write) — hành vi chấp nhận (ẩn nút không phải bảo vệ, PQ_01 §BR-Q03), FE có thể disable toggle sau. |

Trường (camelCase đúng như FE khai): `ma: str` · `ten: str` · `bat: bool` ·
`soKyNang: int` · `coDuLieu: bool`.

## 3. Sổ lĩnh vực — hằng trong module, KHÔNG cho tenant tự thêm

Khớp quyết định FE (docstring `QuanLyLinhVuc.tsx`: sổ là hằng số của sản
phẩm). Hai dòng, cần ánh xạ vì FE nav dùng `bds`/`taichinh` còn CHECK của DB
chỉ nhận `realestate`/`finance` — đổi phía nào cũng đắt hơn bảng ánh xạ:

| `ma` (FE) | `ten` | `vertical` (DB) | `soKyNang` | `coDuLieu` |
|---|---|---|---|---|
| `bds` | Bất động sản | `realestate` | `len(TEN_KY_NANG) − len(KY_NANG_CHUNG)` = 9 | EXISTS dự án published, loại sentinel (§5) |
| `taichinh` | Tài chính | `finance` | 0 | hằng `False`, không query |

`KY_NANG_CHUNG = frozenset({"kb_search", "update_customer", "escalate"})` khai
trong module này (backend chưa có khái niệm đó; FE cũng tự khai ở
`kyNang.ts`). Test đối chiếu `KY_NANG_CHUNG ⊆ TEN_KY_NANG` (import qua mặt
tiền `config.contracts` — đường import chéo hợp lệ, `ops/router.py` đã đi).

⚠️ Công thức `soKyNang` của bds là «mọi kỹ năng không-chung» — hôm nay đúng vì
cả 9 kỹ năng còn lại đều là BĐS (FE suy y hệt: `KY_NANG_TAB_BDS = 12 −
chung`). Ngày sổ kỹ năng mọc kỹ năng finance thì công thức này gán nhầm nó cho
bds — lúc đó phải chuyển sổ sang gắn nhãn lĩnh vực từng kỹ năng (ghi trong
docstring sổ).

## 4. Trạng thái bật/tắt = SỰ HIỆN DIỆN của hàng

- `bat = true` ⟺ tồn tại hàng `(tenant_id, vertical)` trong
  `control.tenant_verticals`.
- PATCH bật → `INSERT … ON CONFLICT DO NOTHING`; tắt → `DELETE`. Cả hai
  idempotent, không có trạng thái lỗi «đã bật rồi».
- `enabled_at` đổi khi tắt rồi bật lại — chấp nhận, không ai đọc mốc đó.
- `control.*` không có RLS (cố ý, `0908`): mọi SQL mang vị từ
  `tenant_id = $1` với tenant lấy từ `Principal` — cùng luật đầu file
  `config/router.py` («tenant_id LUÔN lấy từ Principal, KHÔNG từ path/body»).
- Nhật ký: `linh_vuc.bat` / `linh_vuc.tat`, `chi_tiet={"ma": …}`, qua
  `nhat_ky.ghi(conn, tenant, hanh_dong, user_id, chi_tiet)` — CÙNG transaction
  với INSERT/DELETE, ghi SAU khi câu lệnh chính chạy.

## 5. `coDuLieu` của bds

Qua `tenant_conn(tenant_id)`, một câu EXISTS:

```sql
SELECT EXISTS(
  SELECT 1 FROM tenant_data.projects
  WHERE tenant_id = portal.current_tenant()
    AND status = 'published'
    AND project_code <> '__ALL__'
)
```

- Vị từ literal `tenant_id = portal.current_tenant()` — cổng cách ly đọc TĨNH
  f-string, không expand biến.
- **Loại sentinel bắt buộc**: `__ALL__` là row hệ thống LUÔN published ở mọi
  tenant (provisioning tạo, `SENTINEL_PROTECTED` chặn xoá) — không loại thì
  mọi tenant đều «đã có dữ liệu» và trường này thành hằng. So bằng hằng
  `SENTINEL_TENANT` import từ mặt tiền `realestate.contracts` (đã export),
  nhưng chuỗi trong SQL phải là literal `'__ALL__'` (f-string tĩnh) — test
  đối chiếu hằng với literal.
- Chỉ xét `projects`: nó neo cả cây (units/zones/documents đều FK về nó),
  «có dự án published» là điều kiện cần và đủ để agent tra được gì đó.

## 6. Migration `0944_backfill_tenant_verticals`

```sql
INSERT INTO control.tenant_verticals (tenant_id, vertical)
SELECT id, 'realestate' FROM control.tenants
ON CONFLICT DO NOTHING
```

- **Vì sao bắt buộc:** `them_vertical` chỉ chạy từ 2026-08-15; tenant tạo
  trước đó (anphu, sunrise…) không có hàng. Thiếu backfill thì ship xong,
  `GET` trả `bat=false` cho bds và khối BĐS **biến khỏi nav** của mọi
  workspace cũ ngay lập tức — một regression nhìn thấy được bằng mắt.
- Mọi tenant hiện hữu đều là tenant BĐS (`VERTICAL_MAC_DINH='realestate'`,
  `ConfigPayload.pham_vi.linh_vuc = Literal["realestate"]`) — bật mặc định
  đúng với hành vi họ đang thấy (MSW fake cũng seed `bds.bat=true`).
- Literal `'realestate'` viết thẳng trong migration, KHÔNG import `portal.*`
  (luật đóng băng migration).
- `downgrade` **no-op có ghi chú**: không phân biệt được hàng backfill với
  hàng `them_vertical` ghi thật — xoá là tắt nhầm lĩnh vực người ta đang bật.
- `down_revision = "0943_hop_nhat_hai_head"` (head duy nhất hiện tại — đã
  kiểm `alembic heads`).

## 7. Không side effect — ranh giới cố ý

- **Không đụng agent/config**: gating kỹ năng vẫn ở FE lúc «Lưu và áp dụng»
  (`useBanNhap.locKyNangTheoLinhVuc`) — đúng thiết kế FE đã chốt. Backend chỉ
  là sổ trạng thái.
- **Cổng nạp KHÔNG bị chặn khi tắt lĩnh vực**: ingest xác thực bằng
  `ingest_tokens.vertical`, không đọc `tenant_verticals`. Tắt = agent không
  trả lời, dữ liệu vẫn nạp được — hành vi chấp nhận, ghi rõ ở đây để khỏi
  «sửa» nhầm.
- Không đổi `contracts/` (không chạm `actions.py`/`tools.py` ⇒ không cần
  `make contracts`).

## 8. Cấu trúc module `modules/linh_vuc/`

```
router.py     ROUTER prefix="/linh-vuc" (registry tự quét); 2 route; lỗi 404 khai tại file
contracts.py  LinhVucOut (5 trường camelCase) · DatLinhVucIn (extra="forbid")
so.py         SO_LINH_VUC (NamedTuple ma/ten/vertical) · KY_NANG_CHUNG · so_ky_nang()
repo.py       doc_verticals(conn, tenant_id) → set[str] · bat()/tat() · co_du_lieu_bds(conn)
```

Không `service.py` — hai endpoint, luồng thẳng, router gọi repo (khuôn ngắn
hơn `config` vì không có state machine nào).

## 9. Kiểm chứng

- **Unit** (`tests/modules/linh_vuc/test_so.py`): `KY_NANG_CHUNG ⊆
  TEN_KY_NANG`; ánh xạ `vertical` ⊆ tập CHECK của `0002` (literal trong test);
  `so_ky_nang('bds') == 9` hôm nay.
- **Router** (`test_linh_vuc_router.py`, khuôn gọi handler trực tiếp +
  `Principal` như `tests/modules/kb/`): GET sau backfill → bds `bat=true`,
  taichinh `bat=false`, đúng thứ tự; PATCH tắt → GET đọc lại `false`; PATCH
  bật lại idempotent (gọi hai lần); 404 `ma` lạ; 422 body thừa khoá;
  `coDuLieu=false` khi tenant chỉ có sentinel, `true` khi thêm một dự án
  published, `false` khi dự án chỉ ở draft; cách ly: A tắt không đổi B; nhật
  ký có hàng `linh_vuc.tat` sau PATCH.
- **Migration**: chạy `alembic upgrade head` trên DB dev thật; tenant cũ có
  hàng `realestate`; chạy lại không nổ (ON CONFLICT).
- **Cổng repo**: `make test-isolation` sạch; `test_moi_route_khai_action`
  tự quét 2 route mới; `make check` không thêm đỏ mới so với baseline develop.
- **E2E tay**: FE `VITE_MSW=0` mở `/domains` — danh sách hiện, công tắc đổi
  và giữ sau reload, khối BĐS rời panel khi tắt.

## 10. Việc kèm

- Docstring `workspace/repo.py` (đầu file + `them_vertical`): ghi nhận
  `modules/linh_vuc` là người ghi thứ hai của `tenant_verticals`.
- CLAUDE.md backend: một dòng Change Log.
- Memory/FE không đổi; cập nhật memory note «/domains chưa có backend» sau
  khi merge.
