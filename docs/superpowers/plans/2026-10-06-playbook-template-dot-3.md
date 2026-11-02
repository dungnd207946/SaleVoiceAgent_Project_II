# Playbook template — Đợt 3: màn `/kich-ban` sửa được — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trên `/kich-ban`, người có `agent_config.write` sửa / thêm / xoá / bật-tắt tình huống lớp sale, so với mẫu NobleX, áp lại mẫu và bật kịch bản theo role — gọi API đợt 2 (+ một trường `gioiHan` ở BE).

**Architecture:** Một MR BE nhỏ trả `gioiHan` trong `GET /playbook/template`. FE gói trong module `features/kich-ban`: lớp dữ liệu (`api.ts` + fake MSW có trạng thái), logic thuần (`khuon.ts`), một đường ghi (`useGhi.ts`: dựng bộ sale từ `GET /playbook` mới nhất → biến đổi → kiểm → `PUT` cả bộ với `version`), và các component: dải trạng thái + công tắc role, thao tác trên tình huống, form sửa/thêm trong khung chi tiết, khung so với mẫu.

**Tech Stack:** React 19 + TanStack Router/Query v5 + Tailwind v4 + vitest/RTL + MSW 2 (FE); FastAPI + pydantic v2 + pytest (BE).

**Spec:** `docs/superpowers/specs/2026-10-06-playbook-template-dot-3-design.md` (repo FE, worktree `.wt-fe-kichban-sua`). Nền: spec đợt 1/2 ở repo `odyssey-agent` `docs/superpowers/specs/2026-10-06-playbook-template-dot-{1,2}-design.md`.

## Global Constraints

- FE: worktree `/Users/noblex-thebc-mac/Developer/noble-projects/odyssey/.wt-fe-kichban-sua`, nhánh `feat/kich-ban-sua` (tách từ `origin/develop`, đã gỡ upstream). BE: worktree `/Users/noblex-thebc-mac/Developer/noble-projects/odyssey/.wt-portal-playbook-json`, nhánh MỚI `feat/playbook-template-gioi-han` tách từ `origin/develop`.
- Không push, không merge, không đụng `develop`. Commit theo task, `git add` từng tệp cụ thể. Mỗi commit kết thúc bằng hai dòng:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` và `Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1`.
- Lệnh test FE (máy dev là Node 24 — thiếu cờ là ~210 bài đỏ vì `localStorage`): `NODE_OPTIONS=--no-experimental-webstorage npx vitest run <tệp>`. Typecheck: `npx tsc -b` (KHÔNG `--noEmit` — cổng rỗng). Lint: `npx eslint . --max-warnings 0`. Prettier: `npx prettier --write <tệp đã đụng>` trước commit (repo có nợ định dạng cũ — chỉ định dạng tệp mình đụng).
- Lệnh test BE: `.venv/bin/python -m pytest tests/modules/playbook -q -p no:cacheprovider` (PG local cổng 5444, đã ở `0976_kich_ban`).
- Payload `PUT /playbook` chỉ mang khoá `NutVao`: `id, ten, nhom, bat, kenh, dau_hieu, lam, tool, cam, khi_thieu, cau_ket, lan_2, chi_lan_2, nguon, buoc[{id, lam}]` (BE `extra="forbid"`), dựng từ `nodes` của `GET /playbook` mới nhất.
- Con số giới hạn đọc từ `gioiHan` (`GET /playbook/template`), không chép tay. Thiếu `gioiHan` ⇒ nút ghi khoá với `title` «Không tải được giới hạn kịch bản — tải lại trang».
- Quyền ghi: `useSession().can([ACTIONS.AGENT_CONFIG_WRITE])`. Không có ⇒ không render nút ghi; công tắc role hiện dạng khoá.
- Luật portal (`CLAUDE.md` FE): hộp xác nhận = `HopThoai` + `HANG_NUT` (nút chính cuối, không `confirm()`); ô nhập = primitive `components/ui/Truong.tsx`; công tắc = `CongTac`; màu/viền/cỡ chữ chỉ qua token; nút tự dựng mang `cursor-pointer`; bản xem và form cùng mục/thứ tự/nhãn (`NHAN_TRUONG`).
- Chữ trên màn: không mã snake_case; «Đang tắt — agent không chọn» thay «Bản nháp»; «khác bản mẫu hiện tại» (BE không giữ mẫu lúc áp dụng).
- Không sửa `components/shell/*`, `lib/nav-registry.ts`.

## Review Focus

1. Hai cú bấm ghi liền nhau (công tắc «Đang dùng» bấm hai lần nhanh) — lần ghi sau không được cầm `version` cũ (không 409 do chính mình) → test ở Task 6.
2. `roleDung` còn mang role workspace đã xoá ở `/agent` — bấm công tắc role khác không được gửi lại role đó (BE trả 422) → test ở Task 5.
3. Chữ có emoji / ký tự ngoài BMP — đếm độ dài theo code point như `len()` Python, không theo `.length` UTF-16 → test ở Task 3.
4. Nút mang tool agent đã gỡ (không còn trong `gioiHan.tool`) — form không hiện được nó nên phải bỏ lúc mở, không để `kiemNut` báo lỗi người dùng không gỡ được → test ở Task 7.
5. Xoá chính tình huống đang mở — xoá xong khung chi tiết phải đóng, không treo ở «Tình huống này không còn trong kịch bản» → test ở Task 6.

---

### Task 1: BE — `GET /playbook/template` trả thêm `gioiHan`

**Files:**
- Modify: `src/portal/modules/playbook/contracts.py` (class `TemplateOut`)
- Modify: `src/portal/modules/playbook/router.py` (hàm `xem_template`)
- Test: `tests/modules/playbook/test_kich_ban_api.py`
- Modify: `CLAUDE.md` (bảng `## Change Log`)

**Interfaces:**
- Consumes: `nut.gioi_han() -> dict` (có sẵn, `modules/playbook/nut.py`).
- Produces: `GET /api/v1/playbook/template` → `{templateVersion: str, nodes: list[dict], gioiHan: dict}` — FE Task 2 đọc `gioiHan` (khoá: `nhom, kenh, tool, khoaXoa, khuonId, khuonIdRieng, maxNut, maxTen, maxTool, maxDong{dau_hieu,lam,cam}, maxBuoc, maxKyTu, maxDauHieuTong, maxCamTong, maxCau`).

- [ ] **Step 1: Tạo nhánh từ develop**

```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/.wt-portal-playbook-json
git status --short   # phải rỗng
git fetch -q origin && git switch -c feat/playbook-template-gioi-han origin/develop && git branch --unset-upstream
```

- [ ] **Step 2: Viết test fail** — thêm vào cuối `tests/modules/playbook/test_kich_ban_api.py`:

```python
async def test_template_tra_gioi_han(client_pb):
    d = (await client_pb.get("/api/v1/playbook/template")).json()
    assert d["gioiHan"] == nut.gioi_han()
```

- [ ] **Step 3: Chạy để thấy fail**

Run: `.venv/bin/python -m pytest tests/modules/playbook/test_kich_ban_api.py -q -p no:cacheprovider -k gioi_han`
Expected: FAIL — `KeyError: 'gioiHan'`.

- [ ] **Step 4: Cài đặt**

`contracts.py`, class `TemplateOut`:

```python
class TemplateOut(BaseModel):
    model_config = ConfigDict(frozen=True)
    templateVersion: str
    nodes: list[dict]
    gioiHan: dict  # luật agent xuất trong playbook.json — FE dựng form theo đây (đợt 3)
```

`router.py`, thân `xem_template`:

```python
    bo = _bo_nut()
    return TemplateOut(templateVersion=bo["templateVersion"], nodes=nut.template_sale(), gioiHan=nut.gioi_han())
```

- [ ] **Step 5: Chạy lại cả module**

Run: `.venv/bin/python -m pytest tests/modules/playbook -q -p no:cacheprovider`
Expected: PASS toàn bộ (71 + 1).

- [ ] **Step 6: Ruff + Change Log + commit**

Thêm một hàng ngay dưới dòng `|---|---|` của bảng `## Change Log` trong `CLAUDE.md`:

```markdown
| 2026-10-06 | **`GET /playbook/template` trả thêm `gioiHan`** (playbook template đợt 3). FE `/kich-ban` dựng form sửa tình huống theo khối này (danh sách nhóm/kênh/tool, trần ký tự, `maxNut`) thay vì chép tay số — luật vẫn do agent xuất trong `playbook.json`, BE `kiem.py` vẫn là chốt chặn 422. Chỉ THÊM trường. |
```

```bash
.venv/bin/ruff check src/portal/modules/playbook tests/modules/playbook && .venv/bin/ruff format --check src/portal/modules/playbook tests/modules/playbook
git add src/portal/modules/playbook/contracts.py src/portal/modules/playbook/router.py tests/modules/playbook/test_kich_ban_api.py CLAUDE.md
git commit -m "feat(playbook): GET /playbook/template trả gioiHan cho form sửa kịch bản (đợt 3)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1"
```

---

### Task 2: FE — lớp dữ liệu: kiểu, hàm ghi, fake có trạng thái, search param

**Files:**
- Modify: `src/features/kich-ban/api.ts`
- Create: `src/features/kich-ban/khuon.ts`
- Modify (thay toàn bộ): `src/features/kich-ban/msw.ts`
- Modify: `src/routes/_app/kich-ban.tsx`
- Modify: `tests/kich-ban-logic.test.ts`, `tests/kich-ban-chi-tiet.test.tsx` (fixture đổi: `chot` chuyển sang `chuyen_that` qua `lan_2`)
- Test: `tests/kich-ban-ghi.test.ts` (mới)

**Interfaces:**
- Consumes: BE `GET/PUT /playbook`, `GET /playbook/template`, `POST /playbook/ap-dung`, `PUT /playbook/role-dung` (đợt 2 + Task 1).
- Produces (các task sau dùng):
  - `api.ts`: `class LoiApi { code: string; message: string; fields: readonly LoiTruong[] }`; `interface LoiTruong { field: string; reason: string }`; `interface NutVao`, `BuocVao`, `GioiHan`, `KichBan`, `TemplateKichBan { templateVersion: string; nodes: NutKichBan[]; gioiHan?: GioiHan | undefined }`; `NutKichBan` thêm `lop: 'sale' | 'he_thong'; hash: string; khoaXoa: boolean; bat: boolean; lan_2: string; chi_lan_2: boolean; cau_ket: string`; `DuLieuKichBan.kichBan: KichBan`; hàm `taiTemplate()`, `luuKichBan({version, nut})`, `apDungMau(version)`, `datRoleDung({version, roles})`; hook `useTemplate()` (key `['kich-ban-template']`), `useGhiKichBan() → { luu, apDung, roleDung }` (mutation; thành công thì chờ làm mới `['kich-ban']`; 409 `PLAYBOOK_DA_DOI` thì làm mới `['kich-ban']`; 422 `PLAYBOOK_ROLE_KHONG_CO` thì làm mới `['config']`).
  - `khuon.ts`: `veKhuon(n: NutKichBan): NutVao`, `laSale(n)`, `boSale(nodes): NutVao[]`, `heThong(nodes): NutKichBan[]`.
  - `msw.ts`: `FAKE_KICH_BAN: DuLieuKichBan`, `FAKE_LUOT`, `GIOI_HAN_GIA: GioiHan` (khoaXoa chỉ `che_dat`, `che_dat_downsell`), `TEMPLATE_VERSION_GIA = 'tv-mau-1'`, `MAU_GIA: NutVao[]` (thứ tự `che_dat, che_dat_downsell, chot, goi_dien_ra`), `GHI_GIA: { duong: string; body: unknown }[]`, `datLaiKichBanGia(p?: Partial<{nut, roleDung, version, tuTemplate}>)`, `epLoiGhiKichBanGia(status, body)`, `hashGia(n: NutVao)`, `kichBanHandlers`.
  - Route `/_app/kich-ban` search: thêm `so?: 'mau' | undefined`, `them?: true | undefined`.

- [ ] **Step 0: Cài phụ thuộc trong worktree**

```bash
cd /Users/noblex-thebc-mac/Developer/noble-projects/odyssey/.wt-fe-kichban-sua && npm ci
```

- [ ] **Step 1: Viết test fail** — tạo `tests/kich-ban-ghi.test.ts`:

```ts
import { beforeEach, describe, expect, it } from 'vitest'
import {
  LoiApi,
  apDungMau,
  datRoleDung,
  luuKichBan,
  taiKichBan,
  taiTemplate,
} from '@/features/kich-ban/api'
import { boSale, veKhuon } from '@/features/kich-ban/khuon'
import { FAKE_KICH_BAN, datLaiKichBanGia, epLoiGhiKichBanGia } from '@/features/kich-ban/msw'

beforeEach(() => datLaiKichBanGia())

describe('veKhuon — nút GET thành khuôn PUT', () => {
  it('chỉ đúng các khoá NutVao, bước không mang tool', () => {
    const n = FAKE_KICH_BAN.nodes.find((x) => x.id === 'chot')!
    const v = veKhuon(n)
    expect(Object.keys(v).sort()).toEqual([
      'bat', 'buoc', 'cam', 'cau_ket', 'chi_lan_2', 'dau_hieu', 'id', 'kenh', 'khi_thieu', 'lam',
      'lan_2', 'nguon', 'nhom', 'ten', 'tool',
    ])
    expect(v.buoc[0]).toEqual({ id: n.buoc[0]!.id, lam: n.buoc[0]!.lam })
  })

  it('boSale bỏ nút hệ thống', () => {
    expect(boSale(FAKE_KICH_BAN.nodes).map((n) => n.id)).toEqual([
      'che_dat', 'che_dat_downsell', 'chot', 'goi_dien_ra',
    ])
  })
})

describe('API ghi kịch bản (qua fake)', () => {
  it('chưa áp dụng: trạng thái mẫu, version 0, chỉ customer', async () => {
    const d = await taiKichBan(7)
    expect(d.kichBan).toMatchObject({ trangThai: 'mau', version: 0, roleDung: ['customer'] })
  })

  it('PUT lưu thành bản riêng; chỉ nút đổi mới đổi hash', async () => {
    const d = await taiKichBan(7)
    const bo = boSale(d.nodes).map((n) => (n.id === 'chot' ? { ...n, lam: ['chữ mới'] } : n))
    expect(await luuKichBan({ version: 0, nut: bo })).toMatchObject({ trangThai: 'rieng', version: 1 })
    const sau = await taiKichBan(7)
    const h = (x: typeof d, id: string) => x.nodes.find((n) => n.id === id)!.hash
    expect(sau.nodes.find((n) => n.id === 'chot')!.lam).toEqual(['chữ mới'])
    expect(h(sau, 'chot')).not.toBe(h(d, 'chot'))
    expect(h(sau, 'che_dat')).toBe(h(d, 'che_dat'))
  })

  it('version lệch → LoiApi PLAYBOOK_DA_DOI', async () => {
    await expect(luuKichBan({ version: 5, nut: [] })).rejects.toMatchObject({
      code: 'PLAYBOOK_DA_DOI',
    })
  })

  it('422 mang fields', async () => {
    epLoiGhiKichBanGia(422, {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'x',
        fields: [{ field: 'body.nut[0].lam', reason: 'tối đa 6 dòng' }],
      },
    })
    const e = await luuKichBan({ version: 0, nut: [] }).catch((x: unknown) => x)
    expect(e).toBeInstanceOf(LoiApi)
    expect((e as LoiApi).fields).toEqual([{ field: 'body.nut[0].lam', reason: 'tối đa 6 dòng' }])
  })

  it('áp lại mẫu rồi đặt role', async () => {
    await apDungMau(0)
    expect(await datRoleDung({ version: 1, roles: ['customer', 'sale'] })).toMatchObject({
      trangThai: 'rieng',
      version: 2,
      roleDung: ['customer', 'sale'],
    })
  })

  it('template có gioiHan, chỉ nút lớp sale', async () => {
    const t = await taiTemplate()
    expect(t.gioiHan?.maxNut).toBe(40)
    expect(t.nodes.every((n) => n.lop === 'sale')).toBe(true)
  })
})
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-ghi.test.ts`
Expected: FAIL — không resolve được `@/features/kich-ban/khuon` / các export mới.

- [ ] **Step 3: `api.ts`** — thay đoạn từ đầu tệp tới hết hàm `goi` (dòng 1–26 hiện tại) bằng:

```ts
// Kiểu chép tay từ odyssey-portal-backend `modules/playbook/contracts.py` — đổi ở đó thì đổi ở đây.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

const GOC = '/api/v1'

/** Một lỗi trường của 422 `VALIDATION_ERROR` (BE `portal/api/loi.py::_than_loi_validate`). */
export interface LoiTruong {
  field: string
  reason: string
}

export class LoiApi extends Error {
  readonly code: string
  readonly fields: readonly LoiTruong[]
  constructor(code: string, message: string, fields: readonly LoiTruong[] = []) {
    super(message)
    this.code = code
    this.fields = fields
  }
}

async function docLoi(res: Response, moTa: string): Promise<LoiApi> {
  const body = (await res.json().catch(() => null)) as {
    error?: { code?: string; message?: string; fields?: LoiTruong[] }
  } | null
  return new LoiApi(
    body?.error?.code ?? 'UNKNOWN',
    body?.error?.message ?? `${moTa} → ${res.status}`,
    body?.error?.fields ?? [],
  )
}

async function goi<T>(duong: string): Promise<T> {
  const res = await fetch(`${GOC}${duong}`)
  if (!res.ok) throw await docLoi(res, `GET ${duong}`)
  return (await res.json()) as T
}

async function gui<T>(method: 'PUT' | 'POST', duong: string, body: unknown): Promise<T> {
  const res = await fetch(`${GOC}${duong}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw await docLoi(res, `${method} ${duong}`)
  return (await res.json()) as T
}
```

Trong `interface NutKichBan`, thêm ngay sau dòng `nguon: string`:

```ts
  /** Đợt 1/2: lớp sale (workspace sửa được) hay hệ thống (NobleX giữ, chỉ xem). */
  lop: 'sale' | 'he_thong'
  /** Hash định nghĩa nút (BE `nut.bam_nut` = agent `loader.node_hash`) — số đo đếm theo hash này. */
  hash: string
  /** Nút bắt buộc phải có (`gioiHan.khoaXoa`) — không xoá được, chỉ tắt được. */
  khoaXoa: boolean
  bat: boolean
  lan_2: string
  chi_lan_2: boolean
  cau_ket: string
```

Trong `interface DuLieuKichBan`, thêm sau `coDuLieu: boolean`:

```ts
  kichBan: KichBan
```

Thêm vào cuối tệp:

```ts
export interface BuocVao {
  id: string
  lam: string
}

/** Khuôn nút LƯU (BE `NutVao`, `extra="forbid"`) — payload `PUT /playbook` chỉ mang đúng các khoá này. */
export interface NutVao {
  id: string
  ten: string
  nhom: string
  bat: boolean
  kenh: string[]
  dau_hieu: string[]
  lam: string[]
  tool: string[]
  cam: string[]
  khi_thieu: string
  cau_ket: string
  lan_2: string
  chi_lan_2: boolean
  nguon: string
  buoc: BuocVao[]
}

/** Luật agent xuất trong `playbook.json` (`gioiHan`) — form đọc số ở đây, không chép tay. */
export interface GioiHan {
  nhom: string[]
  kenh: string[]
  tool: string[]
  khoaXoa: string[]
  khuonId: string
  khuonIdRieng: string
  maxNut: number
  maxTen: number
  maxTool: number
  maxDong: { dau_hieu: number; lam: number; cam: number }
  maxBuoc: number
  maxKyTu: number
  maxDauHieuTong: number
  maxCamTong: number
  maxCau: number
}

export interface KichBan {
  trangThai: 'mau' | 'rieng'
  version: number
  tuTemplate: string | null
  templateVersion: string
  coTemplateMoi: boolean
  roleDung: string[]
  capNhatLuc: string | null
  capNhatBoi: string | null
}

export interface TemplateKichBan {
  templateVersion: string
  nodes: NutKichBan[]
  /** Vắng khi BE chưa có MR trả khối này — màn khoá nút ghi, phần xem vẫn chạy. */
  gioiHan?: GioiHan | undefined
}

export const taiTemplate = () => goi<TemplateKichBan>('/playbook/template')
export const luuKichBan = (b: { version: number; nut: NutVao[] }) => gui<KichBan>('PUT', '/playbook', b)
export const apDungMau = (version: number) =>
  gui<KichBan>('POST', '/playbook/ap-dung', { version })
export const datRoleDung = (b: { version: number; roles: string[] }) =>
  gui<KichBan>('PUT', '/playbook/role-dung', b)

/** Template tĩnh theo bản deploy — tải một lần. Khoá KHÔNG bắt đầu bằng `'kich-ban'`: làm mới sau mỗi lần ghi
 *  (`['kich-ban']`) không cần kéo lại nó. */
export function useTemplate() {
  return useQuery({ queryKey: ['kich-ban-template'], queryFn: taiTemplate, staleTime: Infinity })
}

/**
 * Ba lời gọi ghi. Thành công ⇒ `onSuccess` TRẢ promise làm mới `['kich-ban']`, nên mutation còn `isPending` tới lúc
 * `GET /playbook` mới về: nút ghi khoá tới khi màn cầm `version` mới (Review Focus 1). 409 ⇒ làm mới ngay để lần
 * Lưu sau cầm bản mới; role vừa bị xoá ở tab khác (422 `PLAYBOOK_ROLE_KHONG_CO`) ⇒ làm mới danh sách role.
 */
export function useGhiKichBan() {
  const qc = useQueryClient()
  const lamMoi = () => qc.invalidateQueries({ queryKey: ['kich-ban'] })
  const khiLoi = (e: Error) => {
    if (!(e instanceof LoiApi)) return
    if (e.code === 'PLAYBOOK_DA_DOI') void lamMoi()
    if (e.code === 'PLAYBOOK_ROLE_KHONG_CO') void qc.invalidateQueries({ queryKey: ['config'] })
  }
  return {
    luu: useMutation({ mutationFn: luuKichBan, onSuccess: lamMoi, onError: khiLoi }),
    apDung: useMutation({ mutationFn: apDungMau, onSuccess: lamMoi, onError: khiLoi }),
    roleDung: useMutation({ mutationFn: datRoleDung, onSuccess: lamMoi, onError: khiLoi }),
  }
}
```

- [ ] **Step 4: Tạo `src/features/kich-ban/khuon.ts`**

```ts
/**
 * Khuôn nút LƯU của kịch bản workspace (BE `modules/playbook/contracts.py::NutVao`) và các phép thuần trên nó.
 *
 * Payload `PUT /playbook` LUÔN dựng từ `nodes` mà `GET /playbook` vừa trả: BE đã lọc tool agent gỡ khỏi các nút đó
 * (`nut.tuong_thich`), nên dựng từ đây thì không bao giờ 422 trên một tình huống người dùng không sửa (spec đợt 3 §2).
 */
import type { NutKichBan, NutVao } from './api'

/** Nút `GET /playbook` (khuôn playbook.json + trường tương thích) → khuôn `PUT`. */
export function veKhuon(n: NutKichBan): NutVao {
  return {
    id: n.id,
    ten: n.ten ?? n.id,
    nhom: n.nhom,
    bat: n.bat,
    kenh: [...n.kenh],
    dau_hieu: [...n.dau_hieu],
    lam: [...n.lam],
    tool: [...n.tool],
    cam: [...n.cam],
    khi_thieu: n.khi_thieu,
    cau_ket: n.cau_ket,
    lan_2: n.lan_2,
    chi_lan_2: n.chi_lan_2,
    nguon: n.nguon,
    buoc: n.buoc.map((b) => ({ id: b.id, lam: b.lam })),
  }
}

export const laSale = (n: Pick<NutKichBan, 'lop'>) => n.lop === 'sale'
export const boSale = (nodes: readonly NutKichBan[]): NutVao[] => nodes.filter(laSale).map(veKhuon)
export const heThong = (nodes: readonly NutKichBan[]): NutKichBan[] =>
  nodes.filter((n) => n.lop === 'he_thong')
```

- [ ] **Step 5: Thay toàn bộ `src/features/kich-ban/msw.ts`**

```ts
/**
 * Fake của màn Kịch bản — CÓ TRẠNG THÁI từ đợt 3 (sửa được). Mô phỏng hành vi BE `modules/playbook/router.py`:
 * chưa áp dụng ⇒ `GET /playbook` trả NGUYÊN bộ nút mẫu (như BE trả `playbook.json`); có bản riêng ⇒ dựng lại
 * trường tương thích + `hash` từ khuôn lưu (`tuongThich`, bản sao của `nut.tuong_thich`). KHÔNG kiểm luật nút
 * (BE `kiem.py`) — test ép lỗi bằng `epLoiGhiKichBanGia`. Test đổi trạng thái thì `datLaiKichBanGia()` ở `beforeEach`.
 */
import { http, HttpResponse } from 'msw'
import type { DuLieuKichBan, GioiHan, KichBan, LuotNut, NutKichBan, NutVao } from './api'
import { veKhuon } from './khuon'

/** Hash GIẢ — chỉ cần «cùng nội dung ⇒ cùng hash», như `nut.bam_nut` (bỏ `nguon`). */
export function hashGia(n: NutVao): string {
  const s = JSON.stringify([
    n.id, n.ten, n.nhom, n.bat, n.kenh, n.dau_hieu, n.lam, n.tool, n.cam, n.khi_thieu, n.cau_ket,
    n.lan_2, n.chi_lan_2, n.buoc.map((b) => [b.id, b.lam]),
  ])
  let h = 5381
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 33) ^ s.charCodeAt(i)) >>> 0
  return h.toString(16).padStart(12, '0')
}

export const GIOI_HAN_GIA: GioiHan = {
  nhom: ['chot', 'chuyen_nguoi', 'dat_lich', 'ket_thuc', 'kham_pha', 'mo_dau', 'phan_doi', 'tai_lieu', 'tim_can'],
  kenh: ['chat', 'voice'],
  tool: [
    'analyze_projects', 'booking', 'discover_projects', 'escalate', 'find_project', 'get_document', 'kb_search',
    'no_lookup_needed', 'search_units', 'send_media', 'update_customer',
  ],
  // Bản thật khoá thêm `doi_gia_rieng`; fake không có nút đó nên chỉ khoá hai nút có mặt.
  khoaXoa: ['che_dat', 'che_dat_downsell'],
  khuonId: '^[a-z][a-z0-9_]{0,39}$',
  khuonIdRieng: '^rieng_[a-z0-9_]{1,33}$',
  maxNut: 40,
  maxTen: 60,
  maxTool: 4,
  maxDong: { dau_hieu: 6, lam: 6, cam: 5 },
  maxBuoc: 6,
  maxKyTu: 200,
  maxDauHieuTong: 360,
  maxCamTong: 320,
  maxCau: 160,
}

type Goc = Partial<NutKichBan> & Pick<NutKichBan, 'id' | 'loai' | 'nhom'>
const nut = (n: Goc): NutKichBan => {
  const d: NutKichBan = {
    trang_thai: 'dung',
    kenh: [],
    dau_hieu: [],
    lam: [],
    cam: [],
    tool: [],
    can_du_lieu: [],
    khi_thieu: '',
    tiep: {},
    dieu_kien: {},
    buoc: [],
    nguon: 'RULES.md',
    lop: 'sale',
    hash: '',
    khoaXoa: false,
    bat: n.trang_thai !== 'nhap',
    lan_2: '',
    chi_lan_2: false,
    cau_ket: '',
    ...n,
  }
  return { ...d, hash: hashGia(veKhuon(d)) }
}

const NUT_GIA: NutKichBan[] = [
  nut({
    id: 'che_dat',
    ten: 'Khách chê đắt',
    loai: 'phan_xa',
    nhom: 'phan_doi',
    khoaXoa: true,
    dau_hieu: ["khách chê giá cao, 'đắt quá', 'giá ngáo'", 'chê đắt LẦN ĐẦU trong phiên'],
    lam: [
      'ghi nhận thật lòng, không mở đầu bằng "nhưng"',
      'tra NGAY kb_search chính sách vay / tiến độ thanh toán',
    ],
    cam: ['giảm giá', 'escalate', 'tự nhẩm lãi / trả góp'],
    tool: ['kb_search', 'update_customer', 'search_units'],
    can_du_lieu: ['kb:vay_von', 'kb:tien_do_thanh_toan'],
    khi_thieu: 'nói thật chưa có tài liệu vay, chào căn vừa tầm',
    cau_ket: 'một lời mời mà khách chỉ cần trả lời có hoặc không',
    lan_2: 'che_dat_downsell',
    tiep: { lan_2: 'che_dat_downsell' },
    hien: {
      dau_hieu: [
        'Khách chê giá cao, kiểu “đắt quá”, “giá ngáo”',
        'Khách chê đắt lần đầu tiên trong phiên',
      ],
      lam: [
        'Ghi nhận thật lòng, không mở đầu bằng chữ “nhưng”',
        'Tra ngay tài liệu về chính sách vay và tiến độ thanh toán',
      ],
      cam: ['Giảm giá', 'Chuyển cho chuyên viên', 'Tự nhẩm tiền lãi hoặc số tiền trả góp'],
      khi_thieu: 'Nói thật là chưa có tài liệu vay và chào căn vừa tầm',
    },
  }),
  nut({
    id: 'che_dat_downsell',
    ten: 'Chê đắt lần hai',
    loai: 'phan_xa',
    nhom: 'phan_doi',
    khoaXoa: true,
    chi_lan_2: true,
    dau_hieu: ['chê đắt LẦN HAI trong phiên', 'vẫn đắt quá'],
    lam: ['down-sell: một căn rẻ hơn kèm đánh đổi nói rõ, rồi dừng hẳn'],
    cam: ['tự giảm giá', 'áp lực giả'],
    tool: ['search_units'],
    dieu_kien: { lan: 2 },
  }),
  nut({
    id: 'chot',
    ten: 'Chốt căn',
    loai: 'luong',
    nhom: 'chot',
    dau_hieu: ['đã ưng một căn cụ thể, hỏi bước tiếp theo'],
    lam: ['chốt khách đủ 4 bước, thông tin cọc chỉ từ kb'],
    cam: ['bịa mức cọc / chính sách', 'áp lực giả'],
    tool: ['kb_search', 'search_units', 'escalate'],
    lan_2: 'chuyen_that',
    tiep: { lan_2: 'chuyen_that' },
    buoc: [
      { id: 'xac_nhan_nhu_cau', lam: 'hỏi xác nhận nhu cầu dạng đóng sau khi đã tư vấn', tool: [] },
      { id: 'chon_mot_can', lam: 'chọn MỘT căn phù hợp và báo giá từ kết quả tool', tool: [] },
      { id: 'dong_tien_coc', lam: 'nêu tiến độ thanh toán và chính sách, chỉ từ kb', tool: [] },
    ],
  }),
  nut({
    id: 'chuyen_that',
    ten: 'Chuyển cho chuyên viên',
    loai: 'phan_xa',
    nhom: 'chuyen_nguoi',
    lop: 'he_thong',
    dau_hieu: ['muốn gặp người thật', 'khách nói đã sẵn sàng cọc / giữ chỗ ngay'],
    lam: ["gọi escalate(action='transfer', ...) NGAY"],
    cam: ['hứa trước khi gọi escalate'],
    tool: ['escalate'],
  }),
  nut({
    id: 'goi_dien_ra',
    ten: 'Gọi điện cho khách',
    loai: 'luong',
    nhom: 'mo_dau',
    trang_thai: 'nhap',
    kenh: ['voice'],
    dau_hieu: ['cuộc gọi chủ động ra cho khách'],
    lam: ['gọi điện ra ngắn gọn, không quá 3 phút, mục tiêu là xin được cuộc hẹn'],
    tool: ['booking', 'update_customer', 'discover_projects'],
  }),
]

export const TEMPLATE_VERSION_GIA = 'tv-mau-1'
/** Lớp sale của mẫu, khuôn lưu — thứ tự `che_dat, che_dat_downsell, chot, goi_dien_ra`. */
export const MAU_GIA: NutVao[] = NUT_GIA.filter((n) => n.lop === 'sale').map(veKhuon)

interface TrangThaiGia {
  nut: NutVao[] | null
  roleDung: string[]
  version: number
  tuTemplate: string | null
}
const DAU: TrangThaiGia = { nut: null, roleDung: ['customer'], version: 0, tuTemplate: null }
let tt: TrangThaiGia = { ...DAU }
let loiKe: { status: number; body: Record<string, unknown> } | null = null
/** Thân mọi lần ghi theo thứ tự (kể cả lần bị từ chối) — test đọc để kiểm payload. */
export const GHI_GIA: { duong: string; body: unknown }[] = []

export function datLaiKichBanGia(p: Partial<TrangThaiGia> = {}): void {
  tt = { ...DAU, ...p }
  loiKe = null
  GHI_GIA.length = 0
}

/** Lần ghi KẾ TIẾP trả đúng lỗi này (một lần). */
export function epLoiGhiKichBanGia(status: number, body: Record<string, unknown>): void {
  loiKe = { status, body }
}

function kichBanGia(): KichBan {
  const rieng = tt.nut !== null
  return {
    trangThai: rieng ? 'rieng' : 'mau',
    version: tt.version,
    tuTemplate: tt.tuTemplate,
    templateVersion: TEMPLATE_VERSION_GIA,
    coTemplateMoi: rieng && tt.tuTemplate !== TEMPLATE_VERSION_GIA,
    roleDung: tt.roleDung,
    capNhatLuc: tt.version > 0 ? '2026-10-06T07:32:00Z' : null,
    capNhatBoi: null,
  }
}

/** Bản sao `nut.tuong_thich` của BE: tool lạ bị bỏ TRƯỚC khi băm. */
function tuongThich(d: NutVao): NutKichBan {
  const x = { ...d, tool: d.tool.filter((t) => GIOI_HAN_GIA.tool.includes(t)) }
  return {
    ...x,
    lop: 'sale',
    loai: x.buoc.length ? 'luong' : 'phan_xa',
    trang_thai: x.bat ? 'dung' : 'nhap',
    dieu_kien: x.chi_lan_2 ? { lan: 2 } : {},
    tiep: x.lan_2 ? { lan_2: x.lan_2 } : {},
    can_du_lieu: [],
    buoc: x.buoc.map((b) => ({ ...b, tool: [] })),
    khoaXoa: GIOI_HAN_GIA.khoaXoa.includes(x.id),
    hash: hashGia(x),
  }
}

const dem = (ten: string, so: number) => ({ ten, so })
const so = (soLuot: number, daCham: number, dat: number, tiLeDat: number | null) => ({
  soLuot,
  daCham,
  dat,
  tiLeDat,
  thieuDuLieu: 0,
  hayThieu: [],
  hayPham: [],
  jevSo: 0,
  jevKhop: null,
})

export const FAKE_KICH_BAN: DuLieuKichBan = {
  version: 'abc1234567890def',
  promptVersion: 'v3',
  nodes: NUT_GIA,
  soDo: {
    che_dat: {
      ...so(90, 80, 57, 0.71),
      hayThieu: [dem('kết nối lợi ích', 12)],
      hayPham: [dem('tự nhẩm lãi / trả góp', 3)],
    },
    chot: so(12, 10, 5, 0.5),
    chuyen_that: so(3, 3, 3, null),
  },
  nutCu: {},
  phienBanCu: 0,
  nguon: ['web', 'zalo'],
  coDuLieu: true,
  kichBan: kichBanGia(),
}

function duLieuGia(): DuLieuKichBan {
  const nodes =
    tt.nut === null
      ? NUT_GIA
      : [...tt.nut.map(tuongThich), ...NUT_GIA.filter((n) => n.lop === 'he_thong')]
  return { ...FAKE_KICH_BAN, nodes, kichBan: kichBanGia() }
}

export const FAKE_LUOT: LuotNut[] = [
  {
    sessionId: 's-an-1',
    seq: 3,
    phone: null,
    taoLuc: '2026-09-29T09:15:00Z',
    khach: 'Giá này cao quá em ơi',
    agent: 'Dạ em hiểu ạ, để em kiểm tra chính sách vay của dự án cho anh.',
    dat: true,
    thieu: [],
    viPhamCam: [],
    thieuDuLieu: false,
    buoc: null,
    jevNut: 'che_dat',
  },
  {
    sessionId: 's-anh-1',
    seq: 3,
    phone: '0912448111',
    taoLuc: '2026-09-29T10:02:00Z',
    khach: 'Đắt quá, anh chỉ có tầm 2 tỷ',
    agent: 'Dạ căn này 3,2 tỷ, anh cân nhắc nhé.',
    dat: false,
    thieu: ['kết nối lợi ích'],
    viPhamCam: [],
    thieuDuLieu: false,
    buoc: null,
    jevNut: null,
  },
]

const DA_DOI = {
  error: {
    code: 'PLAYBOOK_DA_DOI',
    message: 'Kịch bản vừa thay đổi ở nơi khác — tải lại rồi lưu lại',
  },
}

/** Lỗi ép trước, rồi khoá lạc quan — đúng thứ tự BE. `null` = được ghi. */
function chan(version: number): Response | null {
  if (loiKe) {
    const l = loiKe
    loiKe = null
    return HttpResponse.json(l.body, { status: l.status })
  }
  if (version !== tt.version) return HttpResponse.json(DA_DOI, { status: 409 })
  return null
}

export const kichBanHandlers = [
  http.get('/api/v1/playbook', () => HttpResponse.json(duLieuGia())),
  http.get('/api/v1/playbook/template', () =>
    HttpResponse.json({
      templateVersion: TEMPLATE_VERSION_GIA,
      nodes: NUT_GIA.filter((n) => n.lop === 'sale'),
      gioiHan: GIOI_HAN_GIA,
    }),
  ),
  http.put('/api/v1/playbook', async ({ request }) => {
    const b = (await request.json()) as { version: number; nut: NutVao[] }
    GHI_GIA.push({ duong: 'PUT /playbook', body: b })
    const tu = chan(b.version)
    if (tu) return tu
    tt = {
      ...tt,
      nut: b.nut,
      tuTemplate: tt.nut === null ? TEMPLATE_VERSION_GIA : tt.tuTemplate,
      version: tt.version + 1,
    }
    return HttpResponse.json(kichBanGia())
  }),
  http.post('/api/v1/playbook/ap-dung', async ({ request }) => {
    const b = (await request.json()) as { version: number }
    GHI_GIA.push({ duong: 'POST /playbook/ap-dung', body: b })
    const tu = chan(b.version)
    if (tu) return tu
    tt = { ...tt, nut: structuredClone(MAU_GIA), tuTemplate: TEMPLATE_VERSION_GIA, version: tt.version + 1 }
    return HttpResponse.json(kichBanGia())
  }),
  http.put('/api/v1/playbook/role-dung', async ({ request }) => {
    const b = (await request.json()) as { version: number; roles: string[] }
    GHI_GIA.push({ duong: 'PUT /playbook/role-dung', body: b })
    const la = b.roles.filter((r) => !['customer', 'sale'].includes(r))
    if (la.length)
      return HttpResponse.json(
        { error: { code: 'PLAYBOOK_ROLE_KHONG_CO', message: `Role không có trong workspace: ${la.join(', ')}` } },
        { status: 422 },
      )
    const tu = chan(b.version)
    if (tu) return tu
    tt = { ...tt, roleDung: [...new Set(b.roles)], version: tt.version + 1 }
    return HttpResponse.json(kichBanGia())
  }),
  http.get('/api/v1/playbook/:nut/luot', ({ params, request }) => {
    const chiKhongDat = new URL(request.url).searchParams.get('dat') === 'false'
    const ds = params.nut === 'che_dat' ? FAKE_LUOT : []
    return HttpResponse.json({ luot: chiKhongDat ? ds.filter((l) => l.dat === false) : ds })
  }),
]
```

- [ ] **Step 6: Route** — trong `src/routes/_app/kich-ban.tsx`, `TimKiemKichBan` thêm hai trường và `validateSearch` đọc chúng:

```ts
export interface TimKiemKichBan {
  nut?: string | undefined
  ngay?: 7 | 30 | 90 | undefined
  nguon?: string | undefined
  q?: string | undefined
  /** `mau` = khung chi tiết hiện «So với mẫu» (đợt 3). */
  so?: 'mau' | undefined
  /** Khung chi tiết hiện form thêm tình huống. */
  them?: true | undefined
}
```

```ts
  validateSearch: (s: Record<string, unknown>): TimKiemKichBan => ({
    nut: str(s.nut),
    ngay: s.ngay === 30 || s.ngay === 90 || s.ngay === 7 ? s.ngay : undefined,
    nguon: str(s.nguon),
    q: str(s.q),
    so: s.so === 'mau' ? 'mau' : undefined,
    // Gõ tay `?them=1` về thành SỐ, `<Link search={{them:true}}>` về thành boolean — nhận cả bốn dạng
    // (bẫy `?nap=1` của `/projects`, CLAUDE.md).
    them: s.them === 1 || s.them === '1' || s.them === true || s.them === 'true' ? true : undefined,
  }),
```

- [ ] **Step 7: Sửa hai test cũ theo fixture mới** (`chot` nay chuyển sang `chuyen_that` qua `lan_2`, không còn khoá `san_sang_coc`):

`tests/kich-ban-logic.test.ts`, trong bài `'mỗi cặp tiep một cạnh, nhãn tiếng Việt'`, đổi `label: 'khách sẵn sàng cọc'` thành `label: 'gặp lần 2'`.

`tests/kich-ban-chi-tiet.test.tsx`, bài `'đến từ: nút đích liệt kê nút dẫn tới nó'`, đổi regex `/Chốt căn.*khách sẵn sàng cọc/` thành `/Chốt căn.*gặp lần 2/`.

- [ ] **Step 8: Chạy test mới + toàn bộ test kịch bản + typecheck**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-ghi.test.ts tests/kich-ban.test.tsx tests/kich-ban-chi-tiet.test.tsx tests/kich-ban-logic.test.ts tests/ops-the-nut.test.tsx && npx tsc -b`
Expected: PASS toàn bộ; `tsc -b` thoát 0.

- [ ] **Step 9: Commit**

```bash
npx prettier --write src/features/kich-ban/api.ts src/features/kich-ban/khuon.ts src/features/kich-ban/msw.ts src/routes/_app/kich-ban.tsx tests/kich-ban-ghi.test.ts tests/kich-ban-logic.test.ts tests/kich-ban-chi-tiet.test.tsx
git add src/features/kich-ban/api.ts src/features/kich-ban/khuon.ts src/features/kich-ban/msw.ts src/routes/_app/kich-ban.tsx tests/kich-ban-ghi.test.ts tests/kich-ban-logic.test.ts tests/kich-ban-chi-tiet.test.tsx
git commit -m "feat(kich-ban): lớp dữ liệu sửa kịch bản — kiểu đợt 2, hàm ghi, fake có trạng thái

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1"
```

---

### Task 3: FE — logic thuần: id riêng, so mẫu, kiểm nút / cả bộ, chặn xoá, đọc 422

**Files:**
- Modify: `src/features/kich-ban/khuon.ts` (thêm vào cuối)
- Modify: `src/features/kich-ban/logic.ts` (`nhanKyNang` biết `no_lookup_needed`)
- Test: `tests/kich-ban-khuon.test.ts` (mới)

**Interfaces:**
- Consumes: Task 2 — `NutVao`, `NutKichBan`, `GioiHan`, `LoiApi`, `veKhuon`, `heThong`, `boSale`; fake `GIOI_HAN_GIA`, `MAU_GIA`, `FAKE_KICH_BAN`.
- Produces:
  - `doDai(s: string): number` (code point)
  - `type TruongNut = 'ten'|'nhom'|'kenh'|'dau_hieu'|'lam'|'buoc'|'cam'|'tool'|'khi_thieu'|'cau_ket'|'lan_2'|'chi_lan_2'`; `NHAN_TRUONG: Record<TruongNut, string>`; `type LoiNut = Partial<Record<TruongNut, string>>`
  - `nutTrong(): NutVao`, `chuanHoa(n: NutVao): NutVao`, `idRieng(ten: string, daCo: ReadonlySet<string>): string`, `idBuocMoi(buoc: readonly BuocVao[]): string`
  - `thayNut(bo, moi)`, `themNut(bo, moi)`, `xoaNut(bo, id)` — đều `(readonly NutVao[], …) => NutVao[]`
  - `type LoaiMau = 'giong'|'khac'|'rieng'`; `interface SoMau { loai: Record<string, LoaiMau>; chuaCo: NutKichBan[] }`; `soMau(sale: readonly NutKichBan[], mau: readonly NutKichBan[]): SoMau`
  - `kiemNut(n: NutVao, g: GioiHan): LoiNut`; `kiemBo(bo: readonly NutVao[], heThong: readonly NutKichBan[], g: GioiHan, ten: Record<string,string>): string[]`
  - `interface LyDoChan { id: string; cau: string }`; `chanXoa(id, bo, heThong, ten): LyDoChan[]`
  - `canThemTruoc(m: NutKichBan, bo, heThong, mau: readonly NutKichBan[], ten): string | null`
  - `interface PhanLoi { cuaNut: LoiNut; nutKhac: LyDoChan[]; chung: string[] }`; `phanLoi422(e: Pick<LoiApi,'fields'|'message'>, moi: readonly NutVao[], idDangSua: string | null, ten): PhanLoi`

- [ ] **Step 1: Viết test fail** — tạo `tests/kich-ban-khuon.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { LoiApi, type NutVao } from '@/features/kich-ban/api'
import {
  canThemTruoc,
  chanXoa,
  chuanHoa,
  doDai,
  heThong,
  idBuocMoi,
  idRieng,
  kiemBo,
  kiemNut,
  nutTrong,
  phanLoi422,
  soMau,
  thayNut,
  themNut,
  xoaNut,
  type TruongNut,
} from '@/features/kich-ban/khuon'
import { nhanKyNang } from '@/features/kich-ban/logic'
import { FAKE_KICH_BAN, GIOI_HAN_GIA as G, MAU_GIA } from '@/features/kich-ban/msw'

const HT = heThong(FAKE_KICH_BAN.nodes)
const MAU = FAKE_KICH_BAN.nodes.filter((n) => n.lop === 'sale')
const TEN: Record<string, string> = {
  che_dat: 'Khách chê đắt',
  che_dat_downsell: 'Chê đắt lần hai',
  chot: 'Chốt căn',
  chuyen_that: 'Chuyển cho chuyên viên',
  goi_dien_ra: 'Gọi điện cho khách',
}
const nut = (d: Partial<NutVao> = {}): NutVao => ({
  ...nutTrong(),
  id: 'rieng_x',
  ten: 'X',
  nhom: 'phan_doi',
  dau_hieu: ['a'],
  lam: ['b'],
  ...d,
})

describe('doDai', () => {
  it('đếm theo ký tự như len() của Python — emoji là MỘT', () => {
    expect(doDai('a😀')).toBe(2)
    expect('a😀'.length).toBe(3)
    expect(doDai('Chê đắt')).toBe(7)
  })
})

describe('idRieng', () => {
  it('bỏ dấu, chữ thường, gạch dưới', () =>
    expect(idRieng('Chê màu sơn!', new Set())).toBe('rieng_che_mau_son'))
  it('đ thành d', () => expect(idRieng('Đặt cọc', new Set())).toBe('rieng_dat_coc'))
  it('trùng thì thêm hậu tố', () =>
    expect(
      idRieng('Chê màu sơn', new Set(['rieng_che_mau_son', 'rieng_che_mau_son_2'])),
    ).toBe('rieng_che_mau_son_3'))
  it('tên toàn ký hiệu', () => expect(idRieng('!!!', new Set())).toBe('rieng_tinh_huong'))
  it('tên dài vẫn khớp khuôn, kể cả khi thêm hậu tố', () => {
    const ten = 'Đây là một tình huống có cái tên rất là dài dòng'
    const a = idRieng(ten, new Set())
    const b = idRieng(ten, new Set([a]))
    for (const id of [a, b]) {
      expect(id).toMatch(new RegExp(G.khuonIdRieng))
      expect(id).toMatch(new RegExp(G.khuonId))
    }
    expect(b.endsWith('_2')).toBe(true)
  })
})

describe('phép trên bộ', () => {
  it('idBuocMoi lấp chỗ trống nhỏ nhất', () =>
    expect(idBuocMoi([{ id: 'b1', lam: '' }, { id: 'b3', lam: '' }])).toBe('b2'))
  it('chuanHoa: strip, bỏ ý rỗng, bỏ bước rỗng', () =>
    expect(
      chuanHoa(
        nut({
          ten: '  X ',
          dau_hieu: [' a ', '', '  '],
          khi_thieu: ' k ',
          buoc: [{ id: 'b1', lam: ' ' }, { id: 'b2', lam: ' c' }],
        }),
      ),
    ).toMatchObject({ ten: 'X', dau_hieu: ['a'], khi_thieu: 'k', buoc: [{ id: 'b2', lam: 'c' }] }))
  it('thay / thêm / xoá giữ thứ tự', () => {
    expect(thayNut(MAU_GIA, { ...MAU_GIA[2]!, ten: 'Y' }).map((n) => n.ten)[2]).toBe('Y')
    expect(themNut(MAU_GIA, nut()).at(-1)!.id).toBe('rieng_x')
    expect(xoaNut(MAU_GIA, 'chot').map((n) => n.id)).toEqual(['che_dat', 'che_dat_downsell', 'goi_dien_ra'])
  })
})

describe('soMau', () => {
  it('giống / khác / riêng / chưa có — theo id + hash', () => {
    const sale = [{ ...MAU[0]!, hash: 'doi' }, MAU[1]!, { ...MAU[2]!, id: 'rieng_x', hash: 'h' }]
    const s = soMau(sale, MAU)
    expect(s.loai).toEqual({ che_dat: 'khac', che_dat_downsell: 'giong', rieng_x: 'rieng' })
    expect(s.chuaCo.map((n) => n.id)).toEqual(['chot', 'goi_dien_ra'])
  })
})

const CA: [TruongNut, Partial<NutVao>, string][] = [
  ['ten', { ten: '' }, 'Chưa có tên tình huống'],
  ['ten', { ten: 'x'.repeat(61) }, 'Tối đa 60 ký tự'],
  ['nhom', { nhom: 'khac' }, 'Chọn một nhóm'],
  ['kenh', { kenh: ['fax'] }, 'Kênh không hợp lệ'],
  ['dau_hieu', { dau_hieu: [] }, 'Cần ít nhất một ý'],
  ['lam', { lam: Array<string>(7).fill('a') }, 'Tối đa 6 ý'],
  ['lam', { lam: ['x'.repeat(201)] }, 'Mỗi ý tối đa 200 ký tự'],
  ['dau_hieu', { dau_hieu: Array<string>(6).fill('x'.repeat(60)) }, 'Tổng tối đa 360 ký tự'],
  ['cam', { cam: Array<string>(6).fill('a') }, 'Tối đa 5 ý'],
  ['cam', { cam: ['x'.repeat(200), 'x'.repeat(121)] }, 'Tổng tối đa 320 ký tự'],
  ['tool', { tool: ['tinh_tra_gop'] }, 'Có kỹ năng không còn dùng được'],
  ['tool', { tool: ['kb_search', 'booking', 'escalate', 'send_media', 'find_project'] }, 'Tối đa 4 kỹ năng'],
  ['khi_thieu', { khi_thieu: 'x'.repeat(161) }, 'Tối đa 160 ký tự'],
  ['cau_ket', { cau_ket: 'x'.repeat(161) }, 'Tối đa 160 ký tự'],
  ['buoc', { buoc: Array.from({ length: 7 }, (_, i) => ({ id: `b${i + 1}`, lam: 'a' })) }, 'Tối đa 6 bước'],
  ['buoc', { buoc: [{ id: 'b1', lam: 'x'.repeat(201) }] }, 'Mỗi bước tối đa 200 ký tự'],
  ['lan_2', { lan_2: 'rieng_x' }, 'Không chuyển sang chính nó'],
]

describe('kiemNut — mỗi luật một ca', () => {
  it('nút hợp lệ không lỗi', () => expect(kiemNut(nut(), G)).toEqual({}))
  it('200 ký tự có emoji vẫn hợp lệ (đếm code point)', () =>
    expect(kiemNut(nut({ lam: ['😀'.repeat(200)] }), G)).toEqual({}))
  it.each(CA)('%s', (k, d, cau) => expect(kiemNut(nut(d), G)[k]).toBe(cau))
})

describe('kiemBo — luật cả bộ', () => {
  it('bộ mẫu hợp lệ', () => expect(kiemBo(MAU_GIA, HT, G, TEN)).toEqual([]))
  it('quá số tình huống', () =>
    expect(kiemBo(MAU_GIA, HT, { ...G, maxNut: 3 }, TEN)).toContain('Tối đa 3 tình huống'))
  it('trùng mã với nút hệ thống', () =>
    expect(kiemBo([...MAU_GIA, nut({ id: 'chuyen_that' })], HT, G, TEN)).toContain(
      '«Chuyển cho chuyên viên» trùng mã với một tình huống khác',
    ))
  it('chuyển sang tình huống không còn', () =>
    expect(kiemBo([...MAU_GIA, nut({ lan_2: 'khong_co' })], HT, G, TEN)).toContain(
      '«rieng_x» chuyển sang một tình huống không còn trong kịch bản',
    ))
  it('chỉ-lần-2 mồ côi', () =>
    expect(kiemBo(thayNut(MAU_GIA, { ...MAU_GIA[0]!, lan_2: '' }), HT, G, TEN)).toContain(
      '«Chê đắt lần hai» chỉ dùng khi được chuyển tới, nhưng không tình huống nào chuyển sang nó',
    ))
  it('thiếu tình huống khoá xoá', () =>
    expect(kiemBo(xoaNut(MAU_GIA, 'che_dat'), HT, G, TEN)).toContain('Không được xoá «Khách chê đắt»'))
})

describe('chanXoa', () => {
  it('được xoá khi không ai trỏ tới', () => expect(chanXoa('chot', MAU_GIA, HT, TEN)).toEqual([]))
  it('chặn khi có tình huống chuyển sang nó', () =>
    expect(
      chanXoa('chot', [...MAU_GIA, nut({ id: 'rieng_a', lan_2: 'chot' })], HT, { ...TEN, rieng_a: 'A' }),
    ).toEqual([
      { id: 'rieng_a', cau: '«A» chuyển sang tình huống này khi khách lặp lại — đổi ở «A» trước' },
    ]))
  it('chặn khi nó là đường duy nhất tới một tình huống chỉ-lần-2', () =>
    expect(chanXoa('che_dat', MAU_GIA, HT, TEN)).toEqual([
      {
        id: 'che_dat_downsell',
        cau: '«Chê đắt lần hai» chỉ tới được từ tình huống này — xoá «Chê đắt lần hai» hoặc bỏ «Chỉ dùng khi được chuyển tới» ở «Chê đắt lần hai» trước',
      },
    ]))
})

describe('canThemTruoc', () => {
  const m = (id: string) => MAU.find((n) => n.id === id)!
  const thieuHai = MAU_GIA.filter((n) => n.id !== 'che_dat' && n.id !== 'che_dat_downsell')
  it('thêm được', () => expect(canThemTruoc(m('chot'), xoaNut(MAU_GIA, 'chot'), HT, MAU, TEN)).toBeNull())
  it('chuyển sang tình huống chưa có', () =>
    expect(canThemTruoc(m('che_dat'), thieuHai, HT, MAU, TEN)).toBe('Cần thêm «Chê đắt lần hai» trước'))
  it('chỉ-lần-2 mà chưa ai chuyển sang', () =>
    expect(canThemTruoc(m('che_dat_downsell'), thieuHai, HT, MAU, TEN)).toBe(
      'Cần thêm «Khách chê đắt» trước',
    ))
})

describe('phanLoi422', () => {
  const e = (fields: { field: string; reason: string }[]) =>
    new LoiApi('VALIDATION_ERROR', 'Dữ liệu gửi lên không hợp lệ', fields)
  it('lỗi của tình huống đang sửa vào đúng ô; bước mang số thứ tự', () => {
    const p = phanLoi422(
      e([
        { field: 'body.nut[2].lam', reason: 'tối đa 6 dòng' },
        { field: 'body.nut[2].buoc[1].lam', reason: 'không được rỗng' },
      ]),
      MAU_GIA,
      'chot',
      TEN,
    )
    expect(p.cuaNut).toEqual({ lam: 'tối đa 6 dòng', buoc: 'Bước 2: không được rỗng' })
    expect(p.nutKhac).toEqual([])
  })
  it('lỗi của tình huống khác thành câu có tên + id để mở', () =>
    expect(
      phanLoi422(e([{ field: 'body.nut[0].tool', reason: 'tool không tồn tại: x' }]), MAU_GIA, 'chot', TEN)
        .nutKhac,
    ).toEqual([
      { id: 'che_dat', cau: '«Khách chê đắt» chưa hợp lệ: Kỹ năng nên dùng — tool không tồn tại: x' },
    ]))
  it('lỗi cả bộ và 422 không fields vào nhóm chung', () => {
    expect(phanLoi422(e([{ field: 'body.nut', reason: 'tối đa 40 nút' }]), MAU_GIA, null, TEN).chung).toEqual([
      'tối đa 40 nút',
    ])
    expect(phanLoi422(e([]), MAU_GIA, null, TEN).chung).toEqual(['Dữ liệu gửi lên không hợp lệ'])
  })
})

it('nhanKyNang có nhãn cho no_lookup_needed', () =>
  expect(nhanKyNang('no_lookup_needed')).toBe('Không cần tra cứu'))
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-khuon.test.ts`
Expected: FAIL — các export chưa có.

- [ ] **Step 3: Thêm vào cuối `src/features/kich-ban/khuon.ts`** (sửa dòng import đầu tệp thành `import type { BuocVao, GioiHan, LoiApi, NutKichBan, NutVao } from './api'` và thêm `import { boDau } from '@/lib/boDau'`):

```ts
/** Độ dài theo KÝ TỰ (code point) như `len()` của Python — `.length` đếm UTF-16, emoji tính hai. */
export const doDai = (s: string) => [...s].length

export type TruongNut =
  | 'ten'
  | 'nhom'
  | 'kenh'
  | 'dau_hieu'
  | 'lam'
  | 'buoc'
  | 'cam'
  | 'tool'
  | 'khi_thieu'
  | 'cau_ket'
  | 'lan_2'
  | 'chi_lan_2'

/** Nhãn MỘT nguồn cho cả bản xem lẫn form (luật «xem trước, sửa sau» điều 1). */
export const NHAN_TRUONG: Record<TruongNut, string> = {
  ten: 'Tên tình huống',
  nhom: 'Nhóm',
  kenh: 'Kênh',
  dau_hieu: 'Khi nào dùng',
  lam: 'Agent làm gì',
  buoc: 'Các bước',
  cam: 'Không được làm',
  tool: 'Kỹ năng nên dùng',
  khi_thieu: 'Khi thiếu tài liệu',
  cau_ket: 'Câu kết hỏi khách',
  lan_2: 'Khi khách lặp lại lần 2, chuyển sang',
  chi_lan_2: 'Chỉ dùng khi được chuyển tới',
}

export type LoiNut = Partial<Record<TruongNut, string>>

/** Khuôn của form «Thêm tình huống» — một ô trống sẵn cho hai mục bắt buộc. `id` gán lúc lưu (`idRieng`). */
export const nutTrong = (): NutVao => ({
  id: '',
  ten: '',
  nhom: '',
  bat: true,
  kenh: [],
  dau_hieu: [''],
  lam: [''],
  tool: [],
  cam: [],
  khi_thieu: '',
  cau_ket: '',
  lan_2: '',
  chi_lan_2: false,
  nguon: '',
  buoc: [],
})

/** Form → payload: strip, bỏ ý rỗng và bước rỗng (BE coi «có dòng rỗng» là lỗi). BE strip lại bằng Python. */
export function chuanHoa(n: NutVao): NutVao {
  const ds = (x: string[]) => x.map((s) => s.trim()).filter(Boolean)
  return {
    ...n,
    ten: n.ten.trim(),
    dau_hieu: ds(n.dau_hieu),
    lam: ds(n.lam),
    cam: ds(n.cam),
    khi_thieu: n.khi_thieu.trim(),
    cau_ket: n.cau_ket.trim(),
    buoc: n.buoc.map((b) => ({ ...b, lam: b.lam.trim() })).filter((b) => b.lam),
  }
}

/** `rieng_<tên bỏ dấu>` — luôn khớp `gioiHan.khuonIdRieng` (`^rieng_[a-z0-9_]{1,33}$`); trùng thì `_2`, `_3`… */
export function idRieng(ten: string, daCo: ReadonlySet<string>): string {
  const slug =
    boDau(ten)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'tinh_huong'
  for (let i = 1; ; i++) {
    const duoi = i === 1 ? '' : `_${i}`
    const id = `rieng_${slug.slice(0, 33 - duoi.length).replace(/_+$/, '')}${duoi}`
    if (!daCo.has(id)) return id
  }
}

/** Id cho bước mới: `b<n>` nhỏ nhất chưa dùng — bước cũ GIỮ id (số đo theo bước đọc id). */
export function idBuocMoi(buoc: readonly BuocVao[]): string {
  const co = new Set(buoc.map((b) => b.id))
  for (let i = 1; ; i++) if (!co.has(`b${i}`)) return `b${i}`
}

export const thayNut = (bo: readonly NutVao[], moi: NutVao) =>
  bo.map((n) => (n.id === moi.id ? moi : n))
export const themNut = (bo: readonly NutVao[], moi: NutVao) => [...bo, moi]
export const xoaNut = (bo: readonly NutVao[], id: string) => bo.filter((n) => n.id !== id)

export type LoaiMau = 'giong' | 'khac' | 'rieng'
export interface SoMau {
  loai: Record<string, LoaiMau>
  chuaCo: NutKichBan[]
}

/** So lớp sale đang chạy với mẫu HIỆN TẠI theo id + hash (spec §5). */
export function soMau(sale: readonly NutKichBan[], mau: readonly NutKichBan[]): SoMau {
  const hashMau = new Map(mau.map((n) => [n.id, n.hash]))
  const loai: Record<string, LoaiMau> = {}
  for (const n of sale) {
    const h = hashMau.get(n.id)
    loai[n.id] = h === undefined ? 'rieng' : h === n.hash ? 'giong' : 'khac'
  }
  const co = new Set(sale.map((n) => n.id))
  return { loai, chuaCo: mau.filter((n) => !co.has(n.id)) }
}

/** Luật từng ô (BE `kiem.py`, số từ `gioiHan`) — chạy trên nút ĐÃ `chuanHoa`. Mỗi ô một lỗi đầu tiên. */
export function kiemNut(n: NutVao, g: GioiHan): LoiNut {
  const loi: LoiNut = {}
  const dat = (k: TruongNut, cau: string) => {
    loi[k] ??= cau
  }
  if (!n.ten) dat('ten', 'Chưa có tên tình huống')
  else if (doDai(n.ten) > g.maxTen) dat('ten', `Tối đa ${g.maxTen} ký tự`)
  if (!g.nhom.includes(n.nhom)) dat('nhom', 'Chọn một nhóm')
  if (n.kenh.some((k) => !g.kenh.includes(k))) dat('kenh', 'Kênh không hợp lệ')
  for (const k of ['dau_hieu', 'lam', 'cam'] as const) {
    if (k !== 'cam' && n[k].length === 0) dat(k, 'Cần ít nhất một ý')
    if (n[k].length > g.maxDong[k]) dat(k, `Tối đa ${g.maxDong[k]} ý`)
    if (k !== 'cam' && n[k].some((x) => doDai(x) > g.maxKyTu)) dat(k, `Mỗi ý tối đa ${g.maxKyTu} ký tự`)
  }
  if (doDai(n.dau_hieu.join(' | ')) > g.maxDauHieuTong)
    dat('dau_hieu', `Tổng tối đa ${g.maxDauHieuTong} ký tự`)
  if (n.cam.reduce((s, x) => s + doDai(x), 0) > g.maxCamTong)
    dat('cam', `Tổng tối đa ${g.maxCamTong} ký tự`)
  if (n.tool.some((t) => !g.tool.includes(t))) dat('tool', 'Có kỹ năng không còn dùng được')
  if (n.tool.length > g.maxTool) dat('tool', `Tối đa ${g.maxTool} kỹ năng`)
  for (const k of ['khi_thieu', 'cau_ket'] as const)
    if (doDai(n[k]) > g.maxCau) dat(k, `Tối đa ${g.maxCau} ký tự`)
  if (n.buoc.length > g.maxBuoc) dat('buoc', `Tối đa ${g.maxBuoc} bước`)
  if (n.buoc.some((b) => doDai(b.lam) > g.maxKyTu)) dat('buoc', `Mỗi bước tối đa ${g.maxKyTu} ký tự`)
  if (n.lan_2 && n.lan_2 === n.id) dat('lan_2', 'Không chuyển sang chính nó')
  return loi
}

/** Luật cả bộ (BE `kiem_bo` phần cả bộ) — chỉ để báo sớm bằng TÊN; BE 422 vẫn là chốt chặn. */
export function kiemBo(
  bo: readonly NutVao[],
  heThongNodes: readonly NutKichBan[],
  g: GioiHan,
  ten: Record<string, string>,
): string[] {
  const goi = (id: string) => `«${ten[id] ?? id}»`
  const loi: string[] = []
  if (bo.length > g.maxNut) loi.push(`Tối đa ${g.maxNut} tình huống`)
  const idHt = new Set(heThongNodes.map((n) => n.id))
  const thay = new Set<string>()
  for (const n of bo) {
    if (thay.has(n.id) || idHt.has(n.id)) loi.push(`${goi(n.id)} trùng mã với một tình huống khác`)
    thay.add(n.id)
  }
  const tatCa = new Set([...thay, ...idHt])
  for (const n of bo)
    if (n.lan_2 && n.lan_2 !== n.id && !tatCa.has(n.lan_2))
      loi.push(`${goi(n.id)} chuyển sang một tình huống không còn trong kịch bản`)
  const dich = new Set([...bo, ...heThongNodes].map((n) => n.lan_2).filter(Boolean))
  for (const n of bo)
    if (n.chi_lan_2 && !dich.has(n.id))
      loi.push(`${goi(n.id)} chỉ dùng khi được chuyển tới, nhưng không tình huống nào chuyển sang nó`)
  const thieu = g.khoaXoa.filter((id) => !thay.has(id))
  if (thieu.length) loi.push(`Không được xoá ${thieu.map(goi).join(', ')}`)
  return loi
}

export interface LyDoChan {
  id: string
  cau: string
}

/** Vì sao chưa xoá được `id` (spec §4e) — rỗng = xoá được. Mỗi lý do mang id tình huống để mở nó. */
export function chanXoa(
  id: string,
  bo: readonly NutVao[],
  heThongNodes: readonly NutKichBan[],
  ten: Record<string, string>,
): LyDoChan[] {
  const goi = (x: string) => `«${ten[x] ?? x}»`
  const tatCa = [...bo, ...heThongNodes]
  const out: LyDoChan[] = tatCa
    .filter((n) => n.id !== id && n.lan_2 === id)
    .map((n) => ({
      id: n.id,
      cau: `${goi(n.id)} chuyển sang tình huống này khi khách lặp lại — đổi ở ${goi(n.id)} trước`,
    }))
  const x = bo.find((n) => n.id === id)
  const z = x?.lan_2 ? tatCa.find((n) => n.id === x.lan_2) : undefined
  if (z?.chi_lan_2 && !tatCa.some((n) => n.id !== id && n.lan_2 === z.id))
    out.push({
      id: z.id,
      cau: `${goi(z.id)} chỉ tới được từ tình huống này — xoá ${goi(z.id)} hoặc bỏ «${NHAN_TRUONG.chi_lan_2}» ở ${goi(z.id)} trước`,
    })
  return out
}

/** Thêm một tình huống MẪU vào bản riêng cần tình huống nào có trước? `null` = thêm được (spec §4f). */
export function canThemTruoc(
  m: NutKichBan,
  bo: readonly NutVao[],
  heThongNodes: readonly NutKichBan[],
  mau: readonly NutKichBan[],
  ten: Record<string, string>,
): string | null {
  const tatCa = [...bo, ...heThongNodes]
  const goi = (id: string) => `«${ten[id] ?? id}»`
  if (m.lan_2 && !tatCa.some((n) => n.id === m.lan_2)) return `Cần thêm ${goi(m.lan_2)} trước`
  if (m.chi_lan_2 && !tatCa.some((n) => n.lan_2 === m.id)) {
    const nguon = mau.find((n) => n.lan_2 === m.id)
    return nguon ? `Cần thêm ${goi(nguon.id)} trước` : 'Chưa tình huống nào chuyển sang tình huống này'
  }
  return null
}

export interface PhanLoi {
  cuaNut: LoiNut
  nutKhac: LyDoChan[]
  chung: string[]
}

const DUONG_LOI = /^body\.nut\[(\d+)\]\.(\w+)(?:\[(\d+)\])?/

/** 422 `fields` (`body.nut[i].<trường>[...]`) → lỗi dưới ô của tình huống đang sửa / câu cho tình huống khác / chung. */
export function phanLoi422(
  e: Pick<LoiApi, 'fields' | 'message'>,
  moi: readonly NutVao[],
  idDangSua: string | null,
  ten: Record<string, string>,
): PhanLoi {
  const out: PhanLoi = { cuaNut: {}, nutKhac: [], chung: [] }
  for (const f of e.fields) {
    const m = DUONG_LOI.exec(f.field)
    const n = m ? moi[Number(m[1])] : undefined
    if (!m || !n) {
      out.chung.push(f.reason)
      continue
    }
    const truong = m[2] as TruongNut
    const cau = m[3] !== undefined ? `Bước ${Number(m[3]) + 1}: ${f.reason}` : f.reason
    if (n.id === idDangSua && truong in NHAN_TRUONG) out.cuaNut[truong] ??= cau
    else
      out.nutKhac.push({
        id: n.id,
        cau: `«${ten[n.id] ?? n.id}» chưa hợp lệ: ${NHAN_TRUONG[truong] ?? truong} — ${cau}`,
      })
  }
  if (!e.fields.length) out.chung.push(e.message)
  return out
}
```

- [ ] **Step 4: `logic.ts`** — thay dòng `export const nhanKyNang = (t: string) => NHAN_KY_NANG[t] ?? t` bằng:

```ts
// Tool nội bộ agent dùng làm «không cần tra» — không nằm trong sổ 12 kỹ năng của portal (`lib/tools.ts`).
const NHAN_THEM: Record<string, string> = { no_lookup_needed: 'Không cần tra cứu' }
export const nhanKyNang = (t: string) => NHAN_KY_NANG[t] ?? NHAN_THEM[t] ?? t
```

- [ ] **Step 5: Chạy test**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-khuon.test.ts tests/kich-ban-logic.test.ts && npx tsc -b`
Expected: PASS toàn bộ; `tsc -b` thoát 0.

- [ ] **Step 6: Commit**

```bash
npx prettier --write src/features/kich-ban/khuon.ts src/features/kich-ban/logic.ts tests/kich-ban-khuon.test.ts
git add src/features/kich-ban/khuon.ts src/features/kich-ban/logic.ts tests/kich-ban-khuon.test.ts
git commit -m "feat(kich-ban): logic thuần sửa kịch bản — id riêng, so mẫu, kiểm nút/cả bộ, chặn xoá, đọc 422

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1"
```

---

### Task 4: FE — nhãn nhật ký cho ba mã `playbook.*`

**Files:**
- Modify: `contracts/audit-actions.json` (chép từ BE `develop`)
- Modify: `src/features/platform/so-hanh-dong.ts`
- Test: `tests/audit-actions-parity.test.ts` (có sẵn)

**Interfaces:**
- Consumes: BE `contracts/audit-actions.json` trên `origin/develop` (đã có `playbook.ap_dung`, `playbook.luu`, `playbook.role_dung`).
- Produces: nhãn ba mã + tiền tố `playbook` thuộc nhóm lọc `cau-hinh`.

- [ ] **Step 1: Chép artefact rồi chạy cổng parity để thấy đỏ**

```bash
git -C ../odyssey-portal-backend fetch -q origin
git -C ../odyssey-portal-backend show origin/develop:contracts/audit-actions.json > contracts/audit-actions.json
NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/audit-actions-parity.test.ts
```

Expected: FAIL ở bài (b) (thiếu nhãn `playbook.*`) và (d) (tiền tố `playbook` không thuộc nhóm nào).

- [ ] **Step 2: Thêm nhãn + nhóm** — trong `NHAN_HANH_DONG` của `so-hanh-dong.ts`, chèn theo thứ tự chữ cái (sau khối `owner.bootstrap`, trước `realestate.*`):

```ts
  'playbook.ap_dung': 'Áp dụng mẫu kịch bản',
  'playbook.luu': 'Lưu kịch bản',
  'playbook.role_dung': 'Đổi role dùng kịch bản',
```

Trong `NHOM_LOC`, dòng `cau-hinh` thành:

```ts
  { ma: 'cau-hinh', nhan: 'Cấu hình agent', tienTo: ['agent_config', 'role_config', 'playbook'] },
```

- [ ] **Step 3: Chạy lại**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/audit-actions-parity.test.ts tests/nhat-ky.test.tsx tests/nhat-ky-thuan.test.ts`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
npx prettier --write src/features/platform/so-hanh-dong.ts
git add contracts/audit-actions.json src/features/platform/so-hanh-dong.ts
git commit -m "feat(nhat-ky): nhãn cho playbook.ap_dung / luu / role_dung

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1"
```

---

### Task 5: FE — dải trạng thái + công tắc role + Áp lại mẫu

**Files:**
- Create: `src/features/kich-ban/components/XacNhan.tsx`
- Create: `src/features/kich-ban/components/DaiTrangThai.tsx`
- Modify: `src/features/kich-ban/logic.ts` (thêm `gio`)
- Modify: `src/features/kich-ban/components/BangChiTiet.tsx` (dùng `gio` của `logic.ts`, bỏ bản cục bộ)
- Modify: `src/features/kich-ban/components/KichBanScreen.tsx`
- Test: `tests/kich-ban-sua.test.tsx` (mới)

**Interfaces:**
- Consumes: Task 2 — `useGhiKichBan`, `useTemplate`, `KichBan`, fake `GHI_GIA`, `MAU_GIA`, `datLaiKichBanGia`; Task 3 — `soMau`, `laSale`, `SoMau`; `agent/contracts` — `CAU_HINH_QUERY`, `docCauHinh`.
- Produces:
  - (test) `tests/kich-ban-sua.test.tsx` với `boot(path)`, `chiXem()`, `sua(id, doi)`.
  - `XacNhan({ tieuDe: string; children?: ReactNode; nutChinh?: string | undefined; nutPhu?: string | undefined; phaHuy?: boolean | undefined; dangGui?: boolean | undefined; onDongY?: (() => void) | undefined; onHuy: () => void })` — hộp xác nhận chung (Task 6, 7 dùng).
  - `gio(iso: string): string` ở `logic.ts`.
  - Task 6–8 thêm `describe` vào cuối `tests/kich-ban-sua.test.tsx`.

- [ ] **Step 1: Viết test fail** — tạo `tests/kich-ban-sua.test.tsx`:

```tsx
import { StrictMode } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { server } from '../vitest.setup'
import { routeTree } from '../src/routeTree.gen'
import { LangProvider } from '../src/i18n'
import { FAKE_SESSION } from '../src/lib/msw/handlers'
import type { NutVao } from '../src/features/kich-ban/api'
import { GHI_GIA, MAU_GIA, datLaiKichBanGia } from '../src/features/kich-ban/msw'

function boot(path = '/kich-ban') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [path] }) })
  render(
    <StrictMode>
      <QueryClientProvider client={qc}>
        <LangProvider>
          <RouterProvider router={router} />
        </LangProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
  return router
}

/** Phiên KHÔNG có `agent_config.write`. */
const chiXem = () =>
  server.use(
    http.get('/api/v1/me', () =>
      HttpResponse.json({
        ...FAKE_SESSION,
        actions: FAKE_SESSION.actions.filter((a) => a !== 'agent_config.write'),
      }),
    ),
  )

/** Bộ mẫu với một tình huống đổi. */
const sua = (id: string, doi: Partial<NutVao>) => MAU_GIA.map((n) => (n.id === id ? { ...n, ...doi } : n))

beforeEach(() => datLaiKichBanGia())

describe('dải trạng thái + công tắc role', () => {
  it('chưa áp dụng: nói đang dùng mẫu; Khách hàng bật, Sale tắt; không Áp lại', async () => {
    boot()
    const dai = await screen.findByTestId('dai-trang-thai')
    expect(within(dai).getByText(/Đang dùng kịch bản mẫu NobleX/)).toBeInTheDocument()
    expect(within(dai).getByText(/Sửa một tình huống bất kỳ sẽ tạo bản riêng/)).toBeInTheDocument()
    expect(
      await within(dai).findByRole('switch', { name: 'Dùng kịch bản với Khách hàng' }),
    ).toBeChecked()
    expect(within(dai).getByRole('switch', { name: 'Dùng kịch bản với Sale' })).not.toBeChecked()
    expect(within(dai).queryByRole('button', { name: /Áp lại/ })).toBeNull()
  })

  it('bật Sale gửi PUT /role-dung đủ tập, rồi công tắc bật', async () => {
    boot()
    await userEvent.click(await screen.findByRole('switch', { name: 'Dùng kịch bản với Sale' }))
    await waitFor(() =>
      expect(GHI_GIA).toEqual([
        { duong: 'PUT /playbook/role-dung', body: { version: 0, roles: ['customer', 'sale'] } },
      ]),
    )
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Dùng kịch bản với Sale' })).toBeChecked(),
    )
  })

  it('role đã xoá ở /agent không bị gửi lại', async () => {
    datLaiKichBanGia({ roleDung: ['customer', 'role_da_xoa'] })
    boot()
    await userEvent.click(await screen.findByRole('switch', { name: 'Dùng kịch bản với Sale' }))
    await waitFor(() =>
      expect(GHI_GIA[0]?.body).toEqual({ version: 0, roles: ['customer', 'sale'] }),
    )
  })

  it('người chỉ xem: công tắc khoá, không Áp lại', async () => {
    chiXem()
    datLaiKichBanGia({ nut: MAU_GIA, tuTemplate: 'tv-mau-1', version: 1 })
    boot()
    expect(await screen.findByRole('switch', { name: 'Dùng kịch bản với Sale' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Áp lại/ })).toBeNull()
  })

  it('bản riêng có mẫu mới: báo, đếm, và Áp lại nói rõ mất gì', async () => {
    const rieng = { ...MAU_GIA[2]!, id: 'rieng_mau_son', ten: 'Chê màu sơn', lan_2: '' }
    datLaiKichBanGia({
      nut: [...sua('chot', { lam: ['chữ riêng'] }).filter((n) => n.id !== 'goi_dien_ra'), rieng],
      tuTemplate: 'tv-cu',
      version: 4,
    })
    boot()
    expect(await screen.findByText('NobleX có bản mẫu mới.')).toBeInTheDocument()
    expect(
      await screen.findByRole('button', { name: 'So với mẫu (1 khác · 1 chưa có)' }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Áp lại mẫu NobleX' }))
    const hop = await screen.findByRole('dialog', { name: 'Áp lại mẫu NobleX?' })
    expect(hop).toHaveTextContent(
      '1 tình huống khác mẫu trở về bản mẫu · 1 tình huống riêng bị xoá · 1 tình huống trong mẫu được thêm.',
    )
    await userEvent.click(within(hop).getByRole('button', { name: 'Áp lại' }))
    await waitFor(() =>
      expect(GHI_GIA).toEqual([{ duong: 'POST /playbook/ap-dung', body: { version: 4 } }]),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(await screen.findByText(/Bản riêng của workspace/)).toBeInTheDocument()
  })
})
```

> `tsc -b` typecheck cả `tests/` với `noUnusedLocals`: chỉ import / khai thứ bài của task này DÙNG. Task 6–8 tự thêm import và helper khi cần (ghi rõ ở bước 1 của từng task).

- [ ] **Step 2: Chạy để thấy fail**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-sua.test.tsx`
Expected: FAIL — không tìm thấy `data-testid="dai-trang-thai"`.

- [ ] **Step 3: `logic.ts`** — thêm cuối tệp:

```ts
/** «dd/mm hh:mm» — giờ máy người xem. */
export const gio = (iso: string) =>
  new Date(iso).toLocaleString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
```

`BangChiTiet.tsx`: xoá hằng `gio` cục bộ (dòng `const gio = (iso: string) => …` tới `})`) và thêm `gio` vào import từ `'../logic'`.

- [ ] **Step 4: Tạo `components/XacNhan.tsx`**

```tsx
/**
 * Hộp xác nhận của màn Kịch bản — khuôn portal: `HopThoai` + `HANG_NUT` (nút chính CUỐI), không `confirm()`.
 * Không có `onDongY` ⇒ hộp chỉ để báo (một nút đóng).
 */
import { useId, type ReactNode } from 'react'
import { CAO_O, HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'

const NUT_XOA = `${CAO_O} inline-flex items-center justify-center rounded-md bg-badge-alert-fg px-[15px] text-than font-semibold text-white disabled:opacity-50`

export function XacNhan({
  tieuDe,
  children,
  nutChinh,
  nutPhu = 'Huỷ',
  phaHuy,
  dangGui,
  onDongY,
  onHuy,
}: {
  tieuDe: string
  children?: ReactNode
  nutChinh?: string | undefined
  nutPhu?: string | undefined
  phaHuy?: boolean | undefined
  dangGui?: boolean | undefined
  onDongY?: (() => void) | undefined
  onHuy: () => void
}) {
  const id = useId()
  return (
    <HopThoai
      onDong={onHuy}
      khoaDong={dangGui ?? false}
      aria-labelledby={id}
      className={`${KHUNG_HOP_THOAI} max-w-[440px]`}
    >
      <h2 id={id} className="text-muc leading-tight font-semibold text-fg">
        {tieuDe}
      </h2>
      {children ? (
        <div className="mt-3 space-y-2 text-than leading-[1.55] text-muted">{children}</div>
      ) : null}
      <div className={`${HANG_NUT} mt-5`}>
        <button type="button" onClick={onHuy} disabled={dangGui} className={`${NUT_PHU} cursor-pointer`}>
          {nutPhu}
        </button>
        {onDongY && nutChinh ? (
          <button
            type="button"
            onClick={onDongY}
            disabled={dangGui}
            className={`${phaHuy ? NUT_XOA : NUT_CHINH} cursor-pointer`}
          >
            {nutChinh}
          </button>
        ) : null}
      </div>
    </HopThoai>
  )
}
```

- [ ] **Step 5: Tạo `components/DaiTrangThai.tsx`**

```tsx
/**
 * Dải trạng thái kịch bản của workspace (spec đợt 3 §4a): mẫu / bản riêng / có mẫu mới, công tắc dùng kịch bản theo
 * role, Áp lại mẫu. Công tắc role ở ĐÂY chứ không ở tab role `/agent`: màn đó gom thay đổi vào bản nháp + «Lưu và
 * áp dụng», còn công tắc này ghi ngay bằng `PUT /playbook/role-dung` (version riêng) — xem `CLAUDE.md`.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { CongTac } from '@/components/ui/CongTac'
import { CAU_HINH_QUERY, docCauHinh } from '@/features/agent/contracts'
import { LoiApi, useGhiKichBan, type KichBan } from '../api'
import type { SoMau } from '../khuon'
import { gio } from '../logic'
import { XacNhan } from './XacNhan'

const cauLoi = (e: unknown) => (e instanceof LoiApi ? e.message : 'Chưa lưu được — thử lại.')

interface Props {
  kichBan: KichBan
  so: SoMau | null
  suaDuoc: boolean
  onSoMau: () => void
}

export function DaiTrangThai({ kichBan, so, suaDuoc, onSoMau }: Props) {
  const { apDung, roleDung } = useGhiKichBan()
  const cauHinh = useQuery({ queryKey: CAU_HINH_QUERY, queryFn: docCauHinh })
  const vaiTro = cauHinh.data?.vaiTro ?? []
  const [hoiApLai, setHoiApLai] = useState(false)
  const rieng = kichBan.trangThai === 'rieng'
  const moi = rieng && kichBan.coTemplateMoi
  const loai = so ? Object.values(so.loai) : []
  const soKhac = loai.filter((l) => l === 'khac').length
  const soRieng = loai.filter((l) => l === 'rieng').length

  const doiRole = (key: string, bat: boolean) =>
    // Chỉ gửi role workspace ĐANG có: role trong `roleDung` mà đã bị xoá ở `/agent` thì BE trả 422.
    roleDung.mutate({
      version: kichBan.version,
      roles: vaiTro.map((v) => v.key).filter((k) => (k === key ? bat : kichBan.roleDung.includes(k))),
    })

  const loi = roleDung.error ?? apDung.error
  return (
    <section
      aria-label="Trạng thái kịch bản"
      data-testid="dai-trang-thai"
      className={`space-y-2 rounded-lg border px-4 py-3 ${moi ? 'border-badge-warn-fg/40 bg-badge-warn-bg' : 'border-border bg-surface'}`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p className="text-than text-fg">
          {!rieng
            ? 'Đang dùng kịch bản mẫu NobleX — agent tự nhận bản mẫu mới.'
            : moi
              ? 'NobleX có bản mẫu mới.'
              : `Bản riêng của workspace${kichBan.capNhatLuc ? ` · sửa lần cuối ${gio(kichBan.capNhatLuc)}` : ''}`}
        </p>
        {!rieng && suaDuoc ? (
          <p className="text-phu text-muted">Sửa một tình huống bất kỳ sẽ tạo bản riêng cho workspace.</p>
        ) : null}
        {rieng && suaDuoc ? (
          <div className="ml-auto flex flex-wrap gap-2">
            <button
              type="button"
              disabled={!so}
              onClick={onSoMau}
              className={`${moi ? NUT_CHINH : NUT_PHU} cursor-pointer`}
            >
              {so ? `So với mẫu (${soKhac} khác · ${so.chuaCo.length} chưa có)` : 'So với mẫu'}
            </button>
            <button type="button" onClick={() => setHoiApLai(true)} className={`${NUT_PHU} cursor-pointer`}>
              Áp lại mẫu NobleX
            </button>
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-than">
        <span className="text-muted">Agent dùng kịch bản khi nói chuyện với:</span>
        {vaiTro.map((v) => (
          <span key={v.key} className="flex items-center gap-2">
            {v.ten}
            <CongTac
              bat={kichBan.roleDung.includes(v.key)}
              nhan={`Dùng kịch bản với ${v.ten}`}
              dangGui={!suaDuoc || roleDung.isPending}
              doi={(b) => doiRole(v.key, b)}
            />
          </span>
        ))}
        {cauHinh.isError ? <span className="text-phu text-muted">Không tải được danh sách role.</span> : null}
      </div>
      {vaiTro.length > 0 && !vaiTro.some((v) => kichBan.roleDung.includes(v.key)) ? (
        <p className="text-phu text-muted">Agent không dùng kịch bản với role nào.</p>
      ) : null}
      {loi ? (
        <p role="alert" className="text-phu text-badge-alert-fg">
          {cauLoi(loi)}
        </p>
      ) : null}
      {hoiApLai ? (
        <XacNhan
          tieuDe="Áp lại mẫu NobleX?"
          nutChinh="Áp lại"
          phaHuy
          dangGui={apDung.isPending}
          onHuy={() => setHoiApLai(false)}
          onDongY={() => apDung.mutate(kichBan.version, { onSettled: () => setHoiApLai(false) })}
        >
          <p>
            {so
              ? `${soKhac} tình huống khác mẫu trở về bản mẫu · ${soRieng} tình huống riêng bị xoá · ${so.chuaCo.length} tình huống trong mẫu được thêm.`
              : 'Bản riêng sẽ bị thay bằng bản mẫu hiện tại.'}
          </p>
          <p>Số đo các tình huống đổi chữ đếm lại từ đầu.</p>
        </XacNhan>
      ) : null}
    </section>
  )
}
```

- [ ] **Step 6: Nối vào `KichBanScreen.tsx`**

Import thêm (giữ các import cũ):

Dòng `import { useEffect, useRef, useState } from 'react'` thành `import { useEffect, useMemo, useRef, useState } from 'react'`; dòng import `'../api'` thành `import { LoiApi, useKichBan, useTemplate, type Ngay } from '../api'`; thêm:

```tsx
import { ACTIONS } from '@/lib/actions'
import { useSession } from '@/lib/session'
import { laSale, soMau } from '../khuon'
import { DaiTrangThai } from './DaiTrangThai'
```

Ngay sau dòng `const soNutCu = …`:

```tsx
  const { can } = useSession()
  const suaDuoc = can([ACTIONS.AGENT_CONFIG_WRITE])
  const tpl = useTemplate()
  // So với mẫu chỉ có nghĩa ở bản riêng — ở trạng thái mẫu mọi tình huống sale CHÍNH LÀ mẫu.
  const so = useMemo(
    () =>
      data && tpl.data && data.kichBan.trangThai === 'rieng'
        ? soMau(data.nodes.filter(laSale), tpl.data.nodes)
        : null,
    [data, tpl.data],
  )
```

Trong JSX, ngay sau `<div className="flex flex-col gap-4 px-7 pt-[22px] pb-15 max-md:px-4">` (TRƯỚC hàng bộ lọc):

```tsx
      {data ? (
        <DaiTrangThai
          kichBan={data.kichBan}
          so={so}
          suaDuoc={suaDuoc}
          onSoMau={() => sua({ so: 'mau', nut: undefined, them: undefined })}
        />
      ) : null}
```

- [ ] **Step 7: Chạy test**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-sua.test.tsx tests/kich-ban.test.tsx tests/kich-ban-chi-tiet.test.tsx && npx tsc -b`
Expected: PASS toàn bộ (5 bài mới + bài cũ); `tsc -b` thoát 0.

- [ ] **Step 8: Commit**

```bash
npx prettier --write src/features/kich-ban/components/XacNhan.tsx src/features/kich-ban/components/DaiTrangThai.tsx src/features/kich-ban/components/KichBanScreen.tsx src/features/kich-ban/components/BangChiTiet.tsx src/features/kich-ban/logic.ts tests/kich-ban-sua.test.tsx
git add src/features/kich-ban/components/XacNhan.tsx src/features/kich-ban/components/DaiTrangThai.tsx src/features/kich-ban/components/KichBanScreen.tsx src/features/kich-ban/components/BangChiTiet.tsx src/features/kich-ban/logic.ts tests/kich-ban-sua.test.tsx
git commit -m "feat(kich-ban): dải trạng thái, công tắc dùng kịch bản theo role, áp lại mẫu

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1"
```

---

### Task 6: FE — thao tác trên tình huống: bật/tắt, xoá, xem/dùng bản mẫu (một đường ghi)

**Files:**
- Create: `src/features/kich-ban/useGhi.ts`
- Create: `src/features/kich-ban/components/HanhDongNut.tsx`
- Create: `src/features/kich-ban/components/SoHaiBan.tsx`
- Create: `src/features/kich-ban/components/KhungChiTiet.tsx`
- Modify: `src/features/kich-ban/components/BangChiTiet.tsx` (prop `chip`, `hanhDong`; chip «Đang tắt»)
- Modify (thay toàn bộ): `src/features/kich-ban/components/KichBanScreen.tsx`
- Modify: `src/features/kich-ban/components/DanhSachNut.tsx` («Bản nháp» → «Đang tắt»)
- Modify: `tests/kich-ban.test.tsx` (regex «Bản nháp» → «Đang tắt»)
- Test: `tests/kich-ban-sua.test.tsx` (thêm `describe`)

**Interfaces:**
- Consumes: Task 2 (`useGhiKichBan`, `LoiApi`, kiểu), Task 3 (`boSale`, `heThong`, `kiemBo`, `chanXoa`, `thayNut`, `xoaNut`, `veKhuon`, `NHAN_TRUONG`, `LoaiMau`, `SoMau`), Task 5 (`XacNhan`, `DaiTrangThai`, `gio`).
- Produces:
  - `useGhi(data: DuLieuKichBan | undefined, gioiHan: GioiHan | undefined) → { ghi(bienDoi: (bo: NutVao[]) => NutVao[]): Promise<KetQuaGhi>; dangGhi: boolean; ten: Record<string,string> }`; `interface KetQuaGhi { ok: boolean; loiBo: string[]; loi: unknown; moi: NutVao[] }`; `cauLoi(e: unknown): string`.
  - `KhungChiTiet(props: KhungChiTietProps)` với `KhungChiTietProps = { data; mau: TemplateKichBan | undefined; so: SoMau | null; nut: string; ngay: Ngay; nguon: string | undefined; ghiDuoc: boolean; lyDoKhoa: string | null; onChon(id); onDong(); khung?: string | undefined }` — Task 7 thêm `che`, `onSua`, `onXong`, `onHuy`, `onDoi`.
  - `HanhDongNut` props `{ n, data, nutMau, loai, gioiHan, ghiDuoc, lyDoKhoa, onChon, onDaXoa }` — Task 7 thêm `onSua`.
  - `BangChiTiet` props thêm `chip?: ReactNode`, `hanhDong?: ReactNode`; `khung?: string | undefined`.

- [ ] **Step 1: Viết test fail** — trong `tests/kich-ban-sua.test.tsx`: dòng import fake thành
`import { GHI_GIA, MAU_GIA, datLaiKichBanGia, epLoiGhiKichBanGia } from '../src/features/kich-ban/msw'`; thêm helper ngay trên `beforeEach`:

```tsx
/** Bấm một nút khi nó đã MỞ (nút ghi khoá tới lúc `gioiHan` về). */
async function bam(name: string) {
  const b = await screen.findByRole('button', { name })
  await waitFor(() => expect(b).toBeEnabled())
  await userEvent.click(b)
}
```

rồi thêm vào cuối tệp:

```tsx
describe('thao tác trên một tình huống', () => {
  it('tình huống hệ thống: chip chỉ xem, không nút ghi', async () => {
    boot('/kich-ban?nut=chuyen_that')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(within(b).getByText('Hệ thống NobleX — chỉ xem')).toBeInTheDocument()
    await screen.findByTestId('dai-trang-thai')
    expect(within(b).queryByRole('switch', { name: 'Đang dùng' })).toBeNull()
    expect(within(b).queryByRole('button', { name: 'Xoá' })).toBeNull()
  })

  it('bật một tình huống đang tắt: PUT cả bộ sale, chỉ nó đổi, không lẫn trường tương thích', async () => {
    boot('/kich-ban?nut=goi_dien_ra')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(within(b).getByText('Đang tắt — agent không chọn')).toBeInTheDocument()
    await userEvent.click(await within(b).findByRole('switch', { name: 'Đang dùng' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect(GHI_GIA[0]!.body).toEqual({
      version: 0,
      nut: MAU_GIA.map((n) => (n.id === 'goi_dien_ra' ? { ...n, bat: true } : n)),
    })
  })

  it('hai cú bấm liền nhau không gửi version cũ (Review Focus 1)', async () => {
    boot('/kich-ban?nut=goi_dien_ra')
    const sw = await screen.findByRole('switch', { name: 'Đang dùng' })
    await userEvent.click(sw)
    await userEvent.click(sw)
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Đang dùng' })).not.toBeDisabled(),
    )
    expect(screen.queryByRole('alert')).toBeNull()
    expect(GHI_GIA.map((g) => (g.body as { version: number }).version)).toEqual(
      GHI_GIA.map((_, i) => i),
    )
  })

  it('tình huống khoá xoá: có công tắc, không có Xoá', async () => {
    boot('/kich-ban?nut=che_dat')
    const b = await screen.findByTestId('bang-chi-tiet')
    await within(b).findByRole('switch', { name: 'Đang dùng' })
    expect(within(b).queryByRole('button', { name: 'Xoá' })).toBeNull()
  })

  it('xoá: hỏi lại, PUT thiếu đúng tình huống đó, khung đóng (Review Focus 5)', async () => {
    const router = boot('/kich-ban?nut=chot')
    await bam('Xoá')
    const hop = await screen.findByRole('dialog', { name: 'Xoá «Chốt căn»?' })
    await userEvent.click(within(hop).getByRole('button', { name: 'Xoá' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect((GHI_GIA[0]!.body as { nut: { id: string }[] }).nut.map((n) => n.id)).toEqual([
      'che_dat',
      'che_dat_downsell',
      'goi_dien_ra',
    ])
    await waitFor(() => expect(router.state.location.search).not.toHaveProperty('nut'))
  })

  it('xoá bị chặn khi tình huống khác chuyển sang nó — bấm lý do mở tình huống kia', async () => {
    datLaiKichBanGia({
      nut: [...MAU_GIA, { ...MAU_GIA[2]!, id: 'rieng_hoi_lai', ten: 'Hỏi lại', lan_2: 'chot' }],
      tuTemplate: 'tv-mau-1',
      version: 1,
    })
    const router = boot('/kich-ban?nut=chot')
    await bam('Xoá')
    const hop = await screen.findByRole('dialog', { name: 'Chưa xoá được «Chốt căn»' })
    expect(within(hop).queryByRole('button', { name: 'Xoá' })).toBeNull()
    await userEvent.click(
      within(hop).getByRole('button', { name: /«Hỏi lại» chuyển sang tình huống này/ }),
    )
    await waitFor(() => expect(router.state.location.search).toMatchObject({ nut: 'rieng_hoi_lai' }))
    expect(GHI_GIA).toEqual([])
  })

  it('khác mẫu: xem hai bản, dùng bản mẫu', async () => {
    datLaiKichBanGia({ nut: sua('chot', { lam: ['chữ riêng của sàn'] }), tuTemplate: 'tv-mau-1', version: 2 })
    boot('/kich-ban?nut=chot')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(await within(b).findByText('Khác mẫu')).toBeInTheDocument()
    await userEvent.click(within(b).getByRole('button', { name: 'Xem bản mẫu' }))
    const hai = within(b).getByTestId('so-hai-ban')
    expect(hai).toHaveTextContent('chữ riêng của sàn')
    expect(hai).toHaveTextContent(MAU_GIA[2]!.lam[0]!)
    await userEvent.click(within(b).getByRole('button', { name: 'Dùng bản mẫu' }))
    const hop = await screen.findByRole('dialog', { name: 'Thay «Chốt căn» bằng bản mẫu?' })
    await userEvent.click(within(hop).getByRole('button', { name: 'Dùng bản mẫu' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect(GHI_GIA[0]!.body).toEqual({ version: 2, nut: MAU_GIA })
    expect(await within(b).findByText('Giống mẫu')).toBeInTheDocument()
  })

  it('409: báo câu của BE', async () => {
    epLoiGhiKichBanGia(409, {
      error: { code: 'PLAYBOOK_DA_DOI', message: 'Kịch bản vừa thay đổi ở nơi khác — tải lại rồi lưu lại' },
    })
    boot('/kich-ban?nut=goi_dien_ra')
    await userEvent.click(await screen.findByRole('switch', { name: 'Đang dùng' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Kịch bản vừa thay đổi ở nơi khác')
  })

  it('người chỉ xem: không công tắc, không Xoá', async () => {
    chiXem()
    boot('/kich-ban?nut=chot')
    const b = await screen.findByTestId('bang-chi-tiet')
    await screen.findByTestId('dai-trang-thai')
    expect(within(b).queryByRole('switch')).toBeNull()
    expect(within(b).queryByRole('button', { name: 'Xoá' })).toBeNull()
  })
})
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-sua.test.tsx -t "thao tác"`
Expected: FAIL — không có chip «Hệ thống NobleX — chỉ xem», không có công tắc «Đang dùng».

- [ ] **Step 3: Tạo `src/features/kich-ban/useGhi.ts`**

```ts
import { useMemo } from 'react'
import { LoiApi, useGhiKichBan, type DuLieuKichBan, type GioiHan, type NutVao } from './api'
import { boSale, heThong, kiemBo } from './khuon'
import { tenNut } from './logic'

export interface KetQuaGhi {
  ok: boolean
  /** Lỗi cả bộ phát hiện phía client — chưa gửi gì. */
  loiBo: string[]
  /** Lỗi của lời gọi (`LoiApi` 409/422…, lỗi mạng). */
  loi: unknown
  /** Bộ đã gửi — để đổi `body.nut[i]` của 422 ra tình huống. */
  moi: NutVao[]
}

/** Câu báo cho một lần ghi hỏng: `LoiApi` mang câu tiếng Việt của BE, lỗi khác thì câu chung. */
export const cauLoi = (e: unknown) =>
  e instanceof LoiApi ? e.message : 'Chưa lưu được — thử lại.'

/**
 * MỘT đường ghi cho mọi thao tác trên tình huống (spec đợt 3 §3): bộ sale lấy từ lần tải `GET /playbook` mới nhất
 * (`data` của màn), áp `bienDoi`, kiểm cả bộ phía client, rồi `PUT` với `version` của chính lần tải đó. Mutation
 * chờ tải lại xong mới hết `isPending` (`useGhiKichBan`) ⇒ nút ghi khoá tới lúc `data` mang `version` mới.
 * Đừng giữ bản sao bộ nút trong state: bản sao cũ là cách ghi đè lần lưu của người khác.
 */
export function useGhi(data: DuLieuKichBan | undefined, gioiHan: GioiHan | undefined) {
  const { luu } = useGhiKichBan()
  const ten = useMemo(
    () => Object.fromEntries((data?.nodes ?? []).map((n) => [n.id, tenNut(n)])),
    [data],
  )
  async function ghi(bienDoi: (bo: NutVao[]) => NutVao[]): Promise<KetQuaGhi> {
    if (!data || !gioiHan)
      return { ok: false, loiBo: ['Chưa tải xong kịch bản — thử lại.'], loi: null, moi: [] }
    const moi = bienDoi(boSale(data.nodes))
    const loiBo = kiemBo(moi, heThong(data.nodes), gioiHan, ten)
    if (loiBo.length) return { ok: false, loiBo, loi: null, moi }
    try {
      await luu.mutateAsync({ version: data.kichBan.version, nut: moi })
      return { ok: true, loiBo: [], loi: null, moi }
    } catch (e) {
      return { ok: false, loiBo: [], loi: e, moi }
    }
  }
  return { ghi, dangGhi: luu.isPending, ten }
}
```

- [ ] **Step 4: Tạo `components/SoHaiBan.tsx`**

```tsx
/** «Xem bản mẫu» (spec §4b): chỉ các mục KHÁC nhau, bản của workspace trên, bản mẫu dưới. Không diff từng dòng. */
import type { NutKichBan, NutVao } from '../api'
import { NHAN_TRUONG, veKhuon } from '../khuon'
import { TEN_NHOM, nhanKyNang } from '../logic'

const TRUONG: (keyof NutVao)[] = [
  'ten', 'nhom', 'bat', 'kenh', 'dau_hieu', 'lam', 'buoc', 'cam', 'tool', 'khi_thieu', 'cau_ket', 'lan_2', 'chi_lan_2',
]
const NHAN: Record<string, string> = { ...NHAN_TRUONG, bat: 'Đang dùng' }
const KENH: Record<string, string> = { chat: 'Chỉ chat', voice: 'Chỉ cuộc gọi' }

function hien(k: keyof NutVao, n: NutVao, ten: Record<string, string>): string[] {
  switch (k) {
    case 'nhom':
      return [TEN_NHOM[n.nhom] ?? n.nhom]
    case 'bat':
      return [n.bat ? 'Đang dùng' : 'Đang tắt']
    case 'chi_lan_2':
      return [n.chi_lan_2 ? 'Có' : 'Không']
    case 'kenh':
      return [n.kenh.length === 1 ? (KENH[n.kenh[0]!] ?? n.kenh[0]!) : 'Cả chat và cuộc gọi']
    case 'tool':
      return n.tool.map(nhanKyNang)
    case 'buoc':
      return n.buoc.map((b, i) => `${i + 1}. ${b.lam}`)
    case 'lan_2':
      return [n.lan_2 ? (ten[n.lan_2] ?? n.lan_2) : 'Không chuyển']
    case 'dau_hieu':
    case 'lam':
    case 'cam':
      return n[k]
    default:
      return [String(n[k])]
  }
}

function Ban({ nhan, ds, mau = false }: { nhan: string; ds: string[]; mau?: boolean }) {
  return (
    <div className={`rounded-sm px-2 py-1.5 text-[13px] ${mau ? 'bg-fill' : 'bg-surface'}`}>
      <p className="text-phu text-muted-2">{nhan}</p>
      {ds.length ? (
        <ul className="list-disc pl-4">
          {ds.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      ) : (
        <p className="text-muted">(trống)</p>
      )}
    </div>
  )
}

export function SoHaiBan({
  cua,
  mau,
  ten,
}: {
  cua: NutKichBan
  mau: NutKichBan
  ten: Record<string, string>
}) {
  const a = veKhuon(cua)
  const b = veKhuon(mau)
  const khac = TRUONG.filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]))
  return (
    <section data-testid="so-hai-ban" className="space-y-3 rounded-md border border-border p-3">
      {khac.map((k) => (
        <div key={k} className="space-y-1">
          <h4 className="text-phu font-medium text-muted">{NHAN[k]}</h4>
          <Ban nhan="Bản của bạn" ds={hien(k, a, ten)} />
          <Ban nhan="Bản mẫu" ds={hien(k, b, ten)} mau />
        </div>
      ))}
    </section>
  )
}
```

- [ ] **Step 5: Tạo `components/HanhDongNut.tsx`**

```tsx
/**
 * Hàng thao tác của MỘT tình huống lớp sale (spec §4b, §4e): công tắc «Đang dùng», Xoá (không có với tình huống
 * khoá xoá — agent chỉ bắt buộc chúng CÓ MẶT, tắt được), Xem / Dùng bản mẫu khi khác mẫu. Mọi lần ghi qua `useGhi`.
 */
import { useState } from 'react'
import { NUT_PHU } from '@/components/ui/Bang'
import { CongTac } from '@/components/ui/CongTac'
import type { DuLieuKichBan, GioiHan, NutKichBan, NutVao } from '../api'
import { boSale, chanXoa, heThong, thayNut, veKhuon, xoaNut, type LoaiMau } from '../khuon'
import { cauLoi, useGhi } from '../useGhi'
import { SoHaiBan } from './SoHaiBan'
import { XacNhan } from './XacNhan'

interface Props {
  n: NutKichBan
  data: DuLieuKichBan
  nutMau: NutKichBan | undefined
  loai: LoaiMau | undefined
  gioiHan: GioiHan | undefined
  ghiDuoc: boolean
  /** Có quyền ghi nhưng thiếu `gioiHan` ⇒ nút hiện ở dạng khoá kèm lý do này. */
  lyDoKhoa: string | null
  onChon: (id: string) => void
  onDaXoa: () => void
}

export function HanhDongNut({ n, data, nutMau, loai, gioiHan, ghiDuoc, lyDoKhoa, onChon, onDaXoa }: Props) {
  const { ghi, dangGhi, ten } = useGhi(data, gioiHan)
  const [hoi, setHoi] = useState<'xoa' | 'mau' | null>(null)
  const [xemMau, setXemMau] = useState(false)
  const [loi, setLoi] = useState<string[]>([])
  const coGhi = ghiDuoc || lyDoKhoa !== null
  const khoa = !ghiDuoc || dangGhi
  const tenNay = ten[n.id] ?? n.id

  async function chay(bienDoi: (bo: NutVao[]) => NutVao[], sau?: () => void) {
    setLoi([])
    const kq = await ghi(bienDoi)
    setHoi(null)
    if (kq.ok) return sau?.()
    setLoi(kq.loiBo.length ? kq.loiBo : [cauLoi(kq.loi)])
  }

  const chan = hoi === 'xoa' ? chanXoa(n.id, boSale(data.nodes), heThong(data.nodes), ten) : []
  return (
    <div className="space-y-2">
      {coGhi ? (
        <div className="flex flex-wrap items-center gap-2" title={lyDoKhoa ?? undefined}>
          <span className="flex items-center gap-2 text-than">
            Đang dùng
            <CongTac
              bat={n.bat}
              nhan="Đang dùng"
              dangGui={khoa}
              doi={(b) => void chay((bo) => thayNut(bo, { ...veKhuon(n), bat: b }))}
            />
          </span>
          {n.khoaXoa ? null : (
            <button
              type="button"
              disabled={khoa}
              onClick={() => setHoi('xoa')}
              className={`${NUT_PHU} ml-auto cursor-pointer disabled:opacity-50`}
            >
              Xoá
            </button>
          )}
        </div>
      ) : null}
      {loai === 'khac' && nutMau ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            aria-expanded={xemMau}
            onClick={() => setXemMau((v) => !v)}
            className={`${NUT_PHU} cursor-pointer`}
          >
            Xem bản mẫu
          </button>
          {ghiDuoc ? (
            <button
              type="button"
              disabled={dangGhi}
              onClick={() => setHoi('mau')}
              className={`${NUT_PHU} cursor-pointer`}
            >
              Dùng bản mẫu
            </button>
          ) : null}
        </div>
      ) : null}
      {xemMau && nutMau ? <SoHaiBan cua={n} mau={nutMau} ten={ten} /> : null}
      {loi.length ? (
        <ul role="alert" className="space-y-1 text-phu text-badge-alert-fg">
          {loi.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      ) : null}
      {hoi === 'xoa' && chan.length ? (
        <XacNhan tieuDe={`Chưa xoá được «${tenNay}»`} nutPhu="Đóng" onHuy={() => setHoi(null)}>
          <ul className="space-y-1">
            {chan.map((c) => (
              <li key={c.cau}>
                <button
                  type="button"
                  onClick={() => {
                    setHoi(null)
                    onChon(c.id)
                  }}
                  className="cursor-pointer text-left text-ac"
                >
                  {c.cau}
                </button>
              </li>
            ))}
          </ul>
        </XacNhan>
      ) : null}
      {hoi === 'xoa' && !chan.length ? (
        <XacNhan
          tieuDe={`Xoá «${tenNay}»?`}
          nutChinh="Xoá"
          phaHuy
          dangGui={dangGhi}
          onHuy={() => setHoi(null)}
          onDongY={() => void chay((bo) => xoaNut(bo, n.id), onDaXoa)}
        >
          <p>Lượt cũ của nó chuyển vào mục «tình huống đã bỏ».</p>
        </XacNhan>
      ) : null}
      {hoi === 'mau' && nutMau ? (
        <XacNhan
          tieuDe={`Thay «${tenNay}» bằng bản mẫu?`}
          nutChinh="Dùng bản mẫu"
          phaHuy
          dangGui={dangGhi}
          onHuy={() => setHoi(null)}
          onDongY={() => void chay((bo) => thayNut(bo, veKhuon(nutMau)), () => setXemMau(false))}
        >
          <p>Chữ hiện tại sẽ mất.</p>
        </XacNhan>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 6: `BangChiTiet.tsx`** — bốn sửa:

1. Import: `import type { ReactNode } from 'react'` (gộp với `import { useState } from 'react'` thành `import { useState, type ReactNode } from 'react'`).
2. `interface Props`: đổi `khung?: string` thành `khung?: string | undefined`, thêm:

```ts
  /** Chip lớp / so mẫu (KhungChiTiet). */
  chip?: ReactNode
  /** Hàng thao tác ghi (KhungChiTiet) — vắng với người chỉ xem / tình huống hệ thống. */
  hanhDong?: ReactNode
```

3. Tham số hàm `BangChiTiet({ …, khung = KHUNG_MAC_DINH, chip, hanhDong })`; trong khối chip (`<div className="flex flex-wrap gap-1.5">`), đổi chữ `Bản nháp — chưa áp dụng` thành `Đang tắt — agent không chọn` và thêm `{chip}` ngay trước thẻ đóng `</div>` của khối chip đó.
4. Ngay sau thẻ đóng `</div>` của hàng tiêu đề (div bọc tên + nút «Đóng»), thêm `{hanhDong}`.

- [ ] **Step 7: Tạo `components/KhungChiTiet.tsx`**

```tsx
/** Nội dung khung chi tiết (desktop: khung trượt; điện thoại: bottom sheet) — MỘT chỗ dựng cho cả hai. */
import type { DuLieuKichBan, Ngay, NutKichBan, TemplateKichBan } from '../api'
import type { LoaiMau, SoMau } from '../khuon'
import { BangChiTiet } from './BangChiTiet'
import { HanhDongNut } from './HanhDongNut'

const CHIP = 'rounded-full border border-border px-2 py-0.5 text-[12px] text-muted'
const NHAN_MAU: Record<LoaiMau, string> = {
  giong: 'Giống mẫu',
  khac: 'Khác mẫu',
  rieng: 'Riêng của workspace',
}

function ChipLop({ n, loai }: { n: NutKichBan; loai: LoaiMau | undefined }) {
  if (n.lop === 'he_thong') return <span className={CHIP}>Hệ thống NobleX — chỉ xem</span>
  return loai ? <span className={CHIP}>{NHAN_MAU[loai]}</span> : null
}

export interface KhungChiTietProps {
  data: DuLieuKichBan
  mau: TemplateKichBan | undefined
  so: SoMau | null
  nut: string
  ngay: Ngay
  nguon: string | undefined
  ghiDuoc: boolean
  lyDoKhoa: string | null
  onChon: (id: string) => void
  onDong: () => void
  khung?: string | undefined
}

export function KhungChiTiet({
  data,
  mau,
  so,
  nut,
  ngay,
  nguon,
  ghiDuoc,
  lyDoKhoa,
  onChon,
  onDong,
  khung,
}: KhungChiTietProps) {
  const n = data.nodes.find((x) => x.id === nut)
  const loai = so?.loai[nut]
  return (
    <BangChiTiet
      id={nut}
      nut={n}
      nodes={data.nodes}
      soDo={data.soDo[nut]}
      ngay={ngay}
      nguon={nguon}
      onChon={onChon}
      onDong={onDong}
      khung={khung}
      chip={n ? <ChipLop n={n} loai={loai} /> : null}
      hanhDong={
        n?.lop === 'sale' ? (
          <HanhDongNut
            key={n.id}
            n={n}
            data={data}
            nutMau={mau?.nodes.find((x) => x.id === nut)}
            loai={loai}
            gioiHan={mau?.gioiHan}
            ghiDuoc={ghiDuoc}
            lyDoKhoa={lyDoKhoa}
            onChon={onChon}
            onDaXoa={onDong}
          />
        ) : null
      }
    />
  )
}
```

- [ ] **Step 8: Thay toàn bộ `components/KichBanScreen.tsx`**

```tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { ChonMot, NUT_PHU, O_LOC } from '@/components/ui/Bang'
import { HopThoai } from '@/components/ui/HopThoai'
import { ACTIONS } from '@/lib/actions'
import { useKhoManHinh } from '@/lib/khoManHinh'
import { useSession } from '@/lib/session'
import { LoiApi, useKichBan, useTemplate, type Ngay } from '../api'
import { laSale, soMau } from '../khuon'
import { tenNut } from '../logic'
import { DaiTrangThai } from './DaiTrangThai'
import { DanhSachNut } from './DanhSachNut'
import { DoThi } from './DoThi'
import { KhungChiTiet } from './KhungChiTiet'

const NGAY: Ngay[] = [7, 30, 90]

const CHU_GIAI: { lop: string; nhan: string }[] = [
  { lop: 'bg-ac', nhan: 'Đạt từ 80%' },
  { lop: 'bg-badge-warn-fg', nhan: '60–80%' },
  { lop: 'bg-badge-alert-fg', nhan: 'Dưới 60%' },
  { lop: 'bg-n6', nhan: 'Chưa đủ 5 lượt chấm' },
]

function ChuGiai() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-phu text-muted">
      {CHU_GIAI.map((c) => (
        <span key={c.nhan} className="flex items-center gap-1.5">
          <span className={`inline-block h-2.5 w-2.5 rounded-full ${c.lop}`} />
          {c.nhan}
        </span>
      ))}
      <span>▸ nhiều bước</span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-2.5 w-2.5 rounded-full border border-dashed border-n6" />
        đang tắt
      </span>
    </div>
  )
}

export function KichBanScreen() {
  const { nut, ngay, nguon, q } = useSearch({ from: '/_app/kich-ban' })
  const navigate = useNavigate({ from: '/kich-ban' })
  const kq = useKichBan(ngay ?? 7, nguon)
  const data = kq.data
  const sua = (moi: Record<string, unknown>) =>
    void navigate({ search: (s) => ({ ...s, ...moi }) })
  const soNutCu = data ? Object.values(data.nutCu).reduce((a, b) => a + b, 0) : 0
  const { can } = useSession()
  const suaDuoc = can([ACTIONS.AGENT_CONFIG_WRITE])
  const tpl = useTemplate()
  const gioiHan = tpl.data?.gioiHan
  const ghiDuoc = suaDuoc && gioiHan !== undefined
  // Thiếu `gioiHan` (template lỗi, hoặc BE chưa có MR trả khối này) ⇒ khoá thao tác trên tình huống, phần xem vẫn chạy.
  const lyDoKhoa =
    suaDuoc && !gioiHan && !tpl.isPending ? 'Không tải được giới hạn kịch bản — tải lại trang' : null
  // So với mẫu chỉ có nghĩa ở bản riêng — ở trạng thái mẫu mọi tình huống sale CHÍNH LÀ mẫu.
  const so = useMemo(
    () =>
      data && tpl.data && data.kichBan.trangThai === 'rieng'
        ? soMau(data.nodes.filter(laSale), tpl.data.nodes)
        : null,
    [data, tpl.data],
  )
  const chon = (id: string) => sua({ nut: id, so: undefined, them: undefined })
  const dong = () => sua({ nut: undefined, so: undefined, them: undefined })
  // Toàn màn hình bọc cả sơ đồ LẪN khung chi tiết — chỉ sơ đồ thì bấm tình huống mở bảng vô hình.
  const toanRef = useRef<HTMLDivElement>(null)
  const [toan, setToan] = useState(false)
  useEffect(() => {
    const doi = () => setToan(document.fullscreenElement === toanRef.current)
    document.addEventListener('fullscreenchange', doi)
    return () => document.removeEventListener('fullscreenchange', doi)
  }, [])
  const batTatToan = () => {
    const p = document.fullscreenElement
      ? document.exitFullscreen()
      : toanRef.current?.requestFullscreen()
    p?.catch(() => {})
  }
  // Safari iPhone KHÔNG có `requestFullscreen()` cho phần tử thường — nút bấm vào hư không.
  const coToan = typeof document !== 'undefined' && document.fullscreenEnabled !== false
  const kho = useKhoManHinh()
  // Điện thoại: danh sách + bottom sheet thay cho sơ đồ + khung trượt (xem `DanhSachNut`).
  const dienThoai = kho === 'mobile'
  const mo = !!data && !!nut
  // Dưới `lg` khung chi tiết xếp DƯỚI một sơ đồ cao gần bằng màn: chọn nút xong phải kéo
  // khung tới, không thì chạm trông như không có gì xảy ra (audit 05/10).
  const chiTietRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (mo && kho === 'tablet')
      chiTietRef.current?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
  }, [mo, nut, kho])

  const khungChiTiet = (khung?: string) =>
    data && nut ? (
      <KhungChiTiet
        data={data}
        mau={tpl.data}
        so={so}
        nut={nut}
        ngay={ngay ?? 7}
        nguon={nguon}
        ghiDuoc={ghiDuoc}
        lyDoKhoa={lyDoKhoa}
        onChon={chon}
        onDong={dong}
        khung={khung}
      />
    ) : null

  return (
    <div className="flex flex-col gap-4 px-7 pt-[22px] pb-15 max-md:px-4">
      {data ? (
        <DaiTrangThai
          kichBan={data.kichBan}
          so={so}
          suaDuoc={suaDuoc}
          onSoMau={() => sua({ so: 'mau', nut: undefined, them: undefined })}
        />
      ) : null}
      <div className="flex flex-wrap items-center gap-2 max-md:grid max-md:grid-cols-3">
        <ChonMot
          nhan="Khoảng thời gian"
          muc={NGAY.map((n) => ({ ma: n, nhan: `${n} ngày` }))}
          chon={ngay ?? 7}
          doi={(n) => sua({ ngay: n })}
          className="max-md:col-span-3"
        />
        <select
          aria-label="Nguồn"
          value={nguon ?? ''}
          onChange={(e) => sua({ nguon: e.target.value || undefined })}
          className={`${O_LOC} o-chon bg-surface max-md:col-span-3 max-md:h-10`}
        >
          <option value="">Tất cả nguồn</option>
          {data?.nguon.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
        <input
          type="search"
          aria-label="Tìm tình huống"
          placeholder="Tìm tình huống"
          value={q ?? ''}
          onChange={(e) => sua({ q: e.target.value || undefined })}
          className={`${O_LOC} w-[220px] bg-surface max-md:col-span-3 max-md:h-10 max-md:w-full`}
        />
      </div>

      {kq.isError ? (
        <div
          className="rounded-lg border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-[14px]"
          role="alert"
        >
          <p>{kq.error instanceof LoiApi ? kq.error.message : 'Không tải được kịch bản.'}</p>
          <button type="button" className={`${NUT_PHU} mt-2`} onClick={() => void kq.refetch()}>
            Thử lại
          </button>
        </div>
      ) : null}
      {kq.isPending ? <p className="text-[14px] text-muted">Đang tải…</p> : null}

      {data ? (
        <>
          <ChuGiai />
          {!data.coDuLieu ? (
            <p className="text-[13px] text-muted">
              Chưa có dữ liệu chấm — cần bật đo kịch bản cho workspace này
            </p>
          ) : null}
          {soNutCu > 0 || data.phienBanCu > 0 ? (
            <p className="text-[12px] text-muted-3">
              {soNutCu} lượt thuộc tình huống đã bỏ · {data.phienBanCu} lượt chấm bằng phiên bản cũ
              (không tính)
            </p>
          ) : null}
          {dienThoai ? (
            <>
              <DanhSachNut nodes={data.nodes} soDo={data.soDo} chon={nut} q={q ?? ''} onChon={chon} />
              {mo ? (
                // Bottom sheet: chi tiết nổi lên TẠI CHỖ ngón tay vừa chạm, danh sách vẫn nằm
                // nguyên phía sau. `starting:` trượt sheet lên từ đáy khi mở (bỏ khi giảm chuyển động).
                <HopThoai
                  onDong={dong}
                  aria-label={`Chi tiết tình huống ${tenNut(data.nodes.find((n) => n.id === nut) ?? { id: nut ?? '' })}`}
                  className="mx-0 mt-auto mb-0 max-h-[85dvh] w-full max-w-none overflow-y-auto rounded-t-lg bg-surface text-fg shadow-hop-thoai backdrop:bg-panel/45 motion-safe:transition-transform motion-safe:duration-300 motion-safe:ease-out motion-safe:starting:translate-y-full"
                >
                  {khungChiTiet('px-4 pt-4 pb-[max(1rem,env(safe-area-inset-bottom))]')}
                </HopThoai>
              ) : null}
            </>
          ) : null}
          {/* Chưa chọn gì: bản đồ chiếm cả bề ngang. Chọn một nút: khung chi tiết trượt vào từ phải
              (bề rộng chạy 0 → 376px) và bản đồ co lại theo. Ruột khung rộng CỐ ĐỊNH để chữ không
              xuống dòng lại từng nhịp trong lúc trượt; dưới `lg` khung xếp xuống dưới, không trượt. */}
          {dienThoai ? null : (
            <div
              ref={toanRef}
              className={`flex max-lg:flex-col ${toan ? 'items-stretch overflow-y-auto bg-bg p-4' : 'items-start'}`}
            >
              <div className="min-w-0 flex-1 max-lg:w-full">
                <DoThi
                  nodes={data.nodes}
                  soDo={data.soDo}
                  chon={nut}
                  q={q ?? ''}
                  onChon={chon}
                  toanManHinh={toan}
                  onToanManHinh={coToan ? batTatToan : undefined}
                />
              </div>
              <div
                ref={chiTietRef}
                data-testid="khung-chi-tiet"
                data-mo={mo ? 'true' : 'false'}
                className={`shrink-0 overflow-hidden transition-[width,opacity] duration-300 ease-out motion-reduce:transition-none max-lg:w-full ${
                  mo ? 'w-[376px] opacity-100' : 'w-0 opacity-0'
                }`}
              >
                {mo ? (
                  <div
                    className={`w-[376px] pl-4 max-lg:w-full max-lg:pt-4 max-lg:pl-0 ${toan ? 'h-full overflow-y-auto' : ''}`}
                  >
                    {khungChiTiet()}
                  </div>
                ) : null}
              </div>
            </div>
          )}
        </>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 9: «Bản nháp» → «Đang tắt» ở danh sách điện thoại**

`DanhSachNut.tsx`: đổi `{nhap ? 'Bản nháp' : pct(s)}` thành `{nhap ? 'Đang tắt' : pct(s)}`.
`tests/kich-ban.test.tsx`: đổi regex `/đạt \d+%|chưa đủ lượt chấm|Bản nháp/` thành `/đạt \d+%|chưa đủ lượt chấm|Đang tắt/`.

- [ ] **Step 10: Chạy test**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-sua.test.tsx tests/kich-ban.test.tsx tests/kich-ban-chi-tiet.test.tsx && npx tsc -b`
Expected: PASS toàn bộ; `tsc -b` thoát 0.

- [ ] **Step 11: Commit**

```bash
npx prettier --write src/features/kich-ban/useGhi.ts src/features/kich-ban/components/HanhDongNut.tsx src/features/kich-ban/components/SoHaiBan.tsx src/features/kich-ban/components/KhungChiTiet.tsx src/features/kich-ban/components/BangChiTiet.tsx src/features/kich-ban/components/KichBanScreen.tsx src/features/kich-ban/components/DanhSachNut.tsx tests/kich-ban.test.tsx tests/kich-ban-sua.test.tsx
git add src/features/kich-ban/useGhi.ts src/features/kich-ban/components/HanhDongNut.tsx src/features/kich-ban/components/SoHaiBan.tsx src/features/kich-ban/components/KhungChiTiet.tsx src/features/kich-ban/components/BangChiTiet.tsx src/features/kich-ban/components/KichBanScreen.tsx src/features/kich-ban/components/DanhSachNut.tsx tests/kich-ban.test.tsx tests/kich-ban-sua.test.tsx
git commit -m "feat(kich-ban): bật/tắt, xoá, xem/dùng bản mẫu trên một tình huống — một đường ghi useGhi

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1"
```

(zsh không tách từ của biến chứa danh sách tệp — luôn truyền danh sách tường minh như trên.)

---

### Task 7: FE — form sửa / thêm tình huống trong khung chi tiết

**Files:**
- Create: `src/features/kich-ban/components/ODanhSachDong.tsx`
- Create: `src/features/kich-ban/components/FormNut.tsx`
- Modify: `src/features/kich-ban/components/KhungChiTiet.tsx` (chế độ `che`)
- Modify: `src/features/kich-ban/components/HanhDongNut.tsx` (nút Sửa)
- Modify: `src/features/kich-ban/components/BangChiTiet.tsx` (nhãn `NHAN_TRUONG`, mục «Câu kết hỏi khách»)
- Modify: `src/features/kich-ban/components/KichBanScreen.tsx` (sửa/thêm, hỏi khi rời form dở, khung 560px)
- Test: `tests/kich-ban-sua.test.tsx` (thêm `describe`)

**Interfaces:**
- Consumes: Task 3 (`NHAN_TRUONG`, `chuanHoa`, `doDai`, `idBuocMoi`, `idRieng`, `kiemNut`, `nutTrong`, `phanLoi422`, `themNut`, `thayNut`, `veKhuon`, `LoiNut`, `LyDoChan`), Task 5 (`XacNhan`), Task 6 (`useGhi`, `cauLoi`, `KhungChiTiet`, `HanhDongNut`).
- Produces: `FormNut` props `{ dau: NutVao; moi: boolean; data: DuLieuKichBan; gioiHan: GioiHan; ghi: ReturnType<typeof useGhi>; onXong(id); onHuy(); onDoi(dirty); onChon(id) }`; `KhungChiTietProps` thêm `che: 'xem' | 'sua' | 'them'; onSua(); onXong(id); onHuy(); onDoi(dirty)`; `HanhDongNut` props thêm `onSua: () => void`.

- [ ] **Step 1: Viết test fail** — trong `tests/kich-ban-sua.test.tsx`: import `@testing-library/react` thêm `fireEvent`; import fake thêm `FAKE_KICH_BAN`. Rồi thêm vào cuối tệp:

```tsx
describe('form sửa / thêm tình huống', () => {
  it('Sửa: lưu PUT cả bộ với đúng tình huống đó đổi, rồi về bản xem', async () => {
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    const o = within(f).getByLabelText('Agent làm gì — ý 1')
    await userEvent.clear(o)
    await userEvent.type(o, 'chốt bằng một câu hỏi có hoặc không')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect(GHI_GIA[0]!.body).toEqual({
      version: 0,
      nut: sua('chot', { lam: ['chốt bằng một câu hỏi có hoặc không'] }),
    })
    await waitFor(() => expect(screen.queryByTestId('form-nut')).toBeNull())
    expect(
      within(await screen.findByTestId('bang-chi-tiet')).getByText('chốt bằng một câu hỏi có hoặc không'),
    ).toBeInTheDocument()
  })

  it('trạng thái mẫu: form báo lần lưu đầu tạo bản riêng', async () => {
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    expect(await screen.findByText(/Lần lưu này tạo bản riêng cho workspace/)).toBeInTheDocument()
  })

  it('409: giữ chữ đang gõ, cảnh báo chính tình huống này vừa đổi, lần Lưu sau cầm version mới', async () => {
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    const o = within(f).getByLabelText('Agent làm gì — ý 1')
    await userEvent.clear(o)
    await userEvent.type(o, 'bản của tôi')
    // Người khác lưu xen vào: đổi chính tình huống này, version lên 3.
    datLaiKichBanGia({ nut: sua('chot', { lam: ['bản của người khác'] }), tuTemplate: 'tv-mau-1', version: 3 })
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    expect(await within(f).findByText(/Kịch bản vừa thay đổi ở nơi khác/)).toBeInTheDocument()
    expect(within(f).getByLabelText('Agent làm gì — ý 1')).toHaveValue('bản của tôi')
    expect(await within(f).findByText(/cũng vừa được sửa ở nơi khác/)).toBeInTheDocument()
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(2))
    expect(GHI_GIA.map((g) => (g.body as { version: number }).version)).toEqual([0, 3])
  })

  it('422 trên tình huống đang sửa: lỗi hiện dưới đúng ô', async () => {
    epLoiGhiKichBanGia(422, {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'Dữ liệu gửi lên không hợp lệ (1 lỗi): body.nut[2].lam',
        fields: [{ field: 'body.nut[2].lam', reason: 'mỗi dòng tối đa 200 ký tự' }],
      },
    })
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    expect(await within(f).findByText('mỗi dòng tối đa 200 ký tự')).toBeInTheDocument()
  })

  it('Thêm: id rieng_ sinh từ tên, màn mở tình huống mới', async () => {
    const router = boot()
    await bam('Thêm tình huống')
    const f = await screen.findByTestId('form-nut')
    await userEvent.type(within(f).getByLabelText(/Tên tình huống/), 'Chê màu sơn')
    await userEvent.selectOptions(within(f).getByLabelText(/^Nhóm/), 'phan_doi')
    await userEvent.type(within(f).getByLabelText('Khi nào dùng — ý 1'), 'khách chê màu sơn')
    await userEvent.type(within(f).getByLabelText('Agent làm gì — ý 1'), 'gửi ảnh mẫu màu thật')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect((GHI_GIA[0]!.body as { nut: NutVao[] }).nut.at(-1)).toEqual({
      id: 'rieng_che_mau_son',
      ten: 'Chê màu sơn',
      nhom: 'phan_doi',
      bat: true,
      kenh: [],
      dau_hieu: ['khách chê màu sơn'],
      lam: ['gửi ảnh mẫu màu thật'],
      tool: [],
      cam: [],
      khi_thieu: '',
      cau_ket: '',
      lan_2: '',
      chi_lan_2: false,
      nguon: '',
      buoc: [],
    })
    await waitFor(() => expect(router.state.location.search).toMatchObject({ nut: 'rieng_che_mau_son' }))
  })

  it('Thêm mà để trống: báo lỗi tại chỗ, không gửi gì', async () => {
    boot()
    await bam('Thêm tình huống')
    const f = await screen.findByTestId('form-nut')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    expect(await within(f).findByText('Chưa có tên tình huống')).toBeInTheDocument()
    expect(within(f).getByText('Chọn một nhóm')).toBeInTheDocument()
    expect(GHI_GIA).toEqual([])
  })

  it('sửa dở rồi chọn tình huống khác: hỏi trước; Ở lại giữ form, Bỏ thì đi', async () => {
    const router = boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    await userEvent.type(within(f).getByLabelText('Agent làm gì — ý 1'), ' thêm')
    fireEvent.click(screen.getByTestId('nut-che_dat'))
    const hop = await screen.findByRole('dialog', { name: 'Bỏ phần đang sửa?' })
    await userEvent.click(within(hop).getByRole('button', { name: 'Ở lại' }))
    expect(router.state.location.search).toMatchObject({ nut: 'chot' })
    expect(screen.getByTestId('form-nut')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('nut-che_dat'))
    const hop2 = await screen.findByRole('dialog', { name: 'Bỏ phần đang sửa?' })
    await userEvent.click(within(hop2).getByRole('button', { name: 'Bỏ' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ nut: 'che_dat' }))
    expect(screen.queryByTestId('form-nut')).toBeNull()
  })

  it('tool agent đã gỡ không theo nút vào payload (Review Focus 4)', async () => {
    server.use(
      http.get('/api/v1/playbook', () =>
        HttpResponse.json({
          ...FAKE_KICH_BAN,
          nodes: FAKE_KICH_BAN.nodes.map((n) =>
            n.id === 'chot' ? { ...n, tool: [...n.tool, 'tool_da_go'] } : n,
          ),
        }),
      ),
    )
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    await userEvent.click(within(await screen.findByTestId('form-nut')).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    const chot = (GHI_GIA[0]!.body as { nut: NutVao[] }).nut.find((n) => n.id === 'chot')!
    expect(chot.tool).not.toContain('tool_da_go')
  })

  it('không tải được giới hạn: nút ghi khoá kèm lý do, phần xem vẫn chạy', async () => {
    server.use(
      http.get('/api/v1/playbook/template', () =>
        HttpResponse.json({ error: { code: 'X', message: 'hỏng' } }, { status: 500 }),
      ),
    )
    boot('/kich-ban?nut=chot')
    const them = await screen.findByRole('button', { name: 'Thêm tình huống' })
    await waitFor(() =>
      expect(them).toHaveAttribute('title', 'Không tải được giới hạn kịch bản — tải lại trang'),
    )
    expect(them).toBeDisabled()
    expect(await screen.findByRole('button', { name: 'Sửa' })).toBeDisabled()
    expect(within(screen.getByTestId('bang-chi-tiet')).getByText('Chốt căn')).toBeInTheDocument()
  })

  it('bản xem cùng nhãn với form', async () => {
    boot('/kich-ban?nut=che_dat')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(within(b).getByText('Kỹ năng nên dùng')).toBeInTheDocument()
    expect(within(b).getByText('Câu kết hỏi khách')).toBeInTheDocument()
    expect(within(b).getByText('Khi khách lặp lại lần 2, chuyển sang')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-sua.test.tsx -t "form sửa"`
Expected: FAIL — không có nút «Sửa» / «Thêm tình huống».

- [ ] **Step 3: Tạo `components/ODanhSachDong.tsx`**

```tsx
/**
 * Danh sách Ý của một trường nút (Khi nào dùng · Agent làm gì · Các bước · Không được làm): mỗi ý một ô, nút bỏ ý,
 * «+ Thêm ý» khoá khi đủ trần. Mỗi ý một ô chứ không một textarea «mỗi dòng một ý»: ý dài tự xuống dòng trong ô nên
 * «dòng» trên màn không phải «ý» — người dùng không đếm được mình đang có mấy ý.
 */
import { useId } from 'react'
import { NUT_HANG } from '@/components/ui/Bang'
import { O_CHUNG } from '@/components/ui/Truong'
import { Icon } from '@/components/icons'
import { doDai } from '../khuon'

interface Props {
  nhan: string
  giaTri: readonly string[]
  doiY: (i: number, s: string) => void
  them: () => void
  bo: (i: number) => void
  toiDa: number
  /** Trần ký tự mỗi ý (`maxKyTu`); vắng ⇒ không báo. */
  kyTuMoiY?: number | undefined
  /** Tổng ký tự đã tính theo luật của trường + trần; vắng ⇒ không hiện. */
  tong?: { gia: number; toiDa: number } | undefined
  batBuoc?: boolean | undefined
  goiY?: string | undefined
  loi?: string | undefined
}

export function ODanhSachDong({ nhan, giaTri, doiY, them, bo, toiDa, kyTuMoiY, tong, batBuoc, goiY, loi }: Props) {
  const id = useId()
  const moTa = loi ? `${id}-loi` : goiY ? `${id}-goiy` : undefined
  return (
    <div role="group" aria-labelledby={`${id}-nhan`} aria-describedby={moTa}>
      <p id={`${id}-nhan`} className="mb-1.5 text-phu text-muted">
        {nhan}
        {batBuoc ? (
          <span className="text-badge-alert-fg" aria-hidden="true">
            {' '}
            *
          </span>
        ) : null}
      </p>
      <ol className="space-y-2">
        {giaTri.map((y, i) => (
          <li key={i} className="flex items-start gap-2">
            <textarea
              aria-label={`${nhan} — ý ${i + 1}`}
              rows={2}
              value={y}
              onChange={(e) => doiY(i, e.target.value)}
              aria-invalid={!!loi}
              // ponytail: `field-sizing: content` tự giãn theo chữ ở Chromium; Safari giữ 2 hàng và cuộn trong ô.
              className={`${O_CHUNG} resize-none leading-[1.55] [field-sizing:content]`}
            />
            <button
              type="button"
              aria-label={`Bỏ ý ${i + 1} của ${nhan}`}
              onClick={() => bo(i)}
              className="mt-2 cursor-pointer rounded-sm p-1 text-muted hover:text-fg"
            >
              <Icon name="trash" className="size-4" />
            </button>
          </li>
        ))}
      </ol>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          disabled={giaTri.length >= toiDa}
          onClick={them}
          className={`${NUT_HANG} cursor-pointer disabled:opacity-50`}
        >
          + Thêm ý
        </button>
        <span className="text-phu text-muted tabular-nums">
          {giaTri.length}/{toiDa} ý{tong ? ` · ${tong.gia}/${tong.toiDa} ký tự` : null}
          {kyTuMoiY && giaTri.some((y) => doDai(y.trim()) > kyTuMoiY) ? ` · có ý quá ${kyTuMoiY} ký tự` : null}
        </span>
      </div>
      {goiY && !loi ? (
        <p id={`${id}-goiy`} className="mt-1 text-phu leading-[1.45] text-muted-2">
          {goiY}
        </p>
      ) : null}
      {loi ? (
        <p id={`${id}-loi`} className="mt-1 text-phu leading-[1.45] font-medium text-badge-alert-fg">
          {loi}
        </p>
      ) : null}
    </div>
  )
}
```

- [ ] **Step 4: Tạo `components/FormNut.tsx`**

```tsx
/**
 * Form sửa / thêm MỘT tình huống lớp sale (spec đợt 3 §4c). Thứ tự và nhãn ô = bản xem (`NHAN_TRUONG`). Lưu qua
 * `useGhi` của khung (một đường ghi); lỗi client (`kiemNut`) và 422 (`phanLoi422`) hiện dưới đúng ô; 409 giữ
 * nguyên chữ đang gõ — Lưu lần nữa dựng bộ từ bản vừa tải lại.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { OChon, OChonNhieu, OChu } from '@/components/ui/Truong'
import { LoiApi, type DuLieuKichBan, type GioiHan, type NutVao } from '../api'
import {
  NHAN_TRUONG,
  chuanHoa,
  doDai,
  idBuocMoi,
  idRieng,
  kiemNut,
  phanLoi422,
  thayNut,
  themNut,
  type LoiNut,
  type LyDoChan,
} from '../khuon'
import { TEN_NHOM, THU_TU_NHOM, nhanKyNang, tenNut } from '../logic'
import { cauLoi, type useGhi } from '../useGhi'
import { ODanhSachDong } from './ODanhSachDong'

interface Props {
  dau: NutVao
  moi: boolean
  data: DuLieuKichBan
  gioiHan: GioiHan
  ghi: ReturnType<typeof useGhi>
  onXong: (id: string) => void
  onHuy: () => void
  onDoi: (dirty: boolean) => void
  onChon: (id: string) => void
}

const KENH = [
  { value: 'ca_hai', nhan: 'Cả chat và cuộc gọi' },
  { value: 'chat', nhan: 'Chỉ chat' },
  { value: 'voice', nhan: 'Chỉ cuộc gọi' },
]
type DsTruong = 'dau_hieu' | 'lam' | 'cam'

export function FormNut({ dau, moi, data, gioiHan: g, ghi, onXong, onHuy, onDoi, onChon }: Props) {
  // Tool agent đã gỡ (không còn trong `gioiHan.tool`) bỏ ngay lúc mở — như BE `tuong_thich` bỏ trước khi băm: để
  // lại thì ô chọn không hiện nó mà `kiemNut` vẫn báo, người dùng không có cách gỡ (Review Focus 4).
  const [goc] = useState(() => ({ ...dau, tool: dau.tool.filter((t) => g.tool.includes(t)) }))
  const [f, setF] = useState(goc)
  const [loi, setLoi] = useState<LoiNut>({})
  const [chung, setChung] = useState<string[]>([])
  const [nutKhac, setNutKhac] = useState<LyDoChan[]>([])
  const [gap409, setGap409] = useState(false)
  const [hashLucMo] = useState(() => data.nodes.find((n) => n.id === dau.id)?.hash)
  const formRef = useRef<HTMLFormElement>(null)

  const dirty = JSON.stringify(f) !== JSON.stringify(goc)
  useEffect(() => onDoi(dirty), [dirty, onDoi])
  useEffect(() => {
    formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()
  }, [loi])

  const dat = <K extends keyof NutVao>(k: K, v: NutVao[K]) => setF((x) => ({ ...x, [k]: v }))
  const ds = (k: DsTruong) => ({
    giaTri: f[k],
    doiY: (i: number, s: string) =>
      setF((x) => ({ ...x, [k]: x[k].map((y, j) => (j === i ? s : y)) })),
    them: () => setF((x) => ({ ...x, [k]: [...x[k], ''] })),
    bo: (i: number) => setF((x) => ({ ...x, [k]: x[k].filter((_, j) => j !== i) })),
  })

  const coNguon = !moi && data.nodes.some((n) => n.id !== f.id && n.lan_2 === f.id)
  const doiNoiKhac = gap409 && !moi && data.nodes.find((n) => n.id === dau.id)?.hash !== hashLucMo
  const nhom = [...g.nhom].sort(
    (a, b) => (THU_TU_NHOM as readonly string[]).indexOf(a) - (THU_TU_NHOM as readonly string[]).indexOf(b),
  )
  const tongDauHieu = doDai(f.dau_hieu.map((s) => s.trim()).filter(Boolean).join(' | '))
  const tongCam = f.cam.reduce((s, x) => s + doDai(x.trim()), 0)

  async function luu(e: FormEvent) {
    e.preventDefault()
    setChung([])
    setNutKhac([])
    const sach = chuanHoa(f)
    const id = moi ? idRieng(sach.ten, new Set(data.nodes.map((n) => n.id))) : sach.id
    const nut = { ...sach, id }
    const l = kiemNut(nut, g)
    setLoi(l)
    if (Object.keys(l).length) return
    const kq = await ghi.ghi((bo) => (moi ? themNut(bo, nut) : thayNut(bo, nut)))
    if (kq.ok) return onXong(id)
    if (kq.loiBo.length) return setChung(kq.loiBo)
    if (kq.loi instanceof LoiApi && kq.loi.code === 'VALIDATION_ERROR') {
      const p = phanLoi422(kq.loi, kq.moi, id, ghi.ten)
      setLoi(p.cuaNut)
      setNutKhac(p.nutKhac)
      setChung(p.chung)
      return
    }
    if (kq.loi instanceof LoiApi && kq.loi.code === 'PLAYBOOK_DA_DOI') setGap409(true)
    setChung([cauLoi(kq.loi)])
  }

  return (
    <form ref={formRef} onSubmit={(e) => void luu(e)} noValidate data-testid="form-nut" className="space-y-4">
      <OChu
        ten="nut-ten"
        nhan={NHAN_TRUONG.ten}
        batBuoc
        giaTri={f.ten}
        doi={(v) => dat('ten', v)}
        goiY={`${doDai(f.ten)}/${g.maxTen} ký tự`}
        loi={loi.ten}
      />
      <OChon
        ten="nut-nhom"
        nhan={NHAN_TRUONG.nhom}
        batBuoc
        giaTri={f.nhom || null}
        doi={(v) => dat('nhom', v)}
        muc={nhom.map((x) => ({ value: x, nhan: TEN_NHOM[x] ?? x }))}
        nhanRong="Chọn nhóm"
        loi={loi.nhom}
      />
      <OChon
        ten="nut-kenh"
        nhan={NHAN_TRUONG.kenh}
        giaTri={f.kenh.length === 1 ? f.kenh[0]! : 'ca_hai'}
        doi={(v) => dat('kenh', v === 'ca_hai' ? [] : [v])}
        muc={KENH.filter((k) => k.value === 'ca_hai' || g.kenh.includes(k.value))}
        loi={loi.kenh}
      />
      <ODanhSachDong
        nhan={NHAN_TRUONG.dau_hieu}
        batBuoc
        {...ds('dau_hieu')}
        toiDa={g.maxDong.dau_hieu}
        kyTuMoiY={g.maxKyTu}
        tong={{ gia: tongDauHieu, toiDa: g.maxDauHieuTong }}
        goiY="Tả lời khách nói để agent nhận ra tình huống. Nhắc tình huống khác bằng tên, không bằng mã."
        loi={loi.dau_hieu}
      />
      <ODanhSachDong
        nhan={NHAN_TRUONG.lam}
        batBuoc
        {...ds('lam')}
        toiDa={g.maxDong.lam}
        kyTuMoiY={g.maxKyTu}
        loi={loi.lam}
      />
      <ODanhSachDong
        nhan={NHAN_TRUONG.buoc}
        giaTri={f.buoc.map((b) => b.lam)}
        doiY={(i, s) =>
          setF((x) => ({ ...x, buoc: x.buoc.map((b, j) => (j === i ? { ...b, lam: s } : b)) }))
        }
        them={() => setF((x) => ({ ...x, buoc: [...x.buoc, { id: idBuocMoi(x.buoc), lam: '' }] }))}
        bo={(i) => setF((x) => ({ ...x, buoc: x.buoc.filter((_, j) => j !== i) }))}
        toiDa={g.maxBuoc}
        kyTuMoiY={g.maxKyTu}
        goiY="Để trống nếu xử lý trong một lượt"
        loi={loi.buoc}
      />
      <ODanhSachDong
        nhan={NHAN_TRUONG.cam}
        {...ds('cam')}
        toiDa={g.maxDong.cam}
        tong={{ gia: tongCam, toiDa: g.maxCamTong }}
        loi={loi.cam}
      />
      <OChonNhieu
        ten="nut-tool"
        nhan={NHAN_TRUONG.tool}
        giaTri={f.tool}
        doi={(v) => dat('tool', v)}
        muc={g.tool.map((t) => ({ value: t, nhan: nhanKyNang(t) }))}
        goiY={`Tối đa ${g.maxTool}`}
        loi={loi.tool}
      />
      <OChu
        ten="nut-khi-thieu"
        nhan={NHAN_TRUONG.khi_thieu}
        hangChu={2}
        giaTri={f.khi_thieu}
        doi={(v) => dat('khi_thieu', v)}
        goiY={`${doDai(f.khi_thieu)}/${g.maxCau} ký tự`}
        loi={loi.khi_thieu}
      />
      <OChu
        ten="nut-cau-ket"
        nhan={NHAN_TRUONG.cau_ket}
        hangChu={2}
        giaTri={f.cau_ket}
        doi={(v) => dat('cau_ket', v)}
        goiY="Agent tự bỏ khi đang hỏi trước"
        loi={loi.cau_ket}
      />
      <OChon
        ten="nut-lan-2"
        nhan={NHAN_TRUONG.lan_2}
        giaTri={f.lan_2 || null}
        doi={(v) => dat('lan_2', v)}
        nhanRong="Không chuyển"
        muc={data.nodes.filter((n) => n.id !== f.id).map((n) => ({ value: n.id, nhan: tenNut(n) }))}
        loi={loi.lan_2}
      />
      <label className="flex items-start gap-2 text-than">
        <input
          type="checkbox"
          checked={f.chi_lan_2}
          disabled={!coNguon && !f.chi_lan_2}
          onChange={(e) => dat('chi_lan_2', e.target.checked)}
          className="mt-1"
        />
        <span>
          {NHAN_TRUONG.chi_lan_2}
          {!coNguon && !f.chi_lan_2 ? (
            <span className="block text-phu text-muted-2">
              Chưa tình huống nào chuyển sang đây khi khách lặp lại.
            </span>
          ) : null}
        </span>
      </label>
      {loi.chi_lan_2 ? <p className="text-phu font-medium text-badge-alert-fg">{loi.chi_lan_2}</p> : null}
      {doiNoiKhac ? (
        <p role="alert" className="rounded-md bg-badge-warn-bg px-3 py-2 text-phu text-badge-warn-fg">
          Tình huống này cũng vừa được sửa ở nơi khác — xem lại trước khi lưu.
        </p>
      ) : null}
      {chung.length || nutKhac.length ? (
        <ul role="alert" className="space-y-1 text-phu text-badge-alert-fg">
          {chung.map((c) => (
            <li key={c}>{c}</li>
          ))}
          {nutKhac.map((c) => (
            <li key={c.cau}>
              <button type="button" onClick={() => onChon(c.id)} className="cursor-pointer text-left underline">
                {c.cau}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {data.kichBan.trangThai === 'mau' ? (
        <p className="text-phu text-muted">
          Lần lưu này tạo bản riêng cho workspace: từ đó agent dùng bản của bạn; mẫu NobleX mới chỉ được báo ở đầu
          màn, không tự cập nhật.
        </p>
      ) : null}
      <div className={HANG_NUT}>
        <span className="mr-auto text-phu text-muted">Lưu xong, số đo tình huống này đếm lại từ đầu.</span>
        <button type="button" onClick={onHuy} className={`${NUT_PHU} cursor-pointer`}>
          Huỷ
        </button>
        <button type="submit" disabled={ghi.dangGhi} className={`${NUT_CHINH} cursor-pointer`}>
          Lưu
        </button>
      </div>
    </form>
  )
}
```

- [ ] **Step 5: `KhungChiTiet.tsx`** — thêm chế độ sửa/thêm. Sửa import đầu tệp thành:

```tsx
import type { DuLieuKichBan, Ngay, NutKichBan, NutVao, TemplateKichBan } from '../api'
import { nutTrong, veKhuon, type LoaiMau, type SoMau } from '../khuon'
import { tenNut } from '../logic'
import { useGhi } from '../useGhi'
import { BangChiTiet } from './BangChiTiet'
import { FormNut } from './FormNut'
import { HanhDongNut } from './HanhDongNut'
```

`KhungChiTietProps` thêm:

```ts
  che: 'xem' | 'sua' | 'them'
  onSua: () => void
  onXong: (id: string) => void
  onHuy: () => void
  onDoi: (dirty: boolean) => void
```

Thân hàm (thay nguyên thân `KhungChiTiet`; destructure thêm `che, onSua, onXong, onHuy, onDoi`):

```tsx
  const ghi = useGhi(data, mau?.gioiHan)
  const n = data.nodes.find((x) => x.id === nut)
  const loai = so?.loai[nut]
  const g = mau?.gioiHan
  const khungSua = (moi: boolean, dau: NutVao, gh: NonNullable<typeof g>) => (
    <section
      data-testid="khung-sua"
      className={`space-y-3 ${khung ?? 'rounded-lg border border-border bg-surface p-4'}`}
    >
      <h2 className="text-muc font-semibold">{moi ? 'Thêm tình huống' : `Sửa «${n ? tenNut(n) : nut}»`}</h2>
      <FormNut
        key={moi ? 'moi' : nut}
        dau={dau}
        moi={moi}
        data={data}
        gioiHan={gh}
        ghi={ghi}
        onXong={onXong}
        onHuy={onHuy}
        onDoi={onDoi}
        onChon={onChon}
      />
    </section>
  )
  // Nút Sửa/Thêm khoá khi thiếu `gioiHan`, nên `g` luôn có ở hai nhánh này.
  if (g && che === 'them') return khungSua(true, nutTrong(), g)
  if (g && che === 'sua' && n) return khungSua(false, veKhuon(n), g)
  return (
    <BangChiTiet
      id={nut}
      nut={n}
      nodes={data.nodes}
      soDo={data.soDo[nut]}
      ngay={ngay}
      nguon={nguon}
      onChon={onChon}
      onDong={onDong}
      khung={khung}
      chip={n ? <ChipLop n={n} loai={loai} /> : null}
      hanhDong={
        n?.lop === 'sale' ? (
          <HanhDongNut
            key={n.id}
            n={n}
            data={data}
            nutMau={mau?.nodes.find((x) => x.id === nut)}
            loai={loai}
            gioiHan={g}
            ghiDuoc={ghiDuoc}
            lyDoKhoa={lyDoKhoa}
            onChon={onChon}
            onDaXoa={onDong}
            onSua={onSua}
          />
        ) : null
      }
    />
  )
```

- [ ] **Step 6: `HanhDongNut.tsx`** — thêm prop `onSua: () => void` (vào `Props` và destructure), và trong hàng `coGhi`, NGAY TRƯỚC `<span className="flex items-center gap-2 text-than">Đang dùng…`:

```tsx
          <button
            type="button"
            disabled={khoa}
            onClick={onSua}
            className={`${NUT_PHU} cursor-pointer disabled:opacity-50`}
          >
            Sửa
          </button>
```

- [ ] **Step 7: `BangChiTiet.tsx`** — bản xem cùng nhãn với form: thêm `import { NHAN_TRUONG } from '../khuon'`; đổi các nhãn mục:

```tsx
          <Muc ten={NHAN_TRUONG.dau_hieu} ds={doc.dauHieu} />
          <Muc ten={NHAN_TRUONG.lam} ds={doc.lam} />
          <Muc ten={NHAN_TRUONG.buoc} ds={doc.buoc} so />
          <Muc ten={NHAN_TRUONG.cam} ds={doc.cam} />
```

Tiêu đề «Kỹ năng dùng» → `{NHAN_TRUONG.tool}`; «Khi thiếu tài liệu» → `{NHAN_TRUONG.khi_thieu}`; «Đi tiếp» → `{NHAN_TRUONG.lan_2}`. Ngay SAU khối `doc.khiThieu ? (…) : null`, thêm:

```tsx
          {nut.cau_ket ? (
            <section>
              <h3 className="mb-1 text-phu font-medium text-muted">{NHAN_TRUONG.cau_ket}</h3>
              <p className="text-[13px]">{docDe(nut.cau_ket, ten)}</p>
            </section>
          ) : null}
```

- [ ] **Step 8: `KichBanScreen.tsx`** — nối sửa / thêm / hỏi khi rời form dở:

Import thêm `NUT_CHINH` (gộp vào dòng `@/components/ui/Bang`) và `import { XacNhan } from './XacNhan'`.

Dòng `useSearch` thành: `const { nut, ngay, nguon, q, them } = useSearch({ from: '/_app/kich-ban' })`.

Thay hai dòng `const chon = …` / `const dong = …` bằng:

```tsx
  const soSale = data ? data.nodes.filter(laSale).length : 0
  const day = gioiHan !== undefined && soSale >= gioiHan.maxNut
  // Sửa / thêm (spec §4c–4d). `suaNut` = id đang mở form; `?nut=` đổi (kể cả Back) là tự về bản xem.
  const [suaNut, setSuaNut] = useState<string | null>(null)
  const dangSua = !them && !!nut && suaNut === nut
  const dirty = useRef(false)
  const [cho, setCho] = useState<(() => void) | null>(null)
  /** Mọi đường đổi nội dung khung đi qua đây: đang sửa dở thì hỏi «Bỏ phần đang sửa?» trước. */
  const diKhi = (lam: () => void) => {
    if ((dangSua || them) && dirty.current) setCho(() => lam)
    else lam()
  }
  const roi = (moi: Record<string, unknown>) =>
    diKhi(() => {
      dirty.current = false
      setSuaNut(null)
      sua(moi)
    })
  const chon = (id: string) => roi({ nut: id, so: undefined, them: undefined })
  const dong = () => roi({ nut: undefined, so: undefined, them: undefined })
```

`onSoMau` của `DaiTrangThai` thành `() => roi({ so: 'mau', nut: undefined, them: undefined })`.

Dòng `const mo = !!data && !!nut` thành:

```tsx
  const mo = !!data && (them === true || !!nut)
  const rong = them === true || dangSua
```

`useEffect` cuộn khung: deps `[mo, nut, them, kho]`.

`khungChiTiet` thành:

```tsx
  const khungChiTiet = (khung?: string) =>
    data && (nut || them) ? (
      <KhungChiTiet
        data={data}
        mau={tpl.data}
        so={so}
        nut={nut ?? ''}
        che={them ? 'them' : dangSua ? 'sua' : 'xem'}
        ngay={ngay ?? 7}
        nguon={nguon}
        ghiDuoc={ghiDuoc}
        lyDoKhoa={lyDoKhoa}
        onChon={chon}
        onDong={dong}
        onSua={() => setSuaNut(nut ?? null)}
        onXong={(id) => {
          dirty.current = false
          setSuaNut(null)
          sua({ nut: id, them: undefined })
        }}
        onHuy={() =>
          diKhi(() => {
            dirty.current = false
            setSuaNut(null)
            if (them) sua({ them: undefined })
          })
        }
        onDoi={(d) => {
          dirty.current = d
        }}
        khung={khung}
      />
    ) : null
```

Trong hàng bộ lọc, sau ô `input type="search"`, thêm:

```tsx
        {suaDuoc ? (
          <button
            type="button"
            disabled={!ghiDuoc || day}
            title={lyDoKhoa ?? (day && gioiHan ? `Đã đủ ${gioiHan.maxNut} tình huống` : undefined)}
            onClick={() => roi({ them: true, nut: undefined, so: undefined })}
            className={`${NUT_CHINH} ml-auto cursor-pointer max-md:col-span-3`}
          >
            Thêm tình huống
          </button>
        ) : null}
```

Bottom sheet: `aria-label` thành

```tsx
                  aria-label={
                    them
                      ? 'Thêm tình huống'
                      : `${dangSua ? 'Sửa' : 'Chi tiết'} tình huống ${tenNut(data.nodes.find((n) => n.id === nut) ?? { id: nut ?? '' })}`
                  }
```

Khung desktop: hai chỗ `w-[376px]` thành `${rong ? 'w-[560px]' : 'w-[376px]'}` (giữ nguyên phần còn lại của class), cụ thể:

```tsx
                className={`shrink-0 overflow-hidden transition-[width,opacity] duration-300 ease-out motion-reduce:transition-none max-lg:w-full ${
                  mo ? `${rong ? 'w-[560px]' : 'w-[376px]'} opacity-100` : 'w-0 opacity-0'
                }`}
```

```tsx
                    className={`${rong ? 'w-[560px]' : 'w-[376px]'} pl-4 max-lg:w-full max-lg:pt-4 max-lg:pl-0 ${toan ? 'h-full overflow-y-auto' : ''}`}
```

Cuối JSX, ngay trước thẻ đóng `</div>` ngoài cùng:

```tsx
      {cho ? (
        <XacNhan
          tieuDe="Bỏ phần đang sửa?"
          nutPhu="Ở lại"
          nutChinh="Bỏ"
          phaHuy
          onHuy={() => setCho(null)}
          onDongY={() => {
            const lam = cho
            setCho(null)
            lam()
          }}
        >
          <p>Những gì vừa gõ chưa được lưu.</p>
        </XacNhan>
      ) : null}
```

- [ ] **Step 9: Chạy test**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-sua.test.tsx tests/kich-ban.test.tsx tests/kich-ban-chi-tiet.test.tsx && npx tsc -b`
Expected: PASS toàn bộ; `tsc -b` thoát 0.

- [ ] **Step 10: Commit**

```bash
npx prettier --write src/features/kich-ban/components/ODanhSachDong.tsx src/features/kich-ban/components/FormNut.tsx src/features/kich-ban/components/KhungChiTiet.tsx src/features/kich-ban/components/HanhDongNut.tsx src/features/kich-ban/components/BangChiTiet.tsx src/features/kich-ban/components/KichBanScreen.tsx tests/kich-ban-sua.test.tsx
git add src/features/kich-ban/components/ODanhSachDong.tsx src/features/kich-ban/components/FormNut.tsx src/features/kich-ban/components/KhungChiTiet.tsx src/features/kich-ban/components/HanhDongNut.tsx src/features/kich-ban/components/BangChiTiet.tsx src/features/kich-ban/components/KichBanScreen.tsx tests/kich-ban-sua.test.tsx
git commit -m "feat(kich-ban): form sửa/thêm tình huống trong khung chi tiết, hỏi trước khi bỏ phần đang sửa

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1"
```

---

### Task 8: FE — khung «So với mẫu» + chữ khác mẫu / riêng trên sơ đồ và danh sách

**Files:**
- Create: `src/features/kich-ban/components/SoVoiMau.tsx`
- Modify: `src/features/kich-ban/khuon.ts` (thêm `HAU_TO_MAU`)
- Modify: `src/features/kich-ban/components/DoThi.tsx`, `DanhSachNut.tsx` (prop `loaiMau`)
- Modify: `src/features/kich-ban/components/KichBanScreen.tsx` (`?so=mau`, truyền `loaiMau`, chú giải)
- Test: `tests/kich-ban-sua.test.tsx` (thêm `describe`)

**Interfaces:**
- Consumes: Task 3 (`canThemTruoc`, `themNut`, `veKhuon`, `boSale`, `heThong`, `SoMau`, `LoaiMau`), Task 6 (`useGhi`, `cauLoi`), Task 7 (`roi`, `chon`, `dong` trong `KichBanScreen`).
- Produces: `HAU_TO_MAU: Partial<Record<LoaiMau, string>>`; `SoVoiMau` props `{ data; mau: TemplateKichBan; so: SoMau; ghiDuoc: boolean; onChon(id); onDong(); khung?: string | undefined }`; `DoThi`/`DanhSachNut` prop `loaiMau?: Record<string, LoaiMau> | undefined`.

- [ ] **Step 1: Viết test fail** — thêm vào cuối `tests/kich-ban-sua.test.tsx`:

```tsx
describe('so với mẫu', () => {
  const RIENG = { ...MAU_GIA[2]!, id: 'rieng_mau_son', ten: 'Chê màu sơn', lan_2: '' }
  const datRieng = () =>
    datLaiKichBanGia({
      nut: [
        ...sua('che_dat', { cau_ket: 'hỏi khách có muốn xem căn rẻ hơn' }).filter((n) => n.id !== 'chot'),
        RIENG,
      ],
      tuTemplate: 'tv-cu',
      version: 5,
    })

  it('sơ đồ ghi chữ khác mẫu / riêng sau tên', async () => {
    datRieng()
    boot()
    await waitFor(() => expect(screen.getByTestId('nut-che_dat')).toHaveTextContent('· khác mẫu'))
    expect(screen.getByTestId('nut-rieng_mau_son')).toHaveTextContent('· riêng')
    expect(screen.getByTestId('nut-goi_dien_ra')).not.toHaveTextContent('mẫu')
  })

  it('mở So với mẫu: ba nhóm; bấm một tình huống thì mở nó', async () => {
    datRieng()
    const router = boot()
    await userEvent.click(await screen.findByRole('button', { name: 'So với mẫu (1 khác · 1 chưa có)' }))
    const p = await screen.findByTestId('so-voi-mau')
    expect(within(p).getByTestId('nhom-khac')).toHaveTextContent('Khách chê đắt')
    expect(within(p).getByTestId('nhom-chua-co')).toHaveTextContent('Chốt căn')
    expect(within(p).getByTestId('nhom-rieng')).toHaveTextContent('Chê màu sơn')
    await userEvent.click(within(p).getByRole('button', { name: 'Khách chê đắt' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ nut: 'che_dat' }))
    expect(router.state.location.search).not.toHaveProperty('so')
  })

  it('Thêm vào: gửi nút mẫu giữ nguyên id', async () => {
    datRieng()
    boot('/kich-ban?so=mau')
    await bam('Thêm «Chốt căn» vào bản của bạn')
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect((GHI_GIA[0]!.body as { nut: NutVao[] }).nut.at(-1)).toEqual(MAU_GIA[2])
  })
})
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-sua.test.tsx -t "so với mẫu"`
Expected: FAIL — sơ đồ không có «· khác mẫu», không có `so-voi-mau`.

- [ ] **Step 3: `khuon.ts`** — thêm cuối tệp:

```ts
/** Chữ sau tên tình huống trên sơ đồ / danh sách (spec §4h) — CHỮ, không ký hiệu: font tự host không có ✎/＋. */
export const HAU_TO_MAU: Partial<Record<LoaiMau, string>> = { khac: ' · khác mẫu', rieng: ' · riêng' }
```

- [ ] **Step 4: Tạo `components/SoVoiMau.tsx`**

```tsx
/**
 * «So với mẫu NobleX» (spec §4f): ba nhóm — khác mẫu · có trong mẫu nhưng bản riêng chưa có · riêng của workspace.
 * «Khác» là so với bản mẫu HIỆN TẠI: BE không giữ mẫu lúc áp dụng nên không phân biệt được ai đổi.
 */
import { useState } from 'react'
import { NUT_PHU } from '@/components/ui/Bang'
import type { DuLieuKichBan, NutKichBan, TemplateKichBan } from '../api'
import { boSale, canThemTruoc, heThong, themNut, veKhuon, type SoMau } from '../khuon'
import { tenNut } from '../logic'
import { cauLoi, useGhi } from '../useGhi'

interface Props {
  data: DuLieuKichBan
  mau: TemplateKichBan
  so: SoMau
  ghiDuoc: boolean
  onChon: (id: string) => void
  onDong: () => void
  khung?: string | undefined
}

export function SoVoiMau({
  data,
  mau,
  so,
  ghiDuoc,
  onChon,
  onDong,
  khung = 'rounded-lg border border-border bg-surface p-4',
}: Props) {
  const { ghi, dangGhi, ten } = useGhi(data, mau.gioiHan)
  const [bao, setBao] = useState<Record<string, string>>({})
  const tenCa = { ...Object.fromEntries(mau.nodes.map((n) => [n.id, tenNut(n)])), ...ten }
  const theo = (l: 'khac' | 'rieng') => data.nodes.filter((n) => so.loai[n.id] === l)

  async function themVao(m: NutKichBan) {
    const truoc = canThemTruoc(m, boSale(data.nodes), heThong(data.nodes), mau.nodes, tenCa)
    if (truoc) return setBao((b) => ({ ...b, [m.id]: truoc }))
    const kq = await ghi((bo) => themNut(bo, veKhuon(m)))
    if (!kq.ok) setBao((b) => ({ ...b, [m.id]: kq.loiBo[0] ?? cauLoi(kq.loi) }))
  }

  const danhSach = (tieuDe: string, ds: NutKichBan[], testId: string) => (
    <section data-testid={testId} className="space-y-1">
      <h3 className="text-phu font-medium text-muted">
        {tieuDe} ({ds.length})
      </h3>
      {ds.length ? (
        <ul className="space-y-1">
          {ds.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => onChon(n.id)}
                className="block w-full cursor-pointer rounded-md border border-border-field px-3 py-1.5 text-left text-than hover:bg-fill-strong"
              >
                {tenNut(n)}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted">Không có.</p>
      )}
    </section>
  )

  return (
    <aside data-testid="so-voi-mau" className={`space-y-4 ${khung}`}>
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-muc font-semibold">So với mẫu NobleX</h2>
        <button type="button" onClick={onDong} className={`${NUT_PHU} cursor-pointer`}>
          Đóng
        </button>
      </div>
      <p className="text-phu text-muted">
        So với bản mẫu hiện tại — không phân biệt bạn tự sửa hay NobleX đổi mẫu.
      </p>
      {danhSach('Khác mẫu', theo('khac'), 'nhom-khac')}
      <section data-testid="nhom-chua-co" className="space-y-1">
        <h3 className="text-phu font-medium text-muted">
          Có trong mẫu, chưa có trong bản của bạn ({so.chuaCo.length})
        </h3>
        {so.chuaCo.length ? (
          <ul className="space-y-2">
            {so.chuaCo.map((m) => (
              <li key={m.id} className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 text-than">{tenNut(m)}</span>
                  {ghiDuoc ? (
                    <button
                      type="button"
                      disabled={dangGhi}
                      onClick={() => void themVao(m)}
                      aria-label={`Thêm «${tenNut(m)}» vào bản của bạn`}
                      className={`${NUT_PHU} cursor-pointer`}
                    >
                      Thêm vào
                    </button>
                  ) : null}
                </div>
                {bao[m.id] ? (
                  <p role="alert" className="text-phu text-badge-alert-fg">
                    {bao[m.id]}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-muted">Không có.</p>
        )}
      </section>
      {danhSach('Riêng của workspace', theo('rieng'), 'nhom-rieng')}
    </aside>
  )
}
```

- [ ] **Step 5: `DoThi.tsx`** — prop `loaiMau?: Record<string, LoaiMau> | undefined` (thêm vào `Props` và destructure; import `HAU_TO_MAU, type LoaiMau` từ `'../khuon'`). Trong `nodes.map((n) => {…})`, sau `const dangChon = chon === n.id` thêm:

```tsx
          const hauTo = HAU_TO_MAU[loaiMau?.[n.id] ?? 'giong']
```

`aria-label` của `<g>` thành `` `${tenNut(n)}${hauTo ?? ''} — ${TEN_NHOM[n.nhom] ?? n.nhom}, ${pct(soDo[n.id])}` ``. Trong `<text>`, ngay SAU khối `{pctNgan(soDo[n.id]) && (…)}`:

```tsx
                {hauTo ? <tspan className="fill-muted-2 text-phu font-normal">{hauTo}</tspan> : null}
```

> ponytail: bề ngang nhãn (`boCucCay`) không tính hậu tố — «· khác mẫu» ~94px, nằm gọn trong `CAY.lan` 120 chừa bên phải; đường chuyển tiếp của nút đang chọn có thể chạm hậu tố. Tính vào `boCucCay` nếu thấy chồng.

- [ ] **Step 6: `DanhSachNut.tsx`** — prop `loaiMau?: Record<string, LoaiMau> | undefined` (import `HAU_TO_MAU, type LoaiMau` từ `'../khuon'`). Trong span tên, ngay sau `{n.loai === 'luong' ? <span className="text-muted"> ▸</span> : null}`:

```tsx
                        {HAU_TO_MAU[loaiMau?.[n.id] ?? 'giong'] ? (
                          <span className="text-phu text-muted">{HAU_TO_MAU[loaiMau?.[n.id] ?? 'giong']}</span>
                        ) : null}
```

- [ ] **Step 7: `KichBanScreen.tsx`** — nối khung so mẫu:

1. Import `import { SoVoiMau } from './SoVoiMau'`; `useSearch` thêm `so: soMo` (`const { nut, ngay, nguon, q, them, so: soMo } = useSearch(…)`).
2. `ChuGiai` nhận prop `{ rieng }: { rieng: boolean }` và thêm cuối danh sách:

```tsx
      {rieng ? (
        <>
          <span>· khác mẫu: khác bản mẫu NobleX hiện tại</span>
          <span>· riêng: workspace tự thêm</span>
        </>
      ) : null}
```

   Chỗ gọi: `<ChuGiai rieng={data.kichBan.trangThai === 'rieng'} />`.
3. `const mo = …` thành:

```tsx
  const xemSo = soMo === 'mau' && !!so && !!tpl.data && !them
  const mo = !!data && (them === true || xemSo || !!nut)
```

4. `khungChiTiet` thay toàn bộ bằng (nhánh so mẫu đứng TRƯỚC `KhungChiTiet`):

```tsx
  const khungChiTiet = (khung?: string) =>
    data && xemSo && so && tpl.data ? (
      <SoVoiMau
        data={data}
        mau={tpl.data}
        so={so}
        ghiDuoc={ghiDuoc}
        onChon={chon}
        onDong={dong}
        khung={khung}
      />
    ) : data && (nut || them) ? (
      <KhungChiTiet
        data={data}
        mau={tpl.data}
        so={so}
        nut={nut ?? ''}
        che={them ? 'them' : dangSua ? 'sua' : 'xem'}
        ngay={ngay ?? 7}
        nguon={nguon}
        ghiDuoc={ghiDuoc}
        lyDoKhoa={lyDoKhoa}
        onChon={chon}
        onDong={dong}
        onSua={() => setSuaNut(nut ?? null)}
        onXong={(id) => {
          dirty.current = false
          setSuaNut(null)
          sua({ nut: id, them: undefined })
        }}
        onHuy={() =>
          diKhi(() => {
            dirty.current = false
            setSuaNut(null)
            if (them) sua({ them: undefined })
          })
        }
        onDoi={(d) => {
          dirty.current = d
        }}
        khung={khung}
      />
    ) : null
```

5. Bottom sheet `aria-label`: thêm nhánh đầu `xemSo ? 'So với mẫu NobleX' : …`.
6. `DanhSachNut` và `DoThi`: thêm `loaiMau={so?.loai}`.

- [ ] **Step 8: Chạy test**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run tests/kich-ban-sua.test.tsx tests/kich-ban.test.tsx tests/kich-ban-chi-tiet.test.tsx tests/kich-ban-logic.test.ts && npx tsc -b`
Expected: PASS toàn bộ; `tsc -b` thoát 0.

- [ ] **Step 9: Commit**

```bash
npx prettier --write src/features/kich-ban/components/SoVoiMau.tsx src/features/kich-ban/khuon.ts src/features/kich-ban/components/DoThi.tsx src/features/kich-ban/components/DanhSachNut.tsx src/features/kich-ban/components/KichBanScreen.tsx tests/kich-ban-sua.test.tsx
git add src/features/kich-ban/components/SoVoiMau.tsx src/features/kich-ban/khuon.ts src/features/kich-ban/components/DoThi.tsx src/features/kich-ban/components/DanhSachNut.tsx src/features/kich-ban/components/KichBanScreen.tsx tests/kich-ban-sua.test.tsx
git commit -m "feat(kich-ban): so với mẫu NobleX + chữ khác mẫu/riêng trên sơ đồ và danh sách

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1"
```

---

### Task 9: Tài liệu, cổng toàn repo, kiểm trên trình duyệt

**Files:**
- Modify: `CLAUDE.md` (FE) — mục mới + bảng «Xem trước, sửa sau» + Change Log

**Interfaces:**
- Consumes: toàn bộ Task 1–8.
- Produces: tài liệu; bằng chứng `make check`-tương đương và kiểm tay.

- [ ] **Step 1: `CLAUDE.md` FE**

Trong bảng của mục «Xem trước, sửa sau — luật của MỌI màn có form bản ghi», thêm hàng:

```markdown
| `/kich-ban` khung chi tiết  | `BangChiTiet.tsx` (form `FormNut.tsx`, nhãn chung `NHAN_TRUONG`) |
```

Thêm mục mới ngay TRƯỚC `## Thử agent — hai tab, …`:

```markdown
## Màn Kịch bản (`/kich-ban`) — sửa được (đợt 3, 2026-10-06)

Spec `docs/superpowers/specs/2026-10-06-playbook-template-dot-3-design.md`. API đợt 2 của backend (`/playbook*`).

- **Một đường ghi:** mọi thao tác trên tình huống đi qua `useGhi().ghi(bienDoi)` (`features/kich-ban/useGhi.ts`): bộ sale lấy từ lần tải `GET /playbook` mới nhất → `bienDoi` → `kiemBo` → `PUT /playbook {version, nut}`. Mutation chờ tải lại xong mới hết `isPending` ⇒ nút ghi khoá tới lúc `data` mang `version` mới. **Đừng giữ bản sao bộ nút trong state** — bản sao cũ là cách ghi đè lần lưu của người khác.
- **Payload dựng từ `GET /playbook`:** BE đã lọc tool agent gỡ (`nut.tuong_thich`) nên không 422 trên tình huống người dùng không sửa. `veKhuon` lấy ĐÚNG các khoá `NutVao` (BE `extra="forbid"`).
- **Con số luật đọc từ `gioiHan`** (`GET /playbook/template`), không chép tay. Thiếu `gioiHan` ⇒ nút ghi khoá kèm lý do, phần xem vẫn chạy. `kiemBo`/`kiemNut` (`khuon.ts`) là bản THỨ BA của luật (agent · BE · FE) — chỉ để báo sớm bằng tên, BE 422 là chốt chặn.
- **Công tắc «dùng kịch bản theo role» ở `/kich-ban`, KHÔNG ở tab role `/agent`:** `/agent` gom thay đổi vào bản nháp + «Lưu và áp dụng»; công tắc này ghi ngay bằng `PUT /playbook/role-dung` (version riêng). Chỉ gửi role workspace đang có.
- **Ngoại lệ có ý thức điều 6 của «Xem trước, sửa sau»:** sơ đồ vẫn hiện cạnh form (người sửa cần nó để chọn «chuyển sang»); rời form sửa dở hỏi «Bỏ phần đang sửa?» (`diKhi` trong `KichBanScreen`).
- Fake `features/kich-ban/msw.ts` **CÓ TRẠNG THÁI** (`datLaiKichBanGia` ở `beforeEach`, `epLoiGhiKichBanGia`, `GHI_GIA` ghi thân mọi lần ghi). Chưa áp dụng ⇒ trả nguyên bộ mẫu như BE trả `playbook.json`.
```

Change Log — thêm một hàng lên ĐẦU bảng (ngay dưới dòng `| ---------- | -------- |`):

```markdown
| 2026-10-06 | **`/kich-ban` sửa được (playbook template đợt 3).** Dải trạng thái (mẫu / bản riêng / có mẫu mới) + công tắc dùng kịch bản theo role (`PUT /playbook/role-dung`) + Áp lại mẫu (`POST /playbook/ap-dung`); khung chi tiết có Sửa / bật-tắt / Xoá (chặn khi tình huống khác chuyển sang) / Xem-Dùng bản mẫu; «Thêm tình huống» (id `rieng_…` từ tên); «So với mẫu» ba nhóm. Một đường ghi `useGhi` (mục «Màn Kịch bản — sửa được»). Form trong khung 560px, bottom sheet trên điện thoại. «Bản nháp» → «Đang tắt». Nhãn nhật ký `playbook.*`. Cần backend trả `gioiHan` ở `GET /playbook/template` (MR riêng) — thiếu thì nút ghi khoá, phần xem chạy. |
```

- [ ] **Step 2: Cổng toàn repo**

```bash
NODE_OPTIONS=--no-experimental-webstorage npx vitest run > /tmp/kb-vitest.txt 2>&1; tail -15 /tmp/kb-vitest.txt
npx eslint . --max-warnings 0
npx tsc -b
npx prettier --check src/features/kich-ban src/routes/_app/kich-ban.tsx src/features/platform/so-hanh-dong.ts tests/kich-ban-*.ts tests/kich-ban-*.tsx
```

Expected: vitest không bài đỏ nào (so mốc `origin/develop`: chạy cùng lệnh trên một bản checkout develop nếu có bài đỏ để chứng minh không phải của nhánh); eslint 0 warning; `tsc -b` thoát 0; prettier sạch trên tệp đã đụng.

- [ ] **Step 3: Kiểm trên trình duyệt — MSW**

Cổng 5273 có thể đang bận bởi dev server của checkout khác (background task của phiên trước): dừng nó trước (`TaskStop` theo id, hoặc `lsof -ti :5273` để xem rồi hỏi người dùng nếu không phải của phiên này). Chạy nền trong worktree: `npx vite --port 5273 --strictPort`. Dùng Playwright (MCP) mở `http://localhost:5273/kich-ban`, đi qua: dải trạng thái + bật công tắc Sale; Sửa «Chốt căn» → Lưu (dải đổi sang «Bản riêng»); Thêm tình huống; Xoá tình huống vừa thêm; bật/tắt; So với mẫu; Áp lại mẫu; khung 400px (bottom sheet, sửa trong sheet, hỏi khi bỏ dở). Chụp màn hình các bước chính.

- [ ] **Step 4: Kiểm trên trình duyệt — backend thật**

BE: trong `.wt-portal-playbook-json` (nhánh Task 1) chạy API theo `make api` của repo BE (PG 5444 ở `0976`). FE: `VITE_MSW=0` (tệp `.env.local` trong worktree), khởi động lại vite. Đăng nhập `dang@anphuland.vn` / `odyssey-dev`, lặp lại các bước Step 3; kiểm `GET /playbook/template` có `gioiHan` (tab Network) và `PUT /playbook` 200; một 409 thật (mở hai tab, lưu ở tab 1 rồi lưu ở tab 2). Xong thì xoá `.env.local`, dừng hai server.

- [ ] **Step 5: Commit tài liệu**

```bash
npx prettier --write CLAUDE.md
git add CLAUDE.md
git commit -m "docs: /kich-ban sửa được — một đường ghi, gioiHan, công tắc role (đợt 3)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MoG8nVSiqzoQCnXd9w9Mc1"
```

> Prettier trên `CLAUDE.md`: nếu tệp đang lệch định dạng sẵn (nợ cũ) thì `--write` sẽ đổi cả bảng — khi đó KHÔNG chạy prettier cho `CLAUDE.md`, chỉ commit phần thêm.

**Sau Task 9:** review cả nhánh (FE + commit BE), rồi theo `finishing-a-development-branch`: push + MR BE (`feat/playbook-template-gioi-han` → `develop`) trước, MR FE (`feat/kich-ban-sua` → `develop`) sau — chỉ khi người dùng bảo.
