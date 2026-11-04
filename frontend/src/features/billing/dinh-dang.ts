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
import { gioPhut, ngayThangNam } from '@/lib/dinhDang'

export type Tien = string

const VI = 'vi-VN'

/**
 * Đưa một `Tien` về dạng thập phân THƯỜNG — bước đầu của MỌI bộ parse dưới đây.
 *
 * ⚠️ Pydantic serialize `Decimal` bằng `str()`, và `str()` chuyển sang KÝ HIỆU
 * MŨ khi số mũ điều chỉnh < -6: `str(Decimal('0.0000000000'))` ra `'0E-10'`,
 * KHÔNG phải `'0'`. Cột tiền của BE là `numeric(20,10)`, nên mọi tổng bằng 0 mà
 * có ít nhất một dòng `rated_usage` đều tới đây ở dạng đó. Đường đi không cần
 * bug nào: bảng giá MẶC ĐỊNH (`0949_seed_bang_gia_mac_dinh`) khai
 * `unit_price = 0` cho `vad`/`speaker_verify`/`stt`, còn `billing.rate_usage()`
 * chỉ lọc `qty > 0` chứ không lọc `amount > 0` — mọi phiên voice đều sinh dòng
 * tiền 0. Và `BigInt('0E-10')` NÉM, tức cả màn `/usage` trắng, không phải hiện
 * sai một con số.
 *
 * Chuỗi không mang `E` trả về nguyên vẹn (chỉ `trim`), nên đặt hàm này ở đầu
 * các bộ parse không đổi gì hành vi của dạng thường.
 */
function veThapPhan(x: Tien): string {
  const s = x.trim()
  const m = /^([+-]?)(\d+)(?:\.(\d+))?[eE]([+-]?\d+)$/.exec(s)
  if (!m) return s
  const dau = m[1] === '-' ? '-' : ''
  const [, , nguyen = '0', le = '', mu = '0'] = m
  const so = nguyen + le
  // Vị trí dấu chấm trong `so` sau khi dời theo số mũ.
  const diem = nguyen.length + Number(mu)
  if (diem <= 0) return `${dau}0.${'0'.repeat(-diem)}${so}`
  if (diem >= so.length) return `${dau}${so}${'0'.repeat(diem - so.length)}`
  return `${dau}${so.slice(0, diem)}.${so.slice(diem)}`
}

/** Số chữ số thập phân SAU khi đã bỏ ký hiệu mũ — mẫu chung của ba hàm BigInt
 *  dưới đây. Đếm trên chuỗi thô là đếm nhầm: `'1E-10'` không có dấu chấm nào
 *  nên ra 0, và `veBigInt()` (chỉ `padEnd`, không cắt) sẽ đọc nó thành 1 đồng. */
function soLeCua(x: string): number {
  return (x.split('.')[1] ?? '').length
}

/** Làm tròn ĐỂ HIỆN, và chỉ để hiện. BE cố ý không làm tròn ở `rated_usage`. */
export function tien(x: Tien): string {
  const [nguyen = '', le = ''] = veThapPhan(x).split('.')
  const lam_tron = Number(le[0] ?? '0') >= 5 ? 1n : 0n
  const n = BigInt(nguyen || '0') + (nguyen.startsWith('-') ? -lam_tron : lam_tron)
  return n.toLocaleString(VI)
}

/**
 * Tiền RÚT GỌN cho ô tóm tắt hẹp (ô Chi phí `/dashboard`) — trả HAI mảnh: con số
 * (`so`) và bậc (`hau`: `''` · `'triệu'` · `'tỷ'`). Tách ra để chỗ gọi in con
 * số cỡ lớn và bậc cỡ nhỏ cạnh đơn vị tiền («98.768» + «triệu VND») — ghép
 * chung một chuỗi cỡ 30px thì chính chữ «triệu» làm tràn tile.
 *
 * Dưới 1 triệu giữ nguyên `tien()` (`125.011`, dấu chấm NHÓM hàng nghìn). Từ
 * 1 triệu: ĐÚNG 3 chữ số lẻ, dấu CHẤM thập phân (`98.768` triệu, `12.345` tỷ)
 * — người dùng chốt 2026-09-29, cùng lối ngoại lệ dấu chấm của `token()`.
 * ⚠️ Nên `125.011` (nguyên) và `98.768` (thập phân) cùng hình mà khác nghĩa —
 * thứ phân biệt là chữ bậc «triệu/tỷ» đứng cạnh, đừng bỏ nó khi dùng `so`.
 * CẮT chứ không làm tròn: 999.999.900 làm tròn 3 chữ số ra «1000.000 triệu» —
 * một con số đẹp hơn sự thật, và lệch bậc với «tỷ».
 *
 * Rút gọn LÀ làm mất chính xác — chỉ dùng ở chỗ có đường tới số đầy đủ
 * (`title` + màn `/billing`), KHÔNG dùng trong bảng hay đối soát.
 */
export function tienGon(x: Tien): { readonly so: string; readonly hau: '' | 'triệu' | 'tỷ' } {
  const [nguyen = ''] = veThapPhan(x).split('.')
  const n = Number(nguyen || '0')
  if (Math.abs(n) < 1e6) return { so: tien(x), hau: '' }
  const [chia, hau] = Math.abs(n) >= 1e9 ? ([1e9, 'tỷ'] as const) : ([1e6, 'triệu'] as const)
  return { so: (Math.trunc((n / chia) * 1000) / 1000).toFixed(3), hau }
}

export function tienDay(x: Tien): string {
  const [nguyen, le = ''] = veThapPhan(x).split('.')
  const phan = BigInt(nguyen || '0').toLocaleString(VI)
  return le ? `${phan},${le.padEnd(4, '0').slice(0, 4)} ₫` : `${phan} ₫`
}

/** Số nguyên đếm (phiên, khoá, tổ hợp giá, …) — nhóm hàng nghìn kiểu vi-VN.
 *  KHÔNG dùng cho tiền (đó là `tien()`/`tienDay()`, nhận `Tien` = chuỗi) hay
 *  token (đó là `token()`, có hậu tố k/M). Trước review 2026-08-20, hai
 *  component (`BangLuotDung.tsx`, `TheKpi.tsx`) tự khai lại đúng một dòng
 *  này, và `BangGiaScreen.tsx` còn viết `toLocaleString('vi-VN')` trần thêm
 *  hai lần nữa — bốn chỗ cho một phép format số nguyên. */
export function SO(n: number): string {
  return n.toLocaleString(VI)
}

/**
 * Rút gọn số đếm lớn. HẬU TỐ VIẾT LIỀN SỐ (`976k`, `1.20M`) — không phải
 * `976 k`. Đây là bội số của chính con số, không phải một ĐƠN VỊ đứng sau nó:
 * tách ra bằng khoảng trắng thì mắt đọc thành hai token và `in 976 k` trông
 * như «in 976» rồi một chữ `k` lạc. Cùng lý lẽ `giay()` đã viết `1m 4s` liền
 * từ đầu — hàm này chỉ đang lệch với chính nó.
 *
 * KHÁC với đơn vị THẬT: `12.500 ₫`, `48,2 s`… vẫn tách (xem `tienDay`), và
 * `1,7 MB` ở `/kb` cũng vậy — đó là quy ước của đơn vị dung lượng.
 */
export function token(n: number): string {
  // `toFixed` chứ KHÔNG `toLocaleString(VI)`: dạng rút gọn dùng dấu CHẤM làm
  // thập phân (`1.20M`, không phải `1,20M`) — người dùng chốt 2026-08-21.
  // Đây là ngoại lệ CÓ Ý THỨC với locale vi-VN (dấu phẩy mới là thập phân ở
  // đó): hậu tố `M` đứng ngay sau nên không đọc nhầm sang hàng nghìn được, và
  // hai chữ số lẻ luôn hiện. ⚠️ `toFixed` cũng bỏ luôn dấu nhóm hàng nghìn —
  // chỉ lộ ra từ 1 tỷ token (`1204.50M`); đổi thì đổi cả hai chiều một lượt,
  // đừng nhét dấu chấm nhóm vào cạnh một dấu chấm thập phân.
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (n >= 1e4) return `${Math.round(n / 1e3).toLocaleString(VI)}k`
  return n.toLocaleString(VI)
}

export function giay(s: number): string {
  if (s < 60)
    return `${s.toLocaleString(VI, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}s`
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

/**
 * `dd/MM/yyyy HH:mm` giờ máy người dùng — cột «Tạo lúc» của `/pricing` (Task 8).
 */
export function dinhDangLuc(iso: string): string {
  const d = new Date(iso)
  return `${ngayThangNam(d)} ${gioPhut(d)}`
}

/**
 * Quy `Tien` về BigInt theo ĐÚNG `soLe` chữ số thập phân (đệm `0` bên phải nếu
 * ngắn hơn) — bước chung cho `congTien`/`soSanhTien`, để hai chuỗi số thập
 * phân khác độ dài (`"5"` và `"5.00"`) so/cộng được mà không qua `Number`.
 */
function veBigInt(x: Tien, soLe: number): bigint {
  const s = veThapPhan(x)
  const am = s.startsWith('-')
  const than = am ? s.slice(1) : s
  const [nguyen = '0', le = ''] = than.split('.')
  const v = BigInt((nguyen || '0') + le.padEnd(soLe, '0'))
  return am ? -v : v
}

function tuBigInt(v: bigint, soLe: number): Tien {
  const am = v < 0n
  const s = (am ? -v : v).toString().padStart(soLe + 1, '0')
  const nguyen = s.slice(0, s.length - soLe) || '0'
  const le = soLe > 0 ? s.slice(s.length - soLe) : ''
  return `${am ? '-' : ''}${nguyen}${le ? `.${le}` : ''}`
}

/**
 * Cộng nhiều `Tien` CHÍNH XÁC bằng `BigInt` — KHÔNG qua `Number` (Task 2 đã có
 * bài test chứng minh `Number` mất chính xác trên số lớn, và mất im lặng).
 * Dùng để tự đối chiếu `Σ items[].chi_phi` với `chi_phi_tong` của API — bản
 * thân phép cộng này KHÔNG PHẢI để hiện lên màn thay `chi_phi_tong`, chỉ để so.
 */
export function congTien(xs: readonly Tien[]): Tien {
  if (xs.length === 0) return '0'
  const ds = xs.map(veThapPhan)
  const soLe = Math.max(...ds.map(soLeCua))
  const tong = ds.reduce((acc, x) => acc + veBigInt(x, soLe), 0n)
  return tuBigInt(tong, soLe)
}

/**
 * So hai `Tien` CHÍNH XÁC (không qua `Number`) — âm/0/dương như `Array.sort`
 * mong đợi. Dùng để sắp cột Chi phí VÀ để phát hiện lệch `chi_phi_tong`
 * (`soSanhTien(tongTuCong, chiPhiTong) !== 0` ⇒ tín hiệu lỗi, không phải làm tròn).
 */
export function soSanhTien(a: Tien, b: Tien): number {
  const an = veThapPhan(a)
  const bn = veThapPhan(b)
  const soLe = Math.max(soLeCua(an), soLeCua(bn))
  const av = veBigInt(an, soLe)
  const bv = veBigInt(bn, soLe)
  return av < bv ? -1 : av > bv ? 1 : 0
}

/**
 * Chia `Tien` cho một số nguyên dương — CHÍNH XÁC, qua `BigInt`, giữ 4 chữ số
 * thập phân. Dùng cho các số PHÁI SINH ĐỂ HIỆN (trung bình mỗi ngày, mỗi
 * phiên), KHÔNG phải để tính tiền.
 *
 * ⚠️ Đừng thay bằng `Number(x) / n`: cùng lý do `congTien()` tồn tại — tổng
 * tiền của một tenant lớn vượt khoảng an toàn của `Number` và mất chính xác
 * IM LẶNG. Ở đây con số chỉ để đọc, nhưng một hàm chia "tạm" bằng `Number`
 * nằm cạnh ba hàm BigInt là lời mời dùng nó vào chỗ không tạm.
 */
export function chiaTien(x: Tien, n: number): Tien {
  if (n <= 0) return '0'
  // ⚠️ `soLe` PHẢI ≥ số chữ số thập phân của chính `x`. `veBigInt()` chỉ ĐỆM
  // (`padEnd`), nó KHÔNG cắt bớt — đưa `soLe` nhỏ hơn thì chuỗi số bị đọc
  // thành một giá trị lớn hơn nó 10^k lần, và lớn hơn IM LẶNG. Hai hàm kia
  // (`congTien`/`soSanhTien`) không dính vì chúng lấy `soLe` = độ dài LỚN NHẤT
  // trong các toán hạng; hàm này chỉ có một toán hạng nên phải tự lấy.
  // (Đo được: `chiaTien('125000.5000000000', 4)` từng ra `31250125000` — gấp
  // một triệu lần — và một bài test của mục ② đã bắt đúng nó.)
  const xn = veThapPhan(x)
  const soLe = Math.max(soLeCua(xn), 4)
  return tuBigInt(veBigInt(xn, soLe) / BigInt(Math.trunc(n)), soLe)
}
