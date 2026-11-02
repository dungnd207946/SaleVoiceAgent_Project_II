/**
 * Hai trạng thái của mọi danh sách trong portal: RỖNG và KHÔNG TẢI ĐƯỢC.
 *
 * ⚠️ Trước ở `features/realestate/components/TrangCuon.tsx`. Chuyển ra đây vì
 * bảng người dùng (M2b) cần đúng hai khối này, và Luật 3 cấm `features/auth`
 * import ruột `features/realestate`. `TrangCuon.tsx` giữ lại `NutTaiThem` (nó
 * thuộc về phân trang cursor, không phải hình dạng chung) và re-export hai cái
 * này để năm chỗ dùng của realestate không phải sửa.
 *
 * `KhoRong` và `LoiTai` PHẢI khác nhau, không gộp thành một: xem docstring
 * `LoiTai`.
 */
import type { ReactNode } from 'react'

/**
 * Trạng thái rỗng — HƯỚNG DẪN, không phải lỗi (không `role="alert"`, không đỏ).
 *
 * `viec` là một nút/link để làm ngay việc mà `huongDan` vừa nói. Không truyền thì
 * khối chỉ có chữ (đúng như bản cũ ở realestate).
 */
export function KhoRong({
  tieuDe,
  huongDan,
  viec,
}: {
  tieuDe: string
  huongDan: string
  viec?: ReactNode
}) {
  return (
    // `rounded-lg` — trước là `rounded` (4px) trong khi `LoiTai` ngay dưới dùng
    // `rounded-lg`: hai khối cùng một họ, đặt cạnh nhau trong cùng một danh
    // sách, mà bo góc lệch nhau. Giờ cả hai là `lg`, đúng bậc "thẻ" của thang.
    <div className="rounded-lg border border-border bg-surface p-6 text-center text-noi text-muted">
      <p className="font-medium text-fg">{tieuDe}</p>
      <p className="mt-1">{huongDan}</p>
      {viec && <div className="mt-4 flex justify-center">{viec}</div>}
    </div>
  )
}

/**
 * Không tải được — PHẢI khác `KhoRong`.
 *
 * Backend chết mà UI hiện "chưa có dự án nào" thì người dùng đi nhập lại thứ họ
 * đã nhập, và không ai báo sự cố. Cùng lý lẽ với `TaiLieuList.tsx` của M6.
 */
export function LoiTai({ viec, thuLai }: { viec: string; thuLai: () => void }) {
  return (
    <div
      className="rounded-lg border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-noi"
      role="alert"
    >
      <p>Không tải được {viec}.</p>
      <button
        type="button"
        onClick={thuLai}
        className="mt-2 rounded-md border border-border-field px-3 py-1.5 text-noi"
      >
        Thử lại
      </button>
    </div>
  )
}
