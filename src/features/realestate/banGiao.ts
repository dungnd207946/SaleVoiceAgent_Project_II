/** Hạng mục bàn giao — hàm thuần, tách khỏi component để Vite nạp nóng đúng (react-refresh). */
import type { HangMucBanGiao } from './api'

export const HANG_MUC_TRONG: HangMucBanGiao = {
  item: '',
  material: '',
  brand: '',
  origin: '',
  note: '',
}

/** Bỏ dòng chưa có tên và khoảng trắng thừa trước khi gửi — backend từ chối hạng mục không tên. */
export function hangMucDeGui(ds: readonly HangMucBanGiao[]): HangMucBanGiao[] {
  return ds
    .map((h) => ({
      item: h.item.trim(),
      material: h.material.trim(),
      brand: h.brand.trim(),
      origin: h.origin.trim(),
      note: h.note.trim(),
    }))
    .filter((h) => h.item)
}
