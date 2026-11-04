/**
 * Đầu mục của một khối trong màn: tiêu đề + (số đếm) + (chỗ bên phải) + (ghi chú).
 *
 * VÌ SAO MỘT MODULE. Ba khối trong cùng hai màn đang viết đầu mục ba kiểu, và
 * hai trong số đó nằm CẠNH NHAU trên `/users` nên nhìn thấy ngay:
 *   · `UserAdmin`     h2 15px · `mb-1.5` · có ghi chú `mb-[18px]`
 *   · `DanhSachVaiTro` h2 15px · `mb-1.5` · có ghi chú `mb-[18px]`
 *   · `MemberList`     h2 15px · `mb-3`   · KHÔNG ghi chú
 * Khoảng cách dưới tiêu đề vì thế lúc 6px lúc 12px, và khối không ghi chú thì
 * dính vào bảng của nó chặt hơn khối có ghi chú.
 *
 * Luật ở đây: nhịp dưới đầu mục LUÔN là 18px, dù có ghi chú hay không. Khối nào
 * không có ghi chú thì chính hàng tiêu đề mang 18px ấy — người dùng không phải
 * đoán vì sao hai bảng xếp chồng lại thở khác nhau.
 *
 * `<h2>` chứ KHÔNG `<h1>`: Topbar đã render `<h1>` lấy từ nhãn nav. Nhưng mỗi
 * bảng vẫn PHẢI có tiêu đề riêng — một bảng có nhãn xếp cạnh một bảng không
 * nhãn thì trình đọc màn hình đọc ra một bảng vô danh rồi một bảng có tên.
 */
import type { ReactNode } from 'react'
import { NEN_PILL } from './Bang'

interface Props {
  readonly tieuDe: string
  /** Số đếm cạnh tiêu đề, ví dụ «2 người dùng». Dạng pill xám. */
  readonly dem?: string | undefined
  /** Câu một dòng nói khối này để làm gì. */
  readonly ghiChu?: string | undefined
  /** Đẩy sang mép phải của hàng tiêu đề — nút chính, hoặc một câu ngữ cảnh. */
  readonly phai?: ReactNode
  /** Badge phụ đứng ngay sau số đếm (ví dụ «3 người chưa nhận lời mời»). */
  readonly children?: ReactNode
}

export function DauMuc({ tieuDe, dem, ghiChu, phai, children }: Props) {
  return (
    <>
      <div className={`flex flex-wrap items-center gap-3.5 ${ghiChu ? 'mb-1.5' : 'mb-[18px]'}`}>
        <h2 className="text-muc font-semibold text-fg">{tieuDe}</h2>
        {dem && (
          <span
            className={`${NEN_PILL} rounded-full px-2.5 py-1 text-phu font-medium text-muted-2`}
          >
            {dem}
          </span>
        )}
        {children}
        {phai && <div className="ml-auto flex flex-none items-center gap-2.5">{phai}</div>}
      </div>
      {ghiChu && <p className="mb-[18px] text-noi text-muted">{ghiChu}</p>}
    </>
  )
}
