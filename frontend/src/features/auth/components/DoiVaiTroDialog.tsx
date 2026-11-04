/**
 * Hộp thoại đổi vai trò của MỘT thành viên tại workspace đang mở.
 *
 * Số đo và class lấy từ `features/platform/components/TaoKhoaDialog.tsx` — các
 * hộp thoại của portal phải trông như nhau, và đó là lý do file kia được CHÉP
 * chứ không được "tham khảo".
 *
 * RADIO chứ không `<select>`: bốn vai trò là bốn NGHỀ song song (PQ_01 §2.2),
 * không phải bốn bậc — một danh sách phơi cả bốn ra cùng lúc nói đúng điều đó,
 * còn `<select>` giấu ba cái sau một cái và gợi ý thứ bậc.
 */
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { LoiApi } from '@/lib/http'
import { khoaVaiTro, layDanhSachVaiTro } from '../api'
import { doiVaiTroThanhVien, KHOA_TV, type MemberOut } from '../thanhVien'

/**
 * `m.roleId` PHẢI khác `null` ở đây — chỗ gọi (`HangThanhVien`) đã lọc, vì chủ
 * tổ chức không có vai trò workspace nào để đổi. Nhận `MemberOut` nguyên vẹn cho
 * gọn, và ép kiểu một lần ở `useState` thay vì rải `?? ''` khắp component: một
 * chuỗi rỗng lọt vào `PATCH` là 422 `ROLE_NOT_FOUND` với thông điệp khó hiểu.
 *
 * `m.userId` cũng PHẢI khác `null` ở đây (2026-08-22) — chỗ gọi chỉ đưa mục «Đổi
 * vai trò…» vào menu ở nhánh `!laLoiMoi` của `muc`, và mọi hàng `kind='member'`
 * đều có `userId`. Chỉ hàng `kind='invite'` (lời mời cho một email chưa có tài
 * khoản) mới mang `userId: null`, và hàng đó không có mục mở hộp thoại này.
 */
export function DoiVaiTroDialog({ m, onDong }: { m: MemberOut; onDong: () => void }) {
  const queryClient = useQueryClient()
  const [chon, setChon] = useState(m.roleId ?? '')
  const { data: vaiTro } = useQuery({ queryKey: khoaVaiTro.tatCa, queryFn: layDanhSachVaiTro })

  const luu = useMutation({
    mutationFn: () => doiVaiTroThanhVien(m.userId!, chon),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KHOA_TV })
      onDong()
    },
  })

  // `createPortal` vào `document.body` — component này mở từ TRONG một `<tr>`
  // (`HangThanhVien`), và `<dialog>` không phải con hợp lệ của `<tbody>`. `<dialog>`
  // vào top layer nên portal không đổi gì về hình ảnh; nó chỉ dời NODE tới một chỗ
  // hợp lệ trong DOM.
  return createPortal(
    <HopThoai
      onDong={onDong}
      aria-label={`Đổi vai trò của ${m.name}`}
      className={`${KHUNG_HOP_THOAI} max-w-[420px]`}
    >
      <h2 className="text-the font-semibold text-fg">Đổi vai trò</h2>
      <p className="mt-1 text-than text-muted">{m.name} — chỉ đổi ở workspace đang mở.</p>

      <div className="mt-4 space-y-1.5" role="radiogroup" aria-label="Vai trò">
        {(vaiTro ?? []).map((v) => (
          <label
            key={v.id}
            className="flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 hover:bg-fill"
          >
            <input
              type="radio"
              name="vai-tro"
              value={v.id}
              checked={chon === v.id}
              onChange={() => setChon(v.id)}
            />
            <span className="text-[14px] text-fg">{v.name}</span>
          </label>
        ))}
      </div>

      {luu.error && (
        <p role="alert" className="mt-3 text-[13px] text-badge-alert-fg">
          {luu.error instanceof LoiApi ? luu.error.message : 'Không lưu được vai trò'}
        </p>
      )}

      <div className={`${HANG_NUT} mt-5`}>
        <button type="button" className={NUT_PHU} onClick={onDong}>
          Huỷ
        </button>
        <button
          type="button"
          className={NUT_CHINH}
          disabled={luu.isPending || chon === m.roleId}
          onClick={() => luu.mutate()}
        >
          Lưu
        </button>
      </div>
    </HopThoai>,
    document.body,
  )
}
