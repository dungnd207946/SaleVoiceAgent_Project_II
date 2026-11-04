/**
 * Cổng cấu trúc: KHÔNG chữ nào dưới 11px — sàn của thang cỡ chữ (`--text-nhan`).
 *
 * Trước 2026-10-05 portal có 128 chỗ chữ chức năng dưới 11px (detector của
 * impeccable, 20 màn ở 1280px): nhãn rail 10px trên MỌI màn, slug workspace,
 * nhãn KPI, ngày dưới biểu đồ… Dưới 11px là hỏng đọc trên màn nhỏ/HiDPI, không
 * phải một lựa chọn phong cách. jsdom không nạp CSS nên chỉ quét văn bản mới bắt
 * được, cùng lý do `tests/vien-tran.test.ts`. Quét cả `fontSize` của `<text>` SVG
 * (biểu đồ vẽ theo đơn vị người dùng = px).
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function quet(thuMuc: string): string[] {
  const ra: string[] = []
  for (const ten of readdirSync(thuMuc)) {
    const duongDan = join(thuMuc, ten)
    if (statSync(duongDan).isDirectory()) ra.push(...quet(duongDan))
    else if (/\.tsx?$/.test(ten)) ra.push(duongDan)
  }
  return ra
}

const SAN = 11

describe('sàn cỡ chữ 11px', () => {
  it('không `text-[Npx]` nào dưới 11px, kể cả có tiền tố biến thể', () => {
    const lech = quet('src').flatMap((f) =>
      [...readFileSync(f, 'utf8').matchAll(/text-\[(\d+(?:\.\d+)?)px\]/g)]
        .filter((m) => Number(m[1]) < SAN)
        .map((m) => `${f}: ${m[0]}`),
    )
    expect(lech, 'dùng `text-nhan` (11px) — sàn của thang').toEqual([])
  })

  it('cỡ ĐÃ có token thì viết bằng token, không `text-[Npx]`', () => {
    // 05/10: 362 chỗ trùng bậc đã sang token (đo 0/2875 phần tử đổi hình). 22px chỉ là
    // `text-trang` khi là tiêu đề trang — bốn CON SỐ 22px giữ `text-[22px]` có chủ ý.
    const CO_TOKEN = new Set(['11', '12.5', '13.5', '14.5', '15', '16', '26', '32'])
    const lech = quet('src').flatMap((f) =>
      [...readFileSync(f, 'utf8').matchAll(/text-\[(\d+(?:\.\d+)?)px\]/g)]
        .filter((m) => CO_TOKEN.has(m[1]!))
        .map((m) => `${f}: ${m[0]}`),
    )
    expect(lech, 'dùng `text-nhan`/`phu`/`than`/`noi`/`the`/`muc`/`so`/`so-lon`').toEqual([])
  })

  it('không `fontSize` SVG nào dưới 11', () => {
    const lech = quet('src').flatMap((f) =>
      [...readFileSync(f, 'utf8').matchAll(/fontSize=\{?["']?(\d+(?:\.\d+)?)/g)]
        .filter((m) => Number(m[1]) < SAN)
        .map((m) => `${f}: ${m[0]}`),
    )
    expect(lech).toEqual([])
  })
})
