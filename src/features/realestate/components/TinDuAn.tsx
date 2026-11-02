/**
 * Dòng «dự án này đã lưu trữ» — hiện ở cuối MỌI tab, dưới hàng nút dán đáy.
 *
 * ⚠️ CHỈ CÒN CA LƯU TRỮ. Hai câu về việc agent đọc / thôi đọc dữ liệu («Agent đã
 * đọc dữ liệu này…», «Agent sẽ thôi đọc dự án này — còn thiếu…») đã BỎ (người
 * dùng chốt 2026-08-21): chúng nói lại thứ chip trạng thái và dấu `*` ở từng ô
 * đã nói, và một câu xanh khẳng định ở cuối mọi tab thành nền, không thành tin.
 *
 * Ca lưu trữ ở lại vì nó không nói lại gì: chip nói «Lưu trữ», nhưng không chỗ
 * nào nói rằng đổi trạng thái là việc phải làm ở chip.
 */
import { DongTrangThai } from '@/components/ui/Truong'
import type { DuAn } from '../api'

export function TinDuAn({ duAn }: { duAn: DuAn }) {
  if (duAn.status !== 'archived') return null

  return (
    <div data-testid="pform-tin" className="pt-4">
      <DongTrangThai mau="warn">
        Dự án này đã lưu trữ nên agent không đọc. Đổi trạng thái ở chip cạnh hàng tab.
      </DongTrangThai>
    </div>
  )
}
