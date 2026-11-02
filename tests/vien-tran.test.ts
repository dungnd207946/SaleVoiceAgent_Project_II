/**
 * Cổng cấu trúc: KHÔNG có «viền trần» — class `border` mà không kèm token màu.
 *
 * VÌ SAO PHẢI QUÉT VĂN BẢN. Tailwind v4 đổi mặc định màu viền từ xám nhạt
 * (v3, gray-200) sang **`currentColor`** — một `border` không chỉ định màu sẽ
 * vẽ viền bằng MÀU CHỮ đang thừa kế, tức gần đen (`fg` #14161a), đậm gấp nhiều
 * lần viền thẻ chuẩn (`border-border` #edebe5). Đo thật 2026-08-21: tấm nền
 * `/convos` từng render viền rgb(20,22,26) — không ai từng CHỌN màu đó cả.
 * 10 chỗ dính (4 tấm nền M7/quality + bong bóng khách, thẻ tool, khối dữ liệu
 * trong Transcript, dialog ghi chú HopThuSale) đã sửa cùng ngày; cổng này giữ
 * cho lớp lỗi không quay lại. jsdom không nạp CSS của Tailwind nên KHÔNG bài
 * render nào bắt được — cùng lý do tồn tại của `tests/o-chon.test.ts`.
 *
 * CÁCH QUÉT. Mỗi chuỗi/template literal trong `src/**\/*.tsx` chứa utility
 * `border` ĐỨNG MỘT MÌNH (không phải `border-b`, `bg-border`, `border-dashed`…)
 * phải chứa kèm ít nhất một token màu viền (`border-border*`, `border-ac`,
 * `border-badge-*`, `border-panel-*`, `hover:border-fg`…). Template literal
 * được xét NGUYÊN KHỐI — gồm cả các nhánh ternary bên trong `${…}` — vì màu
 * rất hay nằm ở nhánh ternary (`border px-3 ${x ? 'border-ac' : 'border-…'}`).
 * Comment bị BÓC trước khi quét: docstring của repo dùng backtick markdown
 * (`border`) rất nhiều, để nguyên là cổng đọc nhầm chúng thành template
 * literal. Màu nằm ở một BIẾN ghép từ xa (hằng kế bên, bảng tra) thì cổng
 * không thấy — hai ca như thế đang có tên trong `CHO_PHEP` kèm lý do; thêm ca
 * mới thì thêm dòng có lý do, đừng nới regex.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function quetTsx(thuMuc: string): string[] {
  const ra: string[] = []
  for (const ten of readdirSync(thuMuc)) {
    const duongDan = join(thuMuc, ten)
    if (statSync(duongDan).isDirectory()) ra.push(...quetTsx(duongDan))
    else if (ten.endsWith('.tsx')) ra.push(duongDan)
  }
  return ra
}

/** Utility `border` đứng một mình — không phải `border-b`/`bg-border`/`border-dashed`. */
const VIEN_TRAN = /(?<![\w-])border(?![\w-])/

/** Một token MÀU viền — loại trừ các utility bề rộng/kiểu (`border-2`,
 *  `border-t`, `border-dashed`…) vốn không mang màu. */
const CO_MAU_VIEN =
  /border-(?!dashed\b|solid\b|dotted\b|none\b|collapse\b|spacing\b|[0248]\b|[tblrxy]\b|[tblrxy]-)[a-z]/

/** Chuỗi có `border` trần nhưng MÀU được ghép từ một biến ở xa — cổng không
 *  nhìn xuyên phép ghép được. Mỗi dòng phải có lý do; đọc lại chỗ dùng trước
 *  khi thêm dòng mới. */
const CHO_PHEP: readonly { file: string; chua: string; viSao: string }[] = [
  {
    file: 'src/components/ui/Bang.tsx',
    chua: 'inline-flex size-7 max-md:size-10 flex-none items-center justify-center rounded-sm border',
    viSao: 'NUT_ICON là phần THÂN; màu viền nằm ở NUT_ICON_THUONG/NUT_ICON_XOA ghép ngay dòng dưới',
  },
  {
    file: 'src/components/ui/ChipKenh.tsx',
    chua: 'rounded-full border px-2',
    viSao: 'màu viền nằm trong bảng KENH (`k.lop`) cùng file — mỗi kênh một bộ token riêng',
  },
  {
    file: 'src/features/billing/components/UsageScreen.tsx',
    chua: 'rounded-md border px-3.5',
    viSao:
      'NUT_KY_CHUNG là phần THÂN, cùng hình với NUT_ICON của Bang.tsx: hai người dùng duy nhất ghép token màu ngay hai dòng dưới (NUT_KY_CHON → border-ac · NUT_KY_THUONG → border-border-field) và hằng thân KHÔNG bao giờ render trần',
  },
]

describe('viền trần — `border` không token màu (bẫy currentColor của Tailwind v4)', () => {
  it('mọi chuỗi class chứa `border` đứng một mình phải kèm một token màu viền', () => {
    const loi: string[] = []
    for (const f of quetTsx('src')) {
      // BÓC COMMENT trước — docstring dùng backtick markdown (`border`) sẽ bị
      // đọc nhầm thành template literal nếu để nguyên. Block comment trước,
      // rồi dòng //; comment đuôi dòng (`code // chú`) không bóc để khỏi cắn
      // nhầm `https://` trong chuỗi — backtick trong comment đuôi chưa từng có.
      const goc = readFileSync(f, 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '')
      // Template literal xét nguyên khối (gồm ruột `${…}`), rồi CẮT khỏi nguồn
      // để chuỗi con bên trong nó không bị xét lần hai một cách rời rạc.
      const khoi: string[] = []
      const conLai = goc.replace(/`[^`]*`/g, (m) => {
        khoi.push(m)
        return ''
      })
      khoi.push(...(conLai.match(/"[^"\n]*"|'[^'\n]*'/g) ?? []))
      for (const s of khoi) {
        if (!VIEN_TRAN.test(s) || CO_MAU_VIEN.test(s)) continue
        if (CHO_PHEP.some((c) => f.endsWith(c.file) && s.includes(c.chua))) continue
        loi.push(`${f}: ${s.length > 90 ? `${s.slice(0, 90)}…` : s}`)
      }
    }
    expect(loi).toEqual([])
  })
})
