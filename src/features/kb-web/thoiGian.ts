/**
 * Mốc thời gian theo giờ máy người dùng: «hôm nay 01:10» · «hôm qua 16:20» · «03/10 01:10» ·
 * khác năm thì «03/10/2025 01:10». `bayGio` nhận vào để test không phụ thuộc đồng hồ.
 */
import { gioPhut, ngayThang, ngayThangNam } from '@/lib/dinhDang'

function cungNgay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

export function gio(iso: string): string {
  return gioPhut(new Date(iso))
}

export function luc(iso: string | null, bayGio: Date = new Date()): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const homQua = new Date(bayGio)
  homQua.setDate(homQua.getDate() - 1)
  if (cungNgay(d, bayGio)) return `hôm nay ${gio(iso)}`
  if (cungNgay(d, homQua)) return `hôm qua ${gio(iso)}`
  return `${d.getFullYear() === bayGio.getFullYear() ? ngayThang(d) : ngayThangNam(d)} ${gio(iso)}`
}

/** «mai 01:10» · «T3 07/10 04:00» cho mốc tương lai. */
export function sapToi(iso: string | null, bayGio: Date = new Date()): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const mai = new Date(bayGio)
  mai.setDate(mai.getDate() + 1)
  if (cungNgay(d, bayGio)) return `hôm nay ${gio(iso)}`
  if (cungNgay(d, mai)) return `mai ${gio(iso)}`
  const thu = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7'][d.getDay()]
  return `${thu} ${d.getFullYear() === bayGio.getFullYear() ? ngayThang(d) : ngayThangNam(d)} ${gio(iso)}`
}

/** Số ngày từ mốc tới giờ, làm tròn xuống. */
export function soNgayCach(iso: string, bayGio: Date = new Date()): number {
  return Math.max(0, Math.floor((bayGio.getTime() - new Date(iso).getTime()) / 86_400_000))
}

export function so(n: number): string {
  return n.toLocaleString('vi-VN')
}
