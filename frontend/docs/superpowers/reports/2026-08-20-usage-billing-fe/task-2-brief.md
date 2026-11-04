### Task 2: `dinh-dang.ts` — một chỗ định dạng, có test

**Files:**
- Create: `src/features/billing/dinh-dang.ts`
- Test: `tests/billing-dinh-dang.test.ts`

**Interfaces:**
- Produces: `tien(x: Tien): string` · `tienDay(x: Tien): string` · `token(n: number): string` · `giay(s: number): string` · `phanTram(a: number, b: number): string` · `rong(v: string | null | undefined): string` · `type Tien = string`

**VÌ SAO làm trước mọi màn:** đây là thứ bản demo cũ hỏng nặng nhất (cùng một số tiền hiện ba kiểu ở ba ô) và là thứ rẻ nhất để chốt. Ba màn đều gọi qua đây, không format tại chỗ.

- [ ] **Step 1: Viết test (sẽ đỏ)**

```ts
// tests/billing-dinh-dang.test.ts
import { describe, expect, it } from 'vitest'
import { giay, phanTram, rong, tien, tienDay, token } from '@/features/billing/dinh-dang'

describe('tien', () => {
  it('VND không chữ số thập phân, dấu . phân nghìn', () => {
    expect(tien('1204500.4821')).toBe('1.204.500')
  })
  it('nhận string chứ không number — Decimal(20,10) mất chính xác khi qua number', () => {
    // 9007199254740993 > Number.MAX_SAFE_INTEGER: qua number sẽ thành …992
    expect(tien('9007199254740993')).toBe('9.007.199.254.740.993')
  })
  it('0 vẫn là 0, không phải chuỗi rỗng', () => {
    expect(tien('0')).toBe('0')
  })
})

describe('tienDay', () => {
  it('giữ 4 chữ số thập phân cho tooltip đối soát', () => {
    expect(tienDay('1204500.4821')).toBe('1.204.500,4821 ₫')
  })
})

describe('token', () => {
  it('< 10 000 hiện nguyên', () => expect(token(9999)).toBe('9.999'))
  it('≥ 10 000 rút về k', () => expect(token(48250)).toBe('48 k'))
  it('≥ 1 000 000 rút về M, 2 số lẻ', () => expect(token(1204500)).toBe('1,20 M'))
})

describe('giay', () => {
  it('< 60 hiện giây một số lẻ', () => expect(giay(48.24)).toBe('48,2 s'))
  it('≥ 60 tách giờ/phút/giây', () => expect(giay(4821)).toBe('1h 20m 21s'))
  it('142.44 của fixture BE', () => expect(giay(142.44)).toBe('2m 22s'))
})

describe('phanTram', () => {
  it('một số lẻ', () => expect(phanTram(148, 4352)).toBe('3,4%'))
  it('mẫu 0 ra — chứ không NaN%', () => expect(phanTram(5, 0)).toBe('—'))
})

describe('rong', () => {
  // provider/model của component audio là '' (DEFAULT '', KHÔNG phải NULL)
  it("'' ra —", () => expect(rong('')).toBe('—'))
  it('null ra —', () => expect(rong(null)).toBe('—'))
  it('có giá trị thì trả nguyên', () => expect(rong('anthropic')).toBe('anthropic'))
})
```

- [ ] **Step 2: Chạy để chắc nó đỏ**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-dinh-dang.test.ts`
Expected: FAIL — không import được module chưa tồn tại.

- [ ] **Step 3: Viết `dinh-dang.ts`**

```ts
/**
 * Định dạng số của module billing — MỘT chỗ duy nhất.
 *
 * ⚠️ TIỀN LÀ `string`, KHÔNG phải `number`. `chi_phi`/`chi_phi_tong` phía BE là
 * `numeric(20,10)` và Pydantic serialize `Decimal` thành chuỗi. Parse sang
 * `number` là mất chính xác trên tổng lớn, và mất im lặng — không có gì đỏ.
 * Vì thế `Tien = string` và MỌI hàm ở đây nhận chuỗi.
 *
 * ⚠️ KHÔNG cộng tiền ở FE. BE trả `chi_phi_tong` riêng — dùng nó. Nếu tổng tự
 * cộng ≠ `chi_phi_tong` thì đó là TÍN HIỆU LỖI, không phải chuyện làm tròn.
 */
export type Tien = string

const VI = 'vi-VN'

/** Làm tròn ĐỂ HIỆN, và chỉ để hiện. BE cố ý không làm tròn ở `rated_usage`. */
export function tien(x: Tien): string {
  const [nguyen, le = ''] = x.split('.')
  const lam_tron = Number(le[0] ?? '0') >= 5 ? 1n : 0n
  const n = BigInt(nguyen || '0') + (nguyen.startsWith('-') ? -lam_tron : lam_tron)
  return n.toLocaleString(VI)
}

export function tienDay(x: Tien): string {
  const [nguyen, le = ''] = x.split('.')
  const phan = BigInt(nguyen || '0').toLocaleString(VI)
  return le ? `${phan},${le.padEnd(4, '0').slice(0, 4)} ₫` : `${phan} ₫`
}

export function token(n: number): string {
  if (n >= 1e6)
    return `${(n / 1e6).toLocaleString(VI, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} M`
  if (n >= 1e4) return `${Math.round(n / 1e3).toLocaleString(VI)} k`
  return n.toLocaleString(VI)
}

export function giay(s: number): string {
  if (s < 60) return `${s.toLocaleString(VI, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} s`
  const t = Math.round(s)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const g = t % 60
  return h ? `${h}h ${m}m ${g}s` : `${m}m ${g}s`
}

export function phanTram(a: number, b: number): string {
  if (!b) return '—'
  return `${((a / b) * 100).toLocaleString(VI, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`
}

/** `provider`/`model` của component audio là `''` (DEFAULT '', không NULL). */
export function rong(v: string | null | undefined): string {
  return v ? v : '—'
}
```

- [ ] **Step 4: Chạy test**

Run: `NODE_OPTIONS="--no-experimental-webstorage" npx vitest run tests/billing-dinh-dang.test.ts`
Expected: PASS 14/14. Nếu bài `9007199254740993` đỏ ⇒ ai đó đã parse qua `Number`; sửa lại dùng `BigInt`.

- [ ] **Step 5: Commit**

```bash
git add src/features/billing/dinh-dang.ts tests/billing-dinh-dang.test.ts
git commit -m "feat(billing): dinh-dang — tiền là string, BigInt không mất chính xác"
```

---

