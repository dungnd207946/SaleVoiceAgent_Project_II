/**
 * Màn `/workspace` — «Cài đặt workspace», mảng Quản trị.
 *
 * HAI THẺ, và thứ tự của chúng là một quyết định:
 *   ① Thông tin workspace — mã (chỉ đọc) + tên (sửa được) + Lưu.
 *   ② Xoá workspace — viền cảnh báo, nút đỏ, đứng dưới thẻ thông tin.
 *
 * Việc phá huỷ nằm DƯỚI CÙNG và trong một thẻ RIÊNG, không phải một mục trong
 * thẻ đầu. Người vào đây thường để sửa tên; nút xoá đứng cạnh nút Lưu là mời
 * một cú bấm nhầm không hoàn tác được.
 *
 * KHÔNG CÓ `<h1>` — `components/shell/Topbar.tsx` đã render nó từ nhãn nav.
 * Hai `<h2>` dưới đây nói hai chuyện KHÁC tiêu đề màn nên chúng không lặp lại
 * nó (lỗi «cùng một chữ ở ba độ cao» mà `/convos` và `/users` đã dính).
 *
 * ⚠ MÀN NÀY CHỈ SỬA WORKSPACE ĐANG MỞ. Không có ô chọn workspace: backend đối
 * chiếu id trong đường dẫn với workspace của phiên và trả 403 nếu lệch (xem
 * `router._phai_la_workspace_dang_mo`). Muốn sửa workspace khác thì đổi switcher
 * — cùng lối màn `/users` đã chọn.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { CAO_O, HANG_NUT, NUT_CHINH } from '@/components/ui/Bang'
import { O_CHUNG } from '@/components/ui/Truong'
import { useLang } from '@/i18n'
import { useSession } from '@/lib/session'
import { LoiApi } from '@/lib/http'
import { suaWorkspace } from '../api'
import { XoaWorkspaceDialog } from './XoaWorkspaceDialog'

/** Thẻ + tiêu đề TRONG thẻ — đúng khuôn `NhomTruong`/`The` của mọi form khác.
 *  Bản đầu chép khuôn Soniox Console (h2 trần trên nền trang, nhãn 11px
 *  UPPERCASE, cột bó 720px dạt trái) và bị người dùng chê nhỏ + lệch concept
 *  (2026-08-21) — «chữ trần giữa hai thẻ» cũng đúng là lỗi `/api-keys` đã sửa
 *  2026-08-08, không dựng lại. */
const THE = 'rounded-xl border border-border bg-surface p-5'
const TIEU_DE_THE = 'mb-4 text-the font-semibold text-fg'
/** Nhãn ô — cùng số đo với `Khung` của `components/ui/Truong.tsx`. */
const NHAN = 'mb-1.5 block text-phu text-muted'
/** Nút phá huỷ, cỡ nút chính. `NUT_HANG_XOA` của `Bang.tsx` KHÔNG thay được:
 *  nó là nút-trong-một-hàng-bảng (viền mảnh, 12.5px) — đúng cho ô thao tác cuối
 *  một hàng, quá nhẹ cho hành động duy nhất của cả một thẻ. */
const NUT_XOA = `${CAO_O} inline-flex items-center justify-center rounded-md bg-badge-alert-fg px-[15px] text-than font-semibold text-white`

export function CaiDatWorkspace() {
  const { t } = useLang()
  const { currentWorkspace } = useSession()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  // `key` ở `routes/_app.tsx` bọc <Outlet> theo workspace, nên đổi workspace là
  // DỰNG LẠI màn này — `useState` khởi tạo một lần vẫn luôn khớp workspace đang
  // mở. Không cần `useEffect` đồng bộ lại, và không được thêm: một effect ghi đè
  // ô nhập là ô nhập tự xoá chữ người dùng đang gõ.
  const [ten, setTen] = useState(currentWorkspace.name)
  const [daLuu, setDaLuu] = useState(false)
  const [moXoa, setMoXoa] = useState(false)

  const luu = useMutation({
    mutationFn: (tenMoi: string) => suaWorkspace(currentWorkspace.id, tenMoi),
    onSuccess: async () => {
      setDaLuu(true)
      // NẠP LẠI PHIÊN, không chỉ state của màn này. Tên workspace hiện ở switcher
      // (chân sidebar), ở `<h1>` của Topbar, và ở mọi màn đọc `session`. Sửa
      // riêng ở đây là để cả portal nói tên cũ trong khi màn cài đặt nói tên mới.
      await queryClient.invalidateQueries({ queryKey: ['session'] })
    },
  })

  const tenSach = ten.trim()
  const doiDuoc = tenSach !== '' && tenSach !== currentWorkspace.name

  function guiForm(e: React.FormEvent) {
    e.preventDefault()
    if (!doiDuoc || luu.isPending) return
    setDaLuu(false)
    luu.mutate(tenSach)
  }

  return (
    <div className="space-y-3.5 px-7 py-6 max-md:px-4 max-md:py-4">
      <section className={THE}>
        <h2 className={TIEU_DE_THE}>{t({ vi: 'Thông tin workspace', en: 'Workspace info' })}</h2>

        <form onSubmit={guiForm}>
          {/* Hai cột như `LUOI_O` của màn `/agent` — Mã (chỉ đọc) đứng cạnh Tên
              (sửa được), thẻ choán trọn bề ngang màn như mọi màn khác thay vì bó
              trong một cột hẹp. */}
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className={NHAN}>{t({ vi: 'Mã workspace', en: 'Workspace ID' })}</p>
              {/* KHÔNG phải ô nhập — kể cả ô nhập `readonly`. Một ô có viền mời
                  người ta gõ vào, rồi không cho gõ. Đây là một chuỗi để ĐỌC và để
                  copy: nó xuất hiện trong mọi dòng log và trong mọi thông điệp lỗi.
                  `py-[11px]` = padding 10px + viền 1px của `O_CHUNG` — chữ mã nằm
                  ngang hàng chữ trong ô Tên bên cạnh. */}
              <p className="py-[11px] font-mono text-[14px] leading-[1.5] text-nav">
                {currentWorkspace.id}
              </p>
              <p className="mt-1 text-[12px] leading-[1.45] text-muted-2">
                {t({
                  vi: 'Mã này không đổi khi bạn đổi tên, và không sửa được. Nó là thứ xuất hiện trong log và trong các thông điệp lỗi.',
                  en: 'This ID does not change when you rename the workspace, and cannot be edited. It is what appears in logs and error messages.',
                })}
              </p>
            </div>

            <div>
              <label htmlFor="ws-ten" className={NHAN}>
                {t({ vi: 'Tên workspace', en: 'Workspace name' })}
              </label>
              <input
                id="ws-ten"
                value={ten}
                onChange={(e) => {
                  setTen(e.target.value)
                  setDaLuu(false)
                }}
                maxLength={80}
                disabled={luu.isPending}
                aria-describedby={luu.error ? 'ws-ten-loi' : undefined}
                className={O_CHUNG}
              />
            </div>
          </div>

          {luu.error && (
            <p
              id="ws-ten-loi"
              role="alert"
              className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[13px] leading-[1.5] text-badge-alert-fg"
            >
              {luu.error instanceof LoiApi
                ? luu.error.message
                : t({ vi: 'Không lưu được tên mới', en: 'Could not save the new name' })}
            </p>
          )}

          {/* `HANG_NUT`: căn PHẢI, nút chính CUỐI — một khuôn cho cả form
              trong trang lẫn hộp thoại (người dùng chốt 2026-08-08). Chữ xác
              nhận đi TRƯỚC cụm nút, đẩy về trái bằng `mr-auto`: nó là kết quả
              của lần bấm trước, không phải một hành động.
              `role="status"` chứ không `alert` — lưu xong là tin BÌNH THƯỜNG,
              và `alert` cắt ngang thứ trình đọc màn hình đang đọc dở. */}
          <div className={`${HANG_NUT} mt-4`}>
            {/* Vùng tồn tại sẵn, chữ đổ vào sau — vùng mount cùng lúc với chữ thì
                trình đọc màn hình thường bỏ qua. */}
            <span role="status" className="mr-auto text-[13px] text-muted">
              {daLuu && !luu.isPending ? t({ vi: 'Đã lưu', en: 'Saved' }) : null}
            </span>
            <button type="submit" disabled={!doiDuoc || luu.isPending} className={NUT_CHINH}>
              {luu.isPending ? t({ vi: 'Đang lưu…', en: 'Saving…' }) : t({ vi: 'Lưu', en: 'Save' })}
            </button>
          </div>
        </form>
      </section>

      <section className={`${THE} border-badge-alert-fg/25`}>
        <h2 className={TIEU_DE_THE}>{t({ vi: 'Xoá workspace', en: 'Delete workspace' })}</h2>

        <p className="text-than leading-[1.6] text-nav">
          {t({
            vi: 'Xoá workspace là không thể hoàn tác. Toàn bộ dự án, tài liệu, hội thoại và cấu hình agent của nó sẽ bị xoá, và mọi thành viên sẽ mất quyền truy cập ngay lập tức.',
            en: 'Deleting a workspace is irreversible. All of its projects, documents, conversations and agent configuration will be wiped, and every member loses access immediately.',
          })}
        </p>
        <div className={`${HANG_NUT} mt-4`}>
          <button type="button" onClick={() => setMoXoa(true)} className={NUT_XOA}>
            {t({ vi: 'Xoá workspace này', en: 'Delete this workspace' })}
          </button>
        </div>
      </section>

      {moXoa && (
        <XoaWorkspaceDialog
          workspace={currentWorkspace}
          onDong={() => setMoXoa(false)}
          onXong={async () => {
            // RỜI MÀN TRƯỚC, dọn cache SAU — cùng thứ tự `dangXuat()` ở
            // `lib/session.tsx` và cùng lý do: nạp lại phiên trong lúc còn đứng
            // ở màn cài đặt của workspace vừa xoá thì `key` của `routes/_app.tsx`
            // dựng lại màn này cho workspace KHÁC, và người dùng thấy màn cài đặt
            // của một workspace họ không hề mở, chớp qua trên đường đi.
            await navigate({ to: '/dashboard' })
            queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'session' })
            await queryClient.invalidateQueries({ queryKey: ['session'] })
          }}
        />
      )}
    </div>
  )
}
