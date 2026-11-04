/**
 * Màn "Tạo workspace đầu tiên" — chỗ người vừa tự đăng ký rơi vào.
 *
 * KHÔNG có sidebar/rail/topbar: người chưa có workspace không có gì để điều
 * hướng tới, và một panel toàn mục xám là lời mời bấm vào chỗ chắc chắn hỏng.
 * Vì thế màn này đứng NGOÀI `_app`, tự bọc phiên bằng `useSession` của route.
 *
 * Tạo xong họ là "Quản trị" của workspace đó (backend `service.tao()` ghi hàng
 * `memberships` trong cùng giao dịch) — nên đi thẳng `/dashboard` được ngay,
 * không cần một bước "chọn workspace" nào ở giữa.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { KhungXacThuc } from '@/components/ui/KhungXacThuc'
import { LoiApi } from '@/lib/http'
import { taoWorkspace } from '../api'

export function TaoWorkspaceDauTien() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [ten, setTen] = useState('')
  const [loi, setLoi] = useState<LoiApi | null>(null)
  const [dangGui, setDangGui] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setLoi(null)
    setDangGui(true)
    try {
      await taoWorkspace(ten)

      // ─────────────────────────────────────────────────────────────────────
      // `removeQueries`, KHÔNG `invalidateQueries`. Đây là chỗ đã hỏng thật
      // (2026-08-17) và triệu chứng là màn này tự hiện lại sau khi tạo xong.
      //
      // Vì sao invalidate KHÔNG đủ, ba bước nối nhau:
      //   ① Màn này nằm NGOÀI `_app`, nên `SessionProvider` đang unmount ⇒ query
      //      `['session']` là INACTIVE (cache vẫn còn, gcTime mặc định 5 phút).
      //   ② `invalidateQueries` chỉ refetch query ĐANG ACTIVE. Với query inactive
      //      nó chỉ đánh dấu stale, và `await` của nó trả về NGAY — không có
      //      request nào được gửi.
      //   ③ Điều hướng sang `/dashboard` ⇒ provider mount lại ⇒ React Query trả
      //      CACHE CŨ (`currentWorkspaceId: null`) ngay lập tức trong lúc refetch
      //      chạy nền ⇒ `useEffect` của `SessionReady` bắn trước khi phiên mới
      //      về ⇒ `navigate('/tao-workspace-dau-tien', replace: true)`.
      //
      // Xoá hẳn thì không còn gì cũ để trả về: provider mount, thấy rỗng, hiện
      // "Đang tải phiên…" một nhịp rồi nạp phiên MỚI. Cùng lý lẽ `switchWorkspace`
      // (`lib/session.tsx`) đã ghi khi nó chọn `removeQueries` — chỉ khác là ở đó
      // có sẵn phiên mới để `setQueryData`, còn `POST /workspaces` trả
      // `WorkspaceTaoRaOut` chứ không trả `SessionOut`, nên đây phải để provider
      // tự đi lấy.
      //
      // ⚠ ĐỪNG "tối ưu" thành `refetchQueries({type:'all'})` để tránh nhịp splash:
      // nó ghi cache rồi mới điều hướng, nhưng một lần fetch lỗi là cache giữ
      // nguyên bản cũ và cú đá về quay lại y nguyên. Xoá thì lỗi hạ tầng hiện ra
      // thành màn lỗi thật, không thành một vòng lặp câm.
      queryClient.removeQueries({ queryKey: ['session'] })
      await navigate({ to: '/dashboard' })
    } catch (err) {
      setLoi(err instanceof LoiApi ? err : new LoiApi('UNKNOWN', String(err)))
    } finally {
      setDangGui(false)
    }
  }

  return (
    <KhungXacThuc
      tieuDe="Tạo workspace đầu tiên"
      logo={false}
      rong="max-w-[420px]"
      onSubmit={onSubmit}
    >
      {/* <p className="mt-3 text-center text-than leading-[1.55] text-muted">
          Workspace là nơi chứa dữ liệu và cấu hình agent của bạn. Bạn sẽ là quản trị của nó.
        </p> */}

      <label htmlFor="ten-ws" className="mt-7 block text-than font-semibold text-fg">
        Tên workspace
      </label>
      <input
        id="ten-ws"
        type="text"
        required
        maxLength={80}
        placeholder="VD: An Phú Land"
        value={ten}
        onChange={(e) => setTen(e.target.value)}
        className="mt-1.5 h-11 w-full rounded-md border border-border-field bg-surface px-3 text-noi focus:border-ac focus:outline-none focus:ring-[3px] focus:ring-acs"
      />

      {loi && (
        <p
          role="alert"
          className="mt-[18px] rounded-md border border-badge-alert-fg/25 bg-badge-alert-bg px-3 py-3 text-than leading-[1.5] text-badge-alert-fg"
        >
          {loi.code === 'WORKSPACE_TRUNG_TEN' ? 'Bạn đã có một workspace tên này.' : loi.message}
        </p>
      )}

      <button
        type="submit"
        disabled={dangGui || ten.trim() === ''}
        className="mt-[26px] h-[46px] w-full rounded-md bg-ac text-noi font-semibold text-white transition hover:bg-acd active:translate-y-px disabled:opacity-60"
      >
        {dangGui ? 'Đang tạo…' : 'Tạo workspace'}
      </button>
    </KhungXacThuc>
  )
}
