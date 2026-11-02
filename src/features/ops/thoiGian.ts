/**
 * Định dạng thời gian cho màn Hội thoại. Hàm THUẦN — không React, không `new Date()`
 * ngầm: mọi hàm nhận `bayGio` để test được tất định. Một hàm gọi `Date.now()` bên
 * trong sẽ đỏ vào đúng ngày thứ 8 sau khi ai đó viết test, và người sửa nghĩ mình
 * vừa làm hỏng bộ lọc.
 */
import { gioPhut, ngayThangNam } from '@/lib/dinhDang'

export type MocNgay = 'hom-nay' | 'hom-qua' | 'tuan-truoc' | 'cu-hon'

function dauNgay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

function soNgayCach(iso: string, bayGio: Date): number {
  const MOT_NGAY = 86_400_000
  return Math.round((dauNgay(bayGio) - dauNgay(new Date(iso))) / MOT_NGAY)
}

export function gioNgan(iso: string, bayGio: Date = new Date()): string {
  const n = soNgayCach(iso, bayGio)
  if (n <= 0) return gioPhut(new Date(iso))
  if (n === 1) return 'hôm qua'
  if (n < 7) return `${n} ngày trước`
  return ngayThangNam(new Date(iso))
}

/** `dd/mm/yyyy · hh:mm` — giờ của trình duyệt. Chuỗi không parse được ⇒ `—`, không «Invalid Date». */
export function ngayGio(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  // FINDING 5 (review cuối nhánh M7): guard `Number.isNaN` — `gioCua` của
  // `Transcript.tsx` đã có guard này, `ngayGio` thì thiếu. Một `batDau` không
  // parse được (chuỗi méo từ hệ khác ghi `conversations`, cùng lý do
  // `Transcript.tsx` phòng thủ ở `role`/`meta`) sẽ in `Invalid Date` lên màn
  // thay vì `—`.
  if (Number.isNaN(d.getTime())) return '—'
  return `${ngayThangNam(d)} · ${gioPhut(d)}`
}

export function thoiLuong(batDau: string | null, ketThuc: string | null): string | null {
  // Thiếu một trong hai đầu ⇒ KHÔNG có thời lượng. Trả '0:00' ở đây là in ra một
  // con số sai chứ không phải một ô trống trung thực.
  if (!batDau || !ketThuc) return null
  const giay = Math.max(
    0,
    Math.round((new Date(ketThuc).getTime() - new Date(batDau).getTime()) / 1000),
  )
  return `${Math.floor(giay / 60)}:${String(giay % 60).padStart(2, '0')}`
}

/**
 * Một ca đã chờ bao lâu, không kèm «trước»: `5 phút` · `3 giờ` · `2 ngày`. Dưới 48 giờ
 * vẫn đếm giờ — «1 ngày» nói ít hơn «30 giờ» với người phải gọi lại khách. Chuỗi không
 * parse được ⇒ `null` (chỗ gọi bỏ hẳn dòng, không in «NaN giờ»).
 */
export function daCho(iso: string, bayGio: Date = new Date()): string | null {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  const phut = Math.max(1, Math.floor((bayGio.getTime() - t) / 60_000))
  if (phut < 60) return `${phut} phút`
  const gio = Math.floor(phut / 60)
  return gio < 48 ? `${gio} giờ` : `${Math.floor(gio / 24)} ngày`
}

export function mocNgay(iso: string, bayGio: Date = new Date()): MocNgay {
  const n = soNgayCach(iso, bayGio)
  if (n <= 0) return 'hom-nay'
  if (n === 1) return 'hom-qua'
  if (n < 14) return 'tuan-truoc'
  return 'cu-hon'
}

/**
 * Nhãn khoảng kỳ của màn Tổng quan: `('2026-08-07', '2026-08-13')` →
 * `07/08 – 13/08/2026`. Hai đầu khác năm thì in cả hai năm.
 *
 * TRẢ `null` khi thiếu một đầu, và `moc.tuNgay`/`moc.tinhDen` rỗng CHÍNH LÀ
 * ca đó (`api.ts` cố ý cho khoá vắng rơi về chuỗi rỗng thay vì bịa một ngày).
 * Chỗ gọi phải ẩn hẳn nhãn — vẽ ra một khoảng trống có dấu gạch nối («– » lơ
 * lửng) là nói rằng có một kỳ ở đó mà người đọc không đọc được, tệ hơn là
 * không nói gì.
 *
 * Cắt chuỗi bằng TAY, không qua `new Date()`: `new Date('2026-08-07')` parse
 * theo UTC nên ở múi giờ âm nó lùi một ngày — cùng cái bẫy đã ghi ở
 * `BieuDoNgay.ngayLe()`. Ở đây chuỗi vào đã là ngày lịch rồi, không có gì để
 * quy đổi.
 */
export function khoangKy(tuNgay: string, tinhDen: string): string | null {
  const a = tachIso(tuNgay)
  const b = tachIso(tinhDen)
  if (!a || !b) return null
  return a.nam === b.nam ? `${a.ngayThang} – ${b.ngayThang}/${b.nam}` : `${a.day} – ${b.day}`
}

function tachIso(iso: string): { ngayThang: string; nam: string; day: string } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return null
  const [, nam, thang, ngay] = m as unknown as [string, string, string, string]
  const ngayThang = `${ngay}/${thang}`
  return { ngayThang, nam, day: `${ngayThang}/${nam}` }
}

export const NHAN_MOC: Record<MocNgay, string> = {
  'hom-nay': 'Hôm nay',
  'hom-qua': 'Hôm qua',
  'tuan-truoc': 'Tuần trước',
  'cu-hon': 'Cũ hơn',
}
