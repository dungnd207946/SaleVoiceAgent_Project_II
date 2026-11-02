/**
 * Hình học TRỤC của biểu đồ `/usage` + bảng biến CSS của một tab.
 *
 * Tách khỏi `components/BieuDoLuongDung.tsx` và `components/RailUsage.tsx` vì
 * `eslint react-refresh/only-export-components` (repo chạy `--max-warnings 0`),
 * và luật đó đúng: một tệp vừa xuất component vừa xuất hằng thì HMR phải bỏ
 * trạng thái cả cây mỗi lần sửa một con số. Hàm THUẦN — test gọi trực tiếp,
 * không cần render.
 */
import type { CSSProperties } from 'react'

/**
 * Ba biến CSS của một tab, khai ở ĐÚNG một chỗ: chấm định danh, chip đơn vị,
 * con số rail, nét gradient và vùng tô đều đọc từ đây. Không mã màu nào rải
 * trong markup — đổi diện mạo là sửa `theme.css`.
 */
export function bienMau(ma: string): CSSProperties {
  return {
    ['--c' as string]: `var(--color-u-${ma})`,
    ['--a' as string]: `var(--color-ua-${ma})`,
    ['--b' as string]: `var(--color-ub-${ma})`,
  }
}

/**
 * Hai biến CSS của ĐƯỜNG THỨ HAI — `--d` (đặc) và `--d2` (vừa), cùng vai với
 * `--c`/`--a` của đường chính.
 *
 * Tách khỏi `bienMau()` chứ không nhét thêm hai khoá vào đó: chỉ tab có `duong2`
 * mới khai `--color-u-<ma>2`, nên phát cho cả bảy tab là sáu mục trỏ vào biến
 * KHÔNG TỒN TẠI. Không cái nào được đọc hôm nay, nhưng đó đúng là hình dạng của
 * bug «mọi đường thành đen» (2026-08-25): `var()` trỏ vào hư không thì thuộc
 * tính hỏng lặng lẽ và SVG rơi về mặc định.
 */
export function bienMauPhu(ma: string): CSSProperties {
  return {
    ['--d' as string]: `var(--color-u-${ma}2)`,
    ['--d2' as string]: `var(--color-ua-${ma}2)`,
  }
}

/**
 * Mốc trục dọc «TRÒN SỐ» theo ĐƠN VỊ — không chia đều giá trị đỉnh.
 * `giay` có bậc riêng (15s · 1m · 5m · 30m · 1h…): chia đều một trục thời gian
 * ra `1m 47s`/`3m 34s` thì không mốc nào đọc được thành một quãng người ta nghĩ
 * bằng. Trục LUÔN gồm 0 và luôn PHỦ đỉnh — đường chạm mép trên là đường bị cắt.
 *
 * `soChia` do CHIỀU CAO đo được quyết: khung cao theo rail bảy mục (~600px), và
 * 4 mốc cố định trên chừng đó để lại ba dải trống 150px.
 */
export function mocTruc(dinh: number, donVi: string, soChia = 4): number[] {
  const BAC_GIAY = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 43200]
  let buoc: number
  if (donVi === 'giay') {
    buoc = BAC_GIAY.find((b) => dinh / b <= soChia) ?? BAC_GIAY[BAC_GIAY.length - 1]!
  } else {
    const bac = Math.pow(10, Math.floor(Math.log10(dinh / soChia || 1)))
    buoc = [1, 2, 2.5, 5, 10].map((k) => k * bac).find((b) => dinh / b <= soChia) ?? bac * 10
  }
  const ra: number[] = []
  for (let v = 0; v <= dinh + buoc * 0.001; v += buoc) ra.push(v)
  if (ra[ra.length - 1]! < dinh) ra.push(ra.length * buoc)
  return ra
}

/**
 * Mật độ nhãn ngày TỰ CHỌN theo bề rộng đo được (~1 nhãn / 74px), luôn giữ ngày
 * ĐẦU và ngày CUỐI. `/billing` chốt cứng mốc 1·5·10·15·20 và ĐÃ PHẢI SỬA: kỳ
 * «7 ngày» chỉ còn hai nhãn, kỳ «30 ngày» bắc qua hai tháng thì mốc lặp lại.
 * Cùng bài học đó, làm thành phép tính.
 */
export function mocNgay(rong: number, n: number): number[] {
  if (n <= 1) return [0]
  const buoc = Math.max(1, Math.ceil((n - 1) / Math.max(2, Math.floor(rong / 74))))
  const ra: number[] = []
  for (let i = 0; i < n - 1; i += buoc) ra.push(i)
  if (n - 1 - ra[ra.length - 1]! < buoc * 0.55) ra.pop()
  ra.push(n - 1)
  return ra
}

/** `2026-08-19` → `19/08`. Hai đầu trục mang cả tháng vì kỳ «30 ngày» bắc qua
 *  hai tháng — nhãn `19` trần ở đó không nói được là tháng nào. */
export function ngayVN(iso: string): string {
  return `${iso.slice(8)}/${iso.slice(5, 7)}`
}

/**
 * ĐỒNG BỘ SỐ MỐC của hai trục để chúng dùng CHUNG các đường kẻ ngang.
 *
 * `mocTruc` chọn bước theo đỉnh của từng chuỗi, nên hai trục ra hai số mốc khác
 * nhau (vd 4 và 6). Vẽ nguyên như thế là lưới ĐÔI: bốn nét đứt của trục trái đan
 * xen sáu nét của trục phải, và không nét nào còn là một mốc đọc được — mắt
 * không biết nét mình đang dóng theo thuộc thang nào.
 *
 * Nối dài mảng NGẮN HƠN bằng chính bước của nó (`0, b, 2b, …` giữ nguyên tính
 * tròn số) chứ KHÔNG co mảng dài lại: co lại là hạ trần xuống dưới đỉnh, tức cắt
 * ngọn một trong hai đường.
 */
export function dongBoMoc(a: readonly number[], b: readonly number[]): [number[], number[]] {
  const noiDai = (m: readonly number[], den: number): number[] => {
    const ra = [...m]
    // Một mốc duy nhất (chuỗi phẳng bằng 0) thì không suy được bước — lấy chính
    // trần làm bước, cùng quy ước với `mocTruc`.
    const buoc = ra.length > 1 ? ra[1]! - ra[0]! : ra[0]! || 1
    while (ra.length < den) ra.push(ra[ra.length - 1]! + buoc)
    return ra
  }
  const n = Math.max(a.length, b.length)
  return [noiDai(a, n), noiDai(b, n)]
}
