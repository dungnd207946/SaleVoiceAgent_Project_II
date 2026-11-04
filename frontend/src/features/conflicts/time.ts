import { gioPhut, ngayThang } from '@/lib/dinhDang'

function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString()
}

/** «14:32 hôm nay» · «09:10 hôm qua» · «08/10 16:05». */
export function checkedTime(iso: string, now = new Date()): string {
  const d = new Date(iso)
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (sameDay(d, now)) return `${gioPhut(d)} hôm nay`
  if (sameDay(d, yesterday)) return `${gioPhut(d)} hôm qua`
  return `${ngayThang(d)} ${gioPhut(d)}`
}
